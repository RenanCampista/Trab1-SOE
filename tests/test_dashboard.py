"""Validação do armazenamento da visualização e da interface sem serviços externos."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from aeromonitor.dashboard_data import collection_health, snapshot
from aeromonitor.models import CollectionStatus
from aeromonitor.rules import RuleEngine
from aeromonitor.storage import AlertStore


def test_snapshot_filters_region_age_and_out_of_order(tmp_path, settings, position):
    """Mantenha a posição mais nova e exclua outras regiões ou posições expiradas."""
    path = str(tmp_path / "dashboard.db")
    store = AlertStore(path)
    store.save_position(position(ts=1000))
    store.save_position(position(ts=900))
    store.save_position(position(ts=1000, icao24="other", region_id="galeao"))
    for alert in RuleEngine(settings).process(position(ts=1000)):
        store.save(alert)
    data = snapshot(path, "vitoria", 1010, 90, 1)
    assert len(data["positions"]) == 1
    assert data["positions"][0]["observed_at"] == 1000
    assert len(data["alerts"]) == 2
    assert snapshot(path, "vitoria", 1100, 90, 1)["positions"] == []
    store.close()


def test_collection_keeps_last_success_on_failure_and_replay(tmp_path):
    """Preserve o último sucesso e impeça regressão do estado em replay fora de ordem."""
    path = str(tmp_path / "dashboard.db")
    store = AlertStore(path)
    for ts, success in [(1000, True), (1100, False), (900, True)]:
        store.save_collection(
            CollectionStatus(
                region_id="vitoria",
                observed_at=ts,
                success=success,
                detail="Teste",
                next_attempt_at=ts + 240,
            )
        )
    data = snapshot(path, "vitoria", 1100, 90, 1)
    assert data["last_success_at"] == 1000
    assert data["collection"]["success"] is False
    assert collection_health(data["collection"], 1100)[0] == "error"
    assert collection_health(data["collection"], 1500)[0] == "warning"
    store.close()


def test_missing_database_and_empty_success(tmp_path):
    """Distinga ausência de coleta de uma consulta bem-sucedida sem posições."""
    data = snapshot(str(tmp_path / "missing.db"), "vitoria", 1000, 90, 1)
    assert data["collection"] is None
    assert "primeira coleta" in collection_health(None, 1000)[1]
    state = {"success": True, "valid_positions": 0, "next_attempt_at": 1240}
    assert "sem posições válidas" in collection_health(state, 1000)[1]


def test_dashboard_empty_state(tmp_path, settings, monkeypatch):
    """Abra a interface sem banco, apresentando espera sem erros de execução."""
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "missing.db"))
    app = AppTest.from_file(Path("src/aeromonitor/dashboard.py").resolve()).run(timeout=20)
    assert not app.exception
    assert app.title[0].value == "AeroMonitor"
    assert any("primeira coleta" in item.value for item in app.info)


def test_dashboard_filters_populated_data(tmp_path, settings, position, monkeypatch):
    """Exiba dados reais do SQLite e aplique filtros de aeronave e tipo de alerta."""
    import time

    path = str(tmp_path / "dashboard.db")
    monkeypatch.setenv("DATABASE_PATH", path)
    now = int(time.time())
    region_id = settings.monitored_region().id
    p = position(ts=now, region_id=region_id)
    store = AlertStore(path)
    store.save_position(p)
    for alert in RuleEngine(settings).process(p):
        store.save(alert)
    store.save_collection(
        CollectionStatus(
            region_id=region_id,
            observed_at=now,
            success=True,
            valid_positions=1,
            detail="OK",
            next_attempt_at=now + 240,
        )
    )
    store.close()
    app = AppTest.from_file(Path("src/aeromonitor/dashboard.py").resolve()).run(timeout=20)
    assert not app.exception
    assert app.metric[1].value == "1"
    assert app.metric[2].value == "2"
    app.multiselect[0].set_value(["proximity"]).run()
    assert app.metric[2].value == "1"
    app.text_input[0].set_value("INEXISTENTE").run()
    assert not app.exception
    assert app.metric[1].value == "0"
    assert app.metric[2].value == "0"
