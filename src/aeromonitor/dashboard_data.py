"""Consultas somente leitura para a interface; nenhum acesso direto à OpenSky."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path


def snapshot(path: str, region_id: str, now: int, max_age: int, hours: int) -> dict:
    """Lê posições recentes, alertas e coleta da região em uma única transação.

    Retorna estado vazio se o banco ainda não existir. Falhas SQLite são propagadas
    para a interface sinalizar indisponibilidade, sem confundir com ausência de dados.
    """
    result = {"positions": [], "alerts": [], "collection": None, "last_success_at": None}
    file = Path(path).resolve()
    if not file.exists():
        return result
    with closing(sqlite3.connect(file.as_uri() + "?mode=ro", uri=True, timeout=5)) as conn:
        conn.execute("BEGIN")
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if "positions" in tables:
            result["positions"] = [
                json.loads(row[0])
                for row in conn.execute(
                    "SELECT payload FROM positions WHERE region_id=? "
                    "AND observed_at BETWEEN ? AND ?",
                    (region_id, now - max_age, now),
                )
            ]
        if "alerts" in tables:
            result["alerts"] = [
                json.loads(row[0])
                for row in conn.execute(
                    "SELECT payload FROM alerts WHERE region_id=? AND observed_at BETWEEN ? AND ? "
                    "ORDER BY observed_at DESC LIMIT 1000",
                    (region_id, now - hours * 3600, now),
                )
            ]
        if "collections" in tables:
            row = conn.execute(
                "SELECT payload, last_success_at FROM collections WHERE region_id=?", (region_id,)
            ).fetchone()
            if row:
                result["collection"], result["last_success_at"] = json.loads(row[0]), row[1]
    return result


def collection_health(status: dict | None, now: int) -> tuple[str, str]:
    """Classifica a coleta usando o prazo anunciado e uma tolerância de 60 segundos."""
    if status is None:
        return "info", "Aguardando a primeira coleta desta região."
    if now > status["next_attempt_at"] + 60:
        return "warning", "Coleta sem atualização no prazo esperado. Verifique os serviços."
    if not status["success"]:
        return "error", status["detail"]
    if status["valid_positions"] == 0:
        return (
            "info",
            "Consulta concluída, sem posições válidas. "
            "Pode haver pouco movimento ou falta de cobertura.",
        )
    return "success", "Coleta ativa. Posições e alertas são atualizados automaticamente."
