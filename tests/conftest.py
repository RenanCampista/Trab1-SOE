import pytest

from aeromonitor.config import Settings
from aeromonitor.models import Position


@pytest.fixture
def settings(monkeypatch, tmp_path):
    """Forneça configurações padrão isoladas do ambiente e do arquivo .env."""
    for key in Settings.model_fields:
        monkeypatch.delenv(key.upper(), raising=False)
    monkeypatch.setenv("CONTROL_DATABASE_PATH", str(tmp_path / "control.db"))
    return Settings(_env_file=None)


@pytest.fixture
def position():
    """Forneça uma fábrica de posições sintéticas com campos personalizáveis."""

    def make(ts=1000, distance=10, altitude=900, **overrides):
        """Crie uma posição com tempo Unix, distância em km e altitude em metros."""
        values = dict(
            event_id=f"vitoria:abc123:{ts}",
            region_id="vitoria",
            region_name="Vitória",
            icao24="abc123",
            callsign="TEST123",
            observed_at=ts,
            collected_at=ts,
            latitude=-20.3,
            longitude=-40.3,
            altitude_m=altitude,
            on_ground=False,
            velocity_ms=100,
            vertical_rate_ms=-3,
            distance_km=distance,
        )
        values.update(overrides)
        return Position(**values)

    return make
