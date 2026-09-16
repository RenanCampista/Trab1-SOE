import pytest

from aeromonitor.config import Settings
from aeromonitor.models import distance_km, normalize


def row(**changes):
    """Monte um vetor OpenSky sintético, substituindo os índices solicitados."""
    data = ["abc123", " TEST123 ", "Brazil", 1000, 1000, -40.286, -20.258, 900, False, 100, 180, -3]
    for key, value in changes.items():
        data[int(key)] = value
    return data


def test_normalization_and_units(settings):
    """Verifique limpeza do callsign, unidades preservadas e distância ao centro."""
    p = normalize(row(), settings.monitored_region(), 1010, 90)
    assert p.callsign == "TEST123"
    assert p.altitude_m == 900
    assert p.velocity_ms == 100
    assert p.distance_km == pytest.approx(0)


@pytest.mark.parametrize(
    "data",
    [
        [],
        row(**{"3": None}),
        row(**{"6": None}),
        row(**{"3": 800}),
        row(**{"3": 2000}),
        row(**{"5": -46}),
        row(**{"9": float("nan")}),
    ],
)
def test_invalid_stale_future_and_outside_positions_are_filtered(settings, data):
    """Verifique o descarte de posições inválidas, antigas, futuras ou fora da região."""
    assert normalize(data, settings.monitored_region(), 1010, 90) is None


def test_distance_and_region_settings(settings):
    """Verifique distância conhecida, inclusão do centro e IDs distintos por região."""
    assert 110 < distance_km(0, 0, 1, 0) < 112
    bounds = settings.monitored_region().bounds()
    assert bounds["lamin"] < -20.258 < bounds["lamax"]
    other = Settings(_env_file=None, region="galeao").monitored_region()
    assert settings.monitored_region().id != other.id


def test_partial_credentials_rejected(settings):
    """Verifique que um client ID sem segredo torna a configuração inválida."""
    with pytest.raises(ValueError, match="juntos"):
        Settings(_env_file=None, opensky_client_id="id")
