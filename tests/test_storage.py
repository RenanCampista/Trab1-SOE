from aeromonitor.rules import RuleEngine
from aeromonitor.storage import AlertStore


def test_duplicate_alert_is_stored_once_across_restart(tmp_path, settings, position):
    """Verifique a deduplicação persistente mesmo após reabrir a conexão SQLite."""
    alert = RuleEngine(settings).process(position())[0]
    path = str(tmp_path / "alerts.db")
    store = AlertStore(path)
    assert store.save(alert)
    store.close()
    store = AlertStore(path)
    assert not store.save(alert)
    assert store.connection.execute("SELECT count(*) FROM alerts").fetchone()[0] == 1
    store.close()
