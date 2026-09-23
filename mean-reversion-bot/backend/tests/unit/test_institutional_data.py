import pytest

from app.institutional.data import BookEvent, Observation, OrderBook, point_in_time, replay


def event(**changes):
    values = dict(venue="A", symbol="TEST", currency="USD", event_ms=100, received_ms=110,
                  sequence=1, bids=[{"price": 99, "size": 30}], asks=[{"price": 101, "size": 10}])
    return BookEvent(**(values | changes))


def test_features_and_atomic_delta():
    book = OrderBook("A", "TEST", "USD")
    book.apply(event())
    values = book.features(120)
    assert values["mid"] == 100
    assert values["microprice"] == 100.5
    assert values["top_imbalance"] == .5
    book.apply(event(kind="delta", sequence=2, bids=[{"price": 99, "size": 0}, {"price": 98, "size": 20}], asks=[]))
    assert book.features(120)["mid"] == 99.5
    with pytest.raises(ValueError, match="uncrossed"):
        book.apply(event(kind="delta", sequence=3, bids=[{"price": 102, "size": 1}], asks=[]))
    assert book.bids == {98: 20}
    assert not book.ready


def test_gap_requires_snapshot_and_never_consumes_partial_update():
    book = OrderBook("A", "TEST", "USD")
    book.apply(event())
    with pytest.raises(ValueError, match="Sequence gap"):
        book.apply(event(kind="delta", sequence=3))
    with pytest.raises(ValueError, match="not ready"):
        book.features(120)
    with pytest.raises(ValueError, match="Sequence gap"):
        book.apply(event(kind="delta", sequence=2))
    book.apply(event(sequence=4))
    assert book.ready


@pytest.mark.parametrize("changes", [
    {"bids": [{"price": 99, "size": -1}]},
    {"asks": [{"price": float("nan"), "size": 1}]},
    {"received_ms": 99}, {"sequence": 1.5},
    {"bids": [{"price": 99, "size": 1}, {"price": 99, "size": 2}]},
])
def test_invalid_events_rejected(changes):
    with pytest.raises(ValueError):
        event(**changes)


def test_stale_future_and_duplicate_books_rejected():
    book = OrderBook("A", "TEST", "USD")
    book.apply(event())
    for now in (109, 2000):
        with pytest.raises(ValueError, match="Stale or future"):
            book.features(now)
    with pytest.raises(ValueError, match="Duplicate"):
        book.apply(event())


def test_point_in_time_publication_delay_revisions_and_expiry():
    original = Observation(name="macro", event_ms=100, available_ms=200, value=1, source="test")
    revision = Observation(name="macro", event_ms=100, available_ms=300, value=2, source="test")
    assert point_in_time([revision, original], [150, 200, 299, 300, 401], 300) == [
        {"macro": None}, {"macro": 1}, {"macro": 1}, {"macro": 2}, {"macro": None}]


def test_replay_is_reproducible_and_rejects_reordered_arrivals():
    events = [event(), event(sequence=2, event_ms=120, received_ms=130)]
    assert replay(events) == replay(events)
    assert len(replay(events)["data_hash"]) == 64
    with pytest.raises(ValueError, match="ordered by received_ms"):
        replay(list(reversed(events)))
