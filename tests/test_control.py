"""Seleção na interface, persistência e aplicação pelo produtor."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from aeromonitor.cli import run_producer
from aeromonitor.control import apply_selection, select_region, selected_region


def test_persistent_selection_and_validation(settings):
    """Use o padrão até uma escolha válida e persista a seleção entre leituras."""
    path = settings.control_database_path
    assert selected_region(path, "vitoria") == "vitoria"
    assert not Path(path).exists()
    select_region(path, "galeao")
    assert apply_selection(settings, "vitoria")
    assert settings.region == "galeao"
    assert not apply_selection(settings, "vitoria")
    with pytest.raises(ValueError):
        select_region(path, "desconhecida")
    assert selected_region(path, "vitoria") == "galeao"


def test_dashboard_selection_changes_region(settings, tmp_path, monkeypatch):
    """Confirme a cidade pela interface e restaure a escolha em uma nova sessão."""
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "dashboard.db"))
    script = Path("src/aeromonitor/dashboard.py").resolve()
    app = AppTest.from_file(script).run(timeout=20)
    app.selectbox[0].set_value("guarulhos")
    app.button[0].click().run()
    assert not app.exception
    assert app.metric[0].value == "Guarulhos"
    assert selected_region(settings.control_database_path, "vitoria") == "guarulhos"
    other = AppTest.from_file(script).run(timeout=20)
    assert other.selectbox[0].value == "guarulhos"
    assert other.metric[1].value == "0"


def test_producer_changes_region_between_cycles(settings, monkeypatch):
    """Aplique a escolha após a espera, sem consultas extras nem reinício do serviço."""
    regions = []
    delays = []

    class Stop:
        """Encerre após dois ciclos e altere a região durante a primeira espera."""

        def is_set(self):
            """Informe se os dois ciclos foram concluídos."""
            return len(delays) == 2

        def wait(self, delay):
            """Registre a espera e simule a alteração feita pelo painel."""
            delays.append(delay)
            select_region(settings.control_database_path, "galeao")

    class FakeAPI:
        """Substitua o cliente externo durante o teste do laço de coleta."""

        def __init__(self, cfg):
            """Guarde a configuração compartilhada com o produtor."""
            self.settings = cfg

        def close(self):
            """Encerre o cliente sem recursos externos."""

    def collect(api, cfg):
        """Registre a região que seria usada na requisição."""
        assert api.settings is cfg
        regions.append(cfg.region)
        return []

    monkeypatch.setattr("aeromonitor.cli.OpenSky", FakeAPI)
    monkeypatch.setattr("aeromonitor.cli.Publisher", lambda cfg: None)
    monkeypatch.setattr("aeromonitor.cli.collect", collect)
    monkeypatch.setattr("aeromonitor.cli.publish_status", lambda *args: None)
    run_producer(settings, Stop())
    assert regions == ["vitoria", "galeao"]
    assert delays == [settings.poll_interval_seconds] * 2
