"""Regras simples e inferência temporal; nenhum evento confirma pouso ou destino."""

from collections import deque

from aeromonitor.config import Settings
from aeromonitor.models import Alert, Position


class RuleEngine:
    def __init__(self, settings: Settings):
        """Inicialize históricos e cooldowns em memória com os limites configurados."""
        self.settings = settings
        self.history: dict[tuple[str, str], deque[Position]] = {}
        self.emitted: dict[tuple[str, str, str], int] = {}

    def process(self, p: Position) -> list[Alert]:
        """Atualize o histórico e retorne alertas simples ou de possível aproximação.

        Ignora posições repetidas ou fora de ordem, reinicia sequências com lacunas
        longas e aplica cooldown por regra, região e aeronave usando o tempo do evento.
        """
        cfg = self.settings
        key = (p.region_id, p.icao24)
        history = self.history.setdefault(key, deque(maxlen=cfg.approach_samples))
        if history and p.observed_at <= history[-1].observed_at:
            return []
        if history and p.observed_at - history[-1].observed_at > cfg.approach_max_gap_seconds:
            history.clear()
        history.append(p)
        candidates: list[tuple[str, str, list[Position]]] = []
        if not p.on_ground:
            if p.distance_km <= cfg.proximity_km:
                candidates.append(("proximity", "Aeronave próxima ao centro monitorado", [p]))
            if p.altitude_m is not None and p.altitude_m < cfg.low_altitude_m:
                candidates.append(("low_altitude", "Altitude barométrica abaixo do limite", [p]))
            if (
                p.vertical_rate_ms is not None
                and abs(p.vertical_rate_ms) >= cfg.vertical_rate_threshold_ms
            ):
                candidates.append(("vertical_movement", "Taxa vertical acima do limite", [p]))
        if len(history) == cfg.approach_samples and p.distance_km <= cfg.proximity_km:
            valid = all(x.altitude_m is not None and not x.on_ground for x in history)
            if valid and all(
                a.distance_km - b.distance_km >= cfg.approach_min_distance_drop_km
                and a.altitude_m - b.altitude_m >= cfg.approach_min_altitude_drop_m
                for a, b in zip(history, list(history)[1:], strict=False)
            ):
                candidates.append(
                    (
                        "possible_approach",
                        "Possível aproximação; destino não confirmado",
                        list(history),
                    )
                )
        alerts = []
        for kind, message, sources in candidates:
            alert_key = (*key, kind)
            previous = self.emitted.get(alert_key)
            if previous is not None and p.observed_at - previous < cfg.alert_cooldown_seconds:
                continue
            self.emitted[alert_key] = p.observed_at
            alerts.append(
                Alert(
                    event_id=f"{p.event_id}:{kind}",
                    kind=kind,
                    region_id=p.region_id,
                    region_name=p.region_name,
                    icao24=p.icao24,
                    callsign=p.callsign,
                    observed_at=p.observed_at,
                    message=message,
                    source_event_ids=[x.event_id for x in sources],
                )
            )
        return alerts

    def prune(self, now: int):
        """Remova estados antigos em relação a now, expresso em segundos Unix.

        Preserva o maior intervalo entre a janela de aproximação e o cooldown.
        """
        horizon = max(self.settings.approach_max_gap_seconds, self.settings.alert_cooldown_seconds)
        self.history = {
            key: values
            for key, values in self.history.items()
            if values and now - values[-1].observed_at <= horizon
        }
        self.emitted = {key: ts for key, ts in self.emitted.items() if now - ts <= horizon}
