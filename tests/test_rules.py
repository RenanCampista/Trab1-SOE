from aeromonitor.rules import RuleEngine


def kinds(alerts):
    """Extraia os tipos de alerta para comparar resultados sem depender da ordem."""
    return {alert.kind for alert in alerts}


def test_three_simple_rules_and_cooldown(settings, position):
    """Verifique as três regras simples e a liberação de alertas após o cooldown."""
    engine = RuleEngine(settings)
    assert kinds(engine.process(position(vertical_rate_ms=-9))) == {
        "proximity",
        "low_altitude",
        "vertical_movement",
    }
    assert engine.process(position(ts=1030, vertical_rate_ms=-9)) == []
    assert "low_altitude" in kinds(engine.process(position(ts=1700)))


def test_approach_requires_three_descending_closer_positions(settings, position):
    """Verifique a aproximação derivada e os IDs das três observações de origem."""
    engine = RuleEngine(settings)
    engine.process(position(ts=1000, distance=14, altitude=1500))
    engine.process(position(ts=1030, distance=12, altitude=1300))
    result = engine.process(position(ts=1060, distance=10, altitude=1100))
    derived = [a for a in result if a.kind == "possible_approach"]
    assert len(derived) == 1
    assert derived[0].source_event_ids == [f"vitoria:abc123:{t}" for t in (1000, 1030, 1060)]


def test_repeated_or_out_of_order_events_do_not_create_approach(settings, position):
    """Verifique que duplicatas e eventos atrasados não completam uma aproximação."""
    engine = RuleEngine(settings)
    engine.process(position(ts=1000, distance=14, altitude=1500))
    assert engine.process(position(ts=1000)) == []
    assert engine.process(position(ts=999)) == []
    assert "possible_approach" not in kinds(engine.process(position(ts=1030)))


def test_gap_breaks_approach(settings, position):
    """Verifique que uma lacuna longa reinicia a sequência de aproximação."""
    engine = RuleEngine(settings)
    engine.process(position(ts=1000, distance=14, altitude=1500))
    engine.process(position(ts=1030, distance=12, altitude=1300))
    assert "possible_approach" not in kinds(engine.process(position(ts=1400)))


def test_region_histories_are_separate(settings, position):
    """Verifique que posições de regiões distintas não formam uma sequência comum."""
    engine = RuleEngine(settings)
    engine.process(position(ts=1000, distance=14, altitude=1500))
    engine.process(position(ts=1030, distance=12, altitude=1300))
    assert "possible_approach" not in kinds(
        engine.process(position(ts=1060, region_id="guarulhos"))
    )


def test_ground_and_missing_altitude_do_not_generate_approach(settings, position):
    """Verifique que solo ou ausência de altitude impedem inferir aproximação."""
    engine = RuleEngine(settings)
    assert engine.process(position(on_ground=True, vertical_rate_ms=10)) == []
    engine.process(position(ts=1030, altitude=None))
    assert "possible_approach" not in kinds(engine.process(position(ts=1060)))


def test_receding_aircraft_is_not_approaching(settings, position):
    """Verifique que descer enquanto se afasta não caracteriza aproximação."""
    engine = RuleEngine(settings)
    for index in range(3):
        result = engine.process(
            position(ts=1000 + index * 30, distance=10 + index, altitude=1500 - index * 100)
        )
        assert "possible_approach" not in kinds(result)
