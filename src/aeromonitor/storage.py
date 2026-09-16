"""Persistência idempotente dos alertas antes do commit Kafka."""

import sqlite3
from pathlib import Path

from aeromonitor.models import Alert, CollectionStatus, Position


class AlertStore:
    def __init__(self, path: str):
        """Abra o banco SQLite e crie o diretório e a tabela de alertas se necessário."""
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, timeout=15)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS alerts ("
            "event_id TEXT PRIMARY KEY, kind TEXT NOT NULL, region_id TEXT NOT NULL, "
            "observed_at INTEGER NOT NULL, payload TEXT NOT NULL)"
        )
        self.connection.commit()
        self.connection.executescript("""
            CREATE INDEX IF NOT EXISTS idx_alerts_region_time ON alerts(region_id, observed_at);
            CREATE TABLE IF NOT EXISTS positions (
                region_id TEXT NOT NULL, icao24 TEXT NOT NULL,
                observed_at INTEGER NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY(region_id, icao24)
            );
            CREATE TABLE IF NOT EXISTS collections (
                region_id TEXT PRIMARY KEY, observed_at INTEGER NOT NULL,
                last_success_at INTEGER, payload TEXT NOT NULL
            );
        """)

    def save_position(self, position: Position):
        """Atualize a última posição por região/aeronave sem retroceder no tempo."""
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO positions VALUES (?, ?, ?, ?)
                ON CONFLICT(region_id, icao24) DO UPDATE SET
                    observed_at=excluded.observed_at, payload=excluded.payload
                WHERE excluded.observed_at > positions.observed_at
            """,
                (
                    position.region_id,
                    position.icao24,
                    position.observed_at,
                    position.model_dump_json(),
                ),
            )

    def save_collection(self, status: CollectionStatus):
        """Guarde a tentativa mais recente e preserve a última coleta bem-sucedida."""
        success_at = status.observed_at if status.success else None
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO collections VALUES (?, ?, ?, ?)
                ON CONFLICT(region_id) DO UPDATE SET
                    last_success_at=CASE
                        WHEN excluded.last_success_at IS NULL THEN collections.last_success_at
                        WHEN collections.last_success_at IS NULL THEN excluded.last_success_at
                        ELSE MAX(collections.last_success_at, excluded.last_success_at) END,
                    payload=CASE WHEN excluded.observed_at >= collections.observed_at
                        THEN excluded.payload ELSE collections.payload END,
                    observed_at=MAX(collections.observed_at, excluded.observed_at)
            """,
                (status.region_id, status.observed_at, success_at, status.model_dump_json()),
            )

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
