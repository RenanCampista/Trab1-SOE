"""Contrato entre coleta, processador e destino, sem broker externo."""

from aeromonitor.cli import collect
from aeromonitor.models import Alert, Position
from aeromonitor.rules import RuleEngine
from aeromonitor.storage import AlertStore


def test_api_vectors_to_derived_alert_in_database(settings, tmp_path, monkeypatch):
    """Verifique coleta, contratos JSON, regras e persistência em um fluxo offline."""
    engine = RuleEngine(settings)
    store = AlertStore(str(tmp_path / "alerts.db"))

    class FakeAPI:
        def __init__(self, timestamp, latitude, altitude):
            """Prepare uma resposta sintética com instante e posição controlados."""
            self.payload = {
                "states": [
                    [
                        "abc123",
                        " TEST123 ",
                        "Brazil",
                        timestamp,
                        timestamp,
                        -40.286,
                        latitude,
                        altitude,
                        False,
                        100,
                        180,
                        -9,
                    ]
                ]
            }

        def fetch(self):
            """Retorne os estados simulados sem realizar acesso à rede."""
            return self.payload

    for ts, lat, altitude in [(1000, -20.16, 900), (1030, -20.18, 800), (1060, -20.20, 700)]:
        monkeypatch.setattr("aeromonitor.cli.time.time", lambda ts=ts: ts)
        positions = collect(FakeAPI(ts, lat, altitude), settings)
        assert len(positions) == 1
        wire_position = Position.model_validate_json(positions[0].model_dump_json())
        for alert in engine.process(wire_position):
            assert store.save(Alert.model_validate_json(alert.model_dump_json()))
    kinds = {row[0] for row in store.connection.execute("SELECT kind FROM alerts")}
    assert kinds == {"proximity", "low_altitude", "vertical_movement", "possible_approach"}
    store.close()
