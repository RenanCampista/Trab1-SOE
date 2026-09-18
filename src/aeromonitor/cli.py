"""Entradas dos serviços e consulta de diagnóstico sem Kafka."""

import argparse
import logging
import signal
import threading
import time

import httpx
from confluent_kafka import KafkaException
from pydantic import ValidationError

from aeromonitor.broker import ALERTS, COLLECTIONS, DERIVED, POSITIONS, Publisher, consumer
from aeromonitor.config import Settings
from aeromonitor.control import apply_selection
from aeromonitor.models import Alert, CollectionStatus, Position, normalize
from aeromonitor.opensky import OpenSky, RateLimited
from aeromonitor.rules import RuleEngine
from aeromonitor.storage import AlertStore

log = logging.getLogger(__name__)


def collect(api: OpenSky, cfg: Settings) -> list[Position]:
    """Faça uma consulta e retorne posições recentes e válidas dentro da região.

    Registra as contagens recebida e válida; propaga falhas da API ao chamador.
    """
    payload = api.fetch()
    now = int(time.time())
    region = cfg.monitored_region()
    rows = payload.get("states") or []
    positions = [
        p
        for row in rows
        if (p := normalize(row, region, now, cfg.max_position_age_seconds)) is not None
    ]
    log.info(
        "%s: %d vetores recebidos; %d posições válidas", region.name, len(rows), len(positions)
    )
    return positions


def run_producer(cfg: Settings, stop: threading.Event):
    """Colete e publique posições até stop ser sinalizado, fechando a API ao sair.

    Suprime posições já publicadas em memória e aguarda entre consultas, respeitando
    rate limit e backoff. Falhas Kafka e erros HTTP de acesso encerram o serviço.
    """
    api, publisher = OpenSky(cfg), Publisher(cfg)
    seen: dict[str, int] = {}
    default_region = cfg.region
    failures = 0
    try:
        while not stop.is_set():
            if apply_selection(cfg, default_region):
                seen.clear()
                log.info("Região alterada para %s", cfg.monitored_region().name)
            delay = cfg.poll_interval_seconds
            success, valid_count, detail = False, 0, "Falha na coleta"
            try:
                positions = collect(api, cfg)
                valid_count = len(positions)
                success, detail = True, "Consulta concluída"
                for p in positions:
                    if p.observed_at <= seen.get(p.icao24, -1):
                        continue
                    publisher.send(POSITIONS, f"{p.region_id}:{p.icao24}", p)
                    seen[p.icao24] = p.observed_at
                cutoff = time.time() - 3600
                seen = {key: ts for key, ts in seen.items() if ts >= cutoff}
                failures = 0
            except RateLimited as exc:
                log.warning("%s", exc)
                delay = max(delay, exc.seconds)
                detail = "Limite de consultas da OpenSky; aguardando liberação"
            except httpx.HTTPStatusError as exc:
                detail = f"OpenSky respondeu HTTP {exc.response.status_code}"
                if exc.response.status_code in (400, 401, 403):
                    publish_status(publisher, cfg, False, 0, detail, delay)
                    raise RuntimeError(
                        "OpenSky recusou a consulta; revise acesso/configuração"
                    ) from exc
                failures += 1
                delay = max(delay, min(900, 30 * 2 ** min(failures, 5)))
                log.warning(
                    "OpenSky HTTP %s; nova tentativa em %.0fs", exc.response.status_code, delay
                )
            except (httpx.RequestError, ValueError) as exc:
                failures += 1
                delay = max(delay, min(900, 30 * 2 ** min(failures, 5)))
                log.warning(
                    "Falha na coleta (%s); nova tentativa em %.0fs", type(exc).__name__, delay
                )
                detail = "Falha de conexão ou resposta inválida da OpenSky"
            publish_status(publisher, cfg, success, valid_count, detail, delay)
            stop.wait(delay)
    finally:
        api.close()


