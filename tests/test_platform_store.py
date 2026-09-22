"""Run the same lifecycle tests against SQLite locally and PostgreSQL in CI."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
import os
import uuid

import pytest
from sqlalchemy import text

from jabazi.domain.portfolio import Position, Limits
from jabazi.persistence.store import Store, Conflict


@pytest.fixture(
    params=["sqlite"] + (["postgres"] if os.getenv("JABBAZI_TEST_POSTGRES_URL") else [])
)
def store(request, tmp_path):
    url = (
        "sqlite:///" + str(tmp_path / "platform.db")
        if request.param == "sqlite"
        else os.environ["JABBAZI_TEST_POSTGRES_URL"]
    )
    result = Store(url, initialize=True)
    # CI's PostgreSQL instance is shared; identifiers stay isolated per test.
    result.test_prefix = uuid.uuid4().hex
    yield result
    result.close()


def proposal(store):
    return Position(
        D(0),
        store.test_prefix,
        store.test_prefix,
        theses=frozenset({store.test_prefix}),
        betting_date=store.test_prefix,
    )


def reserve(store, key, **kwargs):
    return store.reserve(
        key,
        proposal(store),
        D(".8"),
        D(2),
        Limits(D(1000), event=D(".015"), sport=D(1), daily=D(1)),
        model_version="test-only-v1",
        **kwargs,
    )


def test_idempotency_conflicts_and_immutable_evidence(store):
    key = uuid.uuid4().hex
    assert store.append("test", key, {"amount": "1"}, key)
    assert not store.append("test", key, {"amount": "1"}, key)
    with pytest.raises(Conflict):
        store.append("test", key, {"amount": "2"}, key)
    for operation in [
        "UPDATE platform_events SET kind=kind WHERE id=:key",
        "DELETE FROM platform_events WHERE id=:key",
    ]:
        with pytest.raises(Exception, match="immutable"):
            with store.engine.begin() as conn:
                conn.execute(text(operation), {"key": key})
    if store.engine.dialect.name == "postgresql":
        with pytest.raises(Exception, match="immutable"):
            with store.engine.begin() as conn:
                conn.execute(text("TRUNCATE platform_events"))


def test_transaction_rollback_leaves_no_audit_fragment(store):
    key = uuid.uuid4().hex
    with pytest.raises(RuntimeError):
        with store.transaction() as conn:
            store._append(conn, "test", key, {"operation": "rollback"}, key)
            raise RuntimeError("abort")
    with store.engine.connect() as conn:
        assert (
            conn.execute(text("SELECT id FROM platform_events WHERE id=:key"), {"key": key}).first()
            is None
        )


def test_concurrent_reservations_cannot_overbook_event_capacity(store):
    keys = [uuid.uuid4().hex for _ in range(6)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        stakes = list(pool.map(lambda key: reserve(store, key), keys))
    assert sum(stakes) == D(15)
    assert sum(x > 0 for x in stakes) == 1


def test_reservation_retries_and_expiry(store):
    key = uuid.uuid4().hex
    now = datetime.now(UTC)
    assert reserve(store, key, now=now) == 15
    assert reserve(store, key, now=now) == 15
    assert reserve(store, key, now=now + timedelta(minutes=6)) == 0
    with pytest.raises(Conflict):
        store.reserve(
            key, proposal(store), D(".7"), D(2), Limits(D(1000)), model_version="test-only-v1"
        )


def test_settlement_corrections_are_new_events(store):
    key = uuid.uuid4().hex
    reserve(store, key)
    placed_key = uuid.uuid4().hex
    store.transition(
        key,
        "placed",
        actor="test",
        evidence={"ticket": "verified-test-fixture"},
        event_key=placed_key,
    )
    store.transition(
        key,
        "placed",
        actor="test",
        evidence={"ticket": "verified-test-fixture"},
        event_key=placed_key,
    )
    store.transition(
        key, "settled", actor="test", evidence={"profit": "-15"}, event_key=uuid.uuid4().hex
    )
    with pytest.raises(ValueError, match="reason"):
        store.transition(
            key, "settled", actor="test", evidence={"profit": "15"}, event_key=uuid.uuid4().hex
        )
    store.transition(
        key,
        "settled",
        actor="test",
        evidence={"profit": "0", "correction_reason": "Official void"},
        event_key=uuid.uuid4().hex,
    )
    with store.engine.connect() as conn:
        rows = conn.execute(
            text("SELECT payload FROM platform_events WHERE entity=:key"), {"key": key}
        ).all()
    assert len(rows) == 4  # Reservation, placement, original settlement, correction.


def test_lease_owner_cannot_release_another_worker(store):
    key = uuid.uuid4().hex
    assert store.acquire_lease(key, "a")
    assert not store.acquire_lease(key, "b")
    store.release_lease(key, "b")
    assert not store.acquire_lease(key, "b")
    store.release_lease(key, "a")
    assert store.acquire_lease(key, "b")


def test_migration_is_repeatable_and_schema_is_ready(store):
    store.migrate()
    assert store.ready()
