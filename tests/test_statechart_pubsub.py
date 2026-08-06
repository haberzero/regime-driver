"""Tests for stage-2 pub/sub: topic-based events with explicit subscription."""

from regime_driver.core.statechart import Bus, SignalKind, StatechartUnit


def test_emit_dispatches_to_subscriber():
    bus = Bus()
    publisher = StatechartUnit("work", bus=bus)
    bus.register(publisher)
    got = []
    observer = StatechartUnit("observer", bus=bus)
    observer.on_event("watchdog_fire", lambda p: got.append(p.get("kind")))
    observer.subscribe("watchdog_fire")
    bus.register(observer)
    publisher.emit("watchdog_fire", kind="stall")
    assert got == ["stall"]


def test_unsubscribed_units_do_not_receive_event():
    bus = Bus()
    pub = StatechartUnit("pub", bus=bus)
    bus.register(pub)
    got = []
    obs = StatechartUnit("obs", bus=bus)
    obs.on_event("watchdog_fire", lambda p: got.append(1))
    bus.register(obs)
    pub.emit("watchdog_fire")  # not subscribed -> observer ignores via handle_event
    assert got == []
    # now subscribe and it receives
    obs.subscribe("watchdog_fire")
    pub.emit("watchdog_fire")
    assert got == [1]


def test_topic_filtering():
    """Only subscribers of a specific topic receive it; others don't."""
    bus = Bus()
    pub = StatechartUnit("pub", bus=bus)
    bus.register(pub)
    a = StatechartUnit("observer")
    a.on_event("topic_a", lambda p: a_got.append(1))
    b = StatechartUnit("observer")
    b.on_event("topic_b", lambda p: b_got.append(1))
    a_got, b_got = [], []
    a.bus = b.bus = bus
    a.subscribe("topic_a")
    b.subscribe("topic_b")
    bus.register(a).register(b)
    pub.emit("topic_a")
    pub.emit("topic_b")
    assert a_got == [1]
    assert b_got == [1]
    assert bus.events()[-2][1] == "topic_a"
    assert bus.events()[-1][1] == "topic_b"


def test_unsubscribe_stops_delivery():
    bus = Bus()
    pub = StatechartUnit("pub", bus=bus)
    bus.register(pub)
    got = []
    obs = StatechartUnit("obs", bus=bus)
    obs.on_event("e", lambda p: got.append(1))
    obs.subscribe("e")
    bus.register(obs)
    pub.emit("e")
    obs.unsubscribe("e")
    pub.emit("e")
    assert got == [1]


def test_emit_still_logs_audit_event():
    bus = Bus()
    pub = StatechartUnit("pub", bus=bus)
    bus.register(pub)
    pub.emit("some_event", a=1)
    assert bus.events()[-1] == ("pub", "some_event", {"a": 1})


def test_handle_event_unhandled_returns_false():
    unit = StatechartUnit("u")
    assert unit.handle_event("nope", {}) is False
    assert unit.has_event("nope") is False