def publish_status(publisher, cfg, success, valid_count, detail, delay):
    """Publique o resultado e o prazo da próxima tentativa sem expor credenciais."""
    now = int(time.time())
    region_id = cfg.monitored_region().id
    publisher.send(
        COLLECTIONS,
        region_id,
        CollectionStatus(
            region_id=region_id,
            observed_at=now,
            success=success,
            valid_positions=valid_count,
            detail=detail,
            next_attempt_at=now + int(delay),
        ),
    )


def run_visualization(cfg: Settings, stop: threading.Event):
    """Persista posições, alertas e coletas em um grupo Kafka independente."""
    client = consumer(
        cfg, "aeromonitor-visualization-v1", [POSITIONS, ALERTS, DERIVED, COLLECTIONS]
    )
    store = AlertStore(cfg.database_path)
    models = {POSITIONS: Position, ALERTS: Alert, DERIVED: Alert, COLLECTIONS: CollectionStatus}
    try:
        while not stop.is_set():
            message = client.poll(1)
            if message is None:
                continue
            if message.error():
                raise KafkaException(message.error())
            event = models[message.topic()].model_validate_json(message.value())
            if isinstance(event, Position):
                store.save_position(event)
            elif isinstance(event, CollectionStatus):
                store.save_collection(event)
            else:
                store.save(event)
            client.commit(message=message, asynchronous=False)
    finally:
        client.close()
        store.close()


def run_consumer(cfg: Settings, stop: threading.Event, processor: bool):
    """Consuma eventos até stop ser sinalizado e libere os recursos ao encerrar.

    Com processor=True, avalia posições e publica alertas; caso contrário, persiste
    e imprime alertas. Confirma offsets somente após concluir a ação correspondente.
    Falhas de validação, publicação ou persistência são propagadas sem esse commit.
    """
    topics = [POSITIONS] if processor else [ALERTS, DERIVED]
    client = consumer(
        cfg, "aeromonitor-processor-v1" if processor else "aeromonitor-alerts-v1", topics
    )
    engine = RuleEngine(cfg) if processor else None
    publisher = Publisher(cfg) if processor else None
    store = None if processor else AlertStore(cfg.database_path)
    try:
        while not stop.is_set():
            message = client.poll(1)
            if message is None:
                continue
            if message.error():
                raise KafkaException(message.error())
            try:
                event = (Position if processor else Alert).model_validate_json(message.value())
            except ValidationError:
                # Falha explícita preserva o offset; não descarta silenciosamente eventos inválidos.
                log.error("Evento inválido em %s/%s", message.topic(), message.offset())
                raise
            if processor:
                for alert in engine.process(event):
                    topic = DERIVED if alert.kind == "possible_approach" else ALERTS
                    publisher.send(topic, f"{alert.region_id}:{alert.icao24}", alert)
                    log.info("%s: %s (%s)", alert.kind, alert.callsign, alert.region_name)
                engine.prune(event.observed_at)
            elif store.save(event):
                print(event.model_dump_json(), flush=True)
            client.commit(message=message, asynchronous=False)
    finally:
        client.close()
        if store:
            store.close()


def main():
    """Leia argumentos e configuração, prepare sinais/logs e execute o comando CLI."""
    parser = argparse.ArgumentParser(description="Monitor OpenSky + Kafka")
    parser.add_argument(
        "command", choices=["producer", "processor", "alerts", "visualization", "probe", "config"]
    )
    args = parser.parse_args()
    cfg = Settings()
    logging.basicConfig(level=cfg.log_level, format="%(asctime)s %(levelname)s %(message)s")
    # Bibliotecas HTTP não devem imprimir URLs/cabeçalhos em logs normais.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    if args.command == "config":
        region = cfg.monitored_region()
        print(f"{region.name} | raio={region.radius_km} km | bbox={region.bounds()}")
    elif args.command == "probe":
        api = OpenSky(cfg)
        try:
            for position in collect(api, cfg):
                print(position.model_dump_json())
        finally:
            api.close()
    elif args.command == "producer":
        run_producer(cfg, stop)
    elif args.command == "visualization":
        run_visualization(cfg, stop)
    else:
        run_consumer(cfg, stop, processor=args.command == "processor")
