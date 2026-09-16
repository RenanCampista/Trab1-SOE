"""Persistência idempotente dos alertas antes do commit Kafka."""

import sqlite3
from pathlib import Path

from aeromonitor.models import Alert


class AlertStore:
    def __init__(self, path: str):
        """Abra o banco SQLite e crie o diretório e a tabela de alertas se necessário."""
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS alerts ("
            "event_id TEXT PRIMARY KEY, kind TEXT NOT NULL, region_id TEXT NOT NULL, "
            "observed_at INTEGER NOT NULL, payload TEXT NOT NULL)"
        )
        self.connection.commit()

    def save(self, alert: Alert) -> bool:
        """Grave e confirme o alerta, retornando True apenas para uma nova inserção.

        IDs já existentes são ignorados; falhas SQLite são propagadas ao chamador.
        """
        with self.connection:
            cursor = self.connection.execute(
                "INSERT OR IGNORE INTO alerts VALUES (?, ?, ?, ?, ?)",
                (
                    alert.event_id,
                    alert.kind,
                    alert.region_id,
                    alert.observed_at,
                    alert.model_dump_json(),
                ),
            )
        return cursor.rowcount == 1

    def close(self):
        """Feche a conexão com o banco de alertas."""
        self.connection.close()
