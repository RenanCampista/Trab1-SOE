"""Seleção persistente da região compartilhada entre painel e produtor local."""

import sqlite3
from contextlib import closing
from pathlib import Path

from aeromonitor.config import AIRPORTS, Settings


def selected_region(path: str, default: str) -> str:
    """Leia a seleção persistida ou retorne o padrão sem criar arquivos."""
    file = Path(path).resolve()
    if not file.exists():
        return default
    with closing(sqlite3.connect(file.as_uri() + "?mode=ro", uri=True, timeout=5)) as conn:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='region_selection'"
        ).fetchone():
            return default
        row = conn.execute("SELECT region FROM region_selection WHERE id=1").fetchone()
    if row is None:
        return default
    if row[0] not in {*AIRPORTS, "custom"}:
        raise ValueError("Seleção de região inválida no banco de controle")
    return row[0]


def select_region(path: str, region: str):
    """Grave atomicamente a região global; a última escolha confirmada prevalece."""
    if region not in {*AIRPORTS, "custom"}:
        raise ValueError("Região desconhecida")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=5)) as conn, conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS region_selection "
            "(id INTEGER PRIMARY KEY CHECK(id=1), region TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO region_selection VALUES (1, ?) "
            "ON CONFLICT(id) DO UPDATE SET region=excluded.region",
            (region,),
        )


def apply_selection(cfg: Settings, default: str) -> bool:
    """Atualize a configuração usada pela API entre ciclos e indique se ela mudou."""
    region = selected_region(cfg.control_database_path, default)
    changed = region != cfg.region
    cfg.region = region
    return changed
