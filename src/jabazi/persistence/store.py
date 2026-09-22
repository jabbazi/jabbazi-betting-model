"""Transactional SQLAlchemy store for PostgreSQL and local SQLite.

Evidence is append-only at the database level; positions are mutable projections
whose transitions append audit events in the same transaction. PostgreSQL uses a
transaction-scoped advisory lock to serialize capacity reservations across workers.
"""

from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import hashlib
import json

from sqlalchemy import (
    create_engine,
    MetaData,
    Table,
    Column,
    String,
    Integer,
    DateTime,
    JSON,
    select,
    insert,
    update,
    text,
)
from sqlalchemy.pool import StaticPool
from jabazi.domain.portfolio import Position, allocate

metadata = MetaData()
versions = Table("platform_schema_versions", metadata, Column("version", Integer, primary_key=True))
events = Table(
    "platform_events",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("kind", String(40), nullable=False, index=True),
    Column("entity", String(160), nullable=False, index=True),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("payload", JSON, nullable=False),
    Column("sha256", String(64), nullable=False),
)
positions = Table(
    "platform_positions",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("state", String(20), nullable=False, index=True),
    Column("expires_at", DateTime(timezone=True), nullable=True),
    Column("payload", JSON, nullable=False),
)
leases = Table(
    "platform_leases",
    metadata,
    Column("name", String(80), primary_key=True),
    Column("owner", String(80), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
)


def canonical(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False)


def digest(payload):
    return hashlib.sha256(canonical(payload).encode()).hexdigest()


def clean(payload):
    return json.loads(canonical(payload))


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class Conflict(ValueError):
    pass


class Store:
    def __init__(self, url, *, initialize=False):
        if url.startswith("postgres://"):
            url = "postgresql+psycopg://" + url[len("postgres://") :]
        if url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://") :]
        options = {"pool_pre_ping": True}
        if url == "sqlite:///:memory:":
            options.update(poolclass=StaticPool, connect_args={"check_same_thread": False})
        elif url.startswith("sqlite:"):
            options.update(connect_args={"timeout": 10})
        self.engine = create_engine(url, **options)
        if initialize:
            self.migrate()

    def migrate(self):
        with self.engine.begin() as conn:
            if conn.dialect.name == "postgresql":
                conn.execute(text("SELECT pg_advisory_xact_lock(742613)"))
            metadata.create_all(conn)
            version = conn.execute(select(versions.c.version)).scalars().all()
            if any(v > 1 for v in version):
                raise RuntimeError("Database schema is newer than this application")
            if 1 not in version:
                conn.execute(insert(versions).values(version=1))
            if conn.dialect.name == "sqlite":
                for operation in ("UPDATE", "DELETE"):
                    conn.exec_driver_sql(
                        f"CREATE TRIGGER IF NOT EXISTS platform_events_no_{operation.lower()} BEFORE {operation} ON platform_events BEGIN SELECT RAISE(ABORT, 'Audit evidence is immutable'); END"
                    )
            elif conn.dialect.name == "postgresql":
                conn.exec_driver_sql("""CREATE OR REPLACE FUNCTION platform_reject_event_edit()
                RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
                RAISE EXCEPTION 'Audit evidence is immutable'; END; $$""")
                if not conn.execute(
                    text(
                        "SELECT 1 FROM pg_trigger WHERE tgname='platform_events_immutable' AND tgrelid='platform_events'::regclass"
                    )
                ).first():
                    conn.exec_driver_sql(
                        "CREATE TRIGGER platform_events_immutable BEFORE UPDATE OR DELETE ON platform_events FOR EACH ROW EXECUTE FUNCTION platform_reject_event_edit()"
                    )
                if not conn.execute(
                    text(
                        "SELECT 1 FROM pg_trigger WHERE tgname='platform_events_no_truncate' AND tgrelid='platform_events'::regclass"
                    )
                ).first():
                    conn.exec_driver_sql(
                        "CREATE TRIGGER platform_events_no_truncate BEFORE TRUNCATE ON platform_events FOR EACH STATEMENT EXECUTE FUNCTION platform_reject_event_edit()"
                    )

    @contextmanager
    def transaction(self):
        with self.engine.connect() as conn:
            try:
                if conn.dialect.name == "sqlite":
                    conn.exec_driver_sql("BEGIN IMMEDIATE")
                else:
                    conn.begin()
                    conn.execute(text("SELECT pg_advisory_xact_lock(742613)"))
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def _append(self, conn, kind, entity, payload, key):
        if (
            not key
            or len(key) > 64
            or not kind
            or len(kind) > 40
            or not entity
            or len(entity) > 160
        ):
            raise ValueError("Invalid audit identity")
        payload = clean(payload)
        fingerprint = digest(payload)
        previous = conn.execute(select(events).where(events.c.id == key)).mappings().first()
        if previous:
            if (
                previous["sha256"] != fingerprint
                or previous["kind"] != kind
                or previous["entity"] != entity
            ):
                raise Conflict("Idempotency key reused with different evidence")
            return False
        conn.execute(
            insert(events).values(
                id=key,
                kind=kind,
                entity=entity,
                occurred_at=datetime.now(UTC),
                payload=payload,
                sha256=fingerprint,
            )
        )
        return True

    def append(self, kind, entity, payload, key=None):
        key = key or digest([kind, entity, payload])
        with self.transaction() as conn:
            return self._append(conn, kind, entity, payload, key)

    def archive_batch(self, batch):
        payload = json.loads(batch.raw_payload)
        key = digest([batch.provider, payload])
        with self.transaction() as conn:
            self._append(conn, "provider_payload", batch.provider, payload, key)
            for q in batch.quotes:
                evidence = asdict(q)
                self._append(conn, "odds_snapshot", q.event_id, evidence, digest(evidence))
        return key

    def record_action_card(self, action, observed_at=None):
        payload = asdict(action)
        return self.append("candidate", action.price.event_id, payload)

    def list_records(self, kind=None, limit=100, *, entity=None):
        if not 1 <= limit <= 1000:
            raise ValueError("Limit must be 1–1000")
        query = select(events).order_by(events.c.occurred_at.desc(), events.c.id).limit(limit)
        if kind:
            query = query.where(events.c.kind == kind)
        if entity:
            query = query.where(events.c.entity == entity)
        with self.engine.connect() as conn:
            return [dict(r) for r in conn.execute(query).mappings()]

    def list_positions(self, limit=100):
        if not 1 <= limit <= 1000:
            raise ValueError("Limit must be 1–1000")
        with self.engine.connect() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    select(positions).order_by(positions.c.id).limit(limit)
                ).mappings()
            ]

    def import_placement(self, key, payload):
        """Record an already placed, owner-reported wager; never place a wager."""
        payload = clean(payload)
        with self.transaction() as conn:
            row = conn.execute(select(positions).where(positions.c.id == key)).mappings().first()
            if row:
                self._append(conn, "reported_placement", key, payload, digest(["placement", key]))
                return False
            self._append(conn, "reported_placement", key, payload, digest(["placement", key]))
            conn.execute(
                insert(positions).values(id=key, state="placed", expires_at=None, payload=payload)
            )
            return True

    def get_position(self, key):
        with self.engine.connect() as conn:
            row = conn.execute(select(positions).where(positions.c.id == key)).mappings().first()
            return dict(row) if row else None

    def claim_credits(self, provider, amount, *, monthly_limit, key, now=None):
        """Conservative monthly request budget, shared by every process and restart.

        Credits are charged before the network call and never refunded on ambiguous
        failure. This local ceiling is independent of the provider billing cycle.
        """
        if not isinstance(amount, int) or not 1 <= amount <= 1000:
            raise ValueError("Credit amount must be 1–1000")
        if not isinstance(monthly_limit, int) or monthly_limit < 1:
            raise ValueError("Positive monthly credit ceiling required")
        now = now or datetime.now(UTC)
        if now.tzinfo is None:
            raise ValueError("Aware budget time required")
        month = now.astimezone(UTC).strftime("%Y-%m")
        entity = provider + ":" + month
        payload = {"provider": provider, "month": month, "credits": amount}
        with self.transaction() as conn:
            if conn.execute(select(events.c.id).where(events.c.id == key)).first():
                self._append(conn, "quota_reservation", entity, payload, key)
                return False
            rows = conn.execute(
                select(events.c.payload).where(
                    events.c.kind == "quota_reservation", events.c.entity == entity
                )
            ).scalars()
            spent = sum(int(r["credits"]) for r in rows)
            if spent + amount > monthly_limit:
                return False
            self._append(conn, "quota_reservation", entity, payload, key)
            return True

    def _active(self, conn, now):
        rows = conn.execute(select(positions)).mappings()
        return [
            r
            for r in rows
            if r["state"] == "placed"
            or (r["state"] == "reserved" and r["expires_at"] and utc(r["expires_at"]) > now)
        ]

    @staticmethod
    def _position(row):
        p = row["payload"]
        return Position(
            Decimal(p["stake"]),
            p["sport"],
            p["event"],
            frozenset(p["players"]),
            frozenset(p["theses"]),
            p["parlay"],
            p["origin"],
            p["betting_date"],
        )

    def open_exposure(self):
        with self.engine.connect() as conn:
            return sum(
                (self._position(r).amount for r in self._active(conn, datetime.now(UTC))),
                Decimal(0),
            )

    def reserve(
        self,
        key,
        proposal,
        p,
        price,
        limits,
        *,
        model_version,
        tier="standard",
        drawdown=0,
        now=None,
        ttl=300,
    ):
        if not model_version or not proposal.theses:
            raise ValueError("Model version and thesis tags required")
        if not 1 <= ttl <= 600:
            raise ValueError("Reservation TTL must be 1–600 seconds")
        now = now or datetime.now(UTC)
        if now.tzinfo is None:
            raise ValueError("Timezone-aware reservation time required")
        request_hash = digest(
            [
                clean(
                    {
                        **asdict(proposal),
                        "players": sorted(proposal.players),
                        "theses": sorted(proposal.theses),
                    }
                ),
                str(p),
                str(price),
                model_version,
                tier,
            ]
        )
        with self.transaction() as conn:
            existing = (
                conn.execute(select(positions).where(positions.c.id == key)).mappings().first()
            )
            if existing:
                if existing["payload"].get("request_hash") != request_hash:
                    raise Conflict("Reservation key reused for a different request")
                if existing["state"] == "reserved" and utc(existing["expires_at"]) > now:
                    return Decimal(existing["payload"]["stake"])
                return Decimal(0)
            exposure = [self._position(r) for r in self._active(conn, now)]
            result = allocate(p, price, proposal, exposure, limits, tier=tier, drawdown=drawdown)
            if result.dollars <= 0:
                return Decimal(0)
            payload = clean(
                {
                    **asdict(proposal),
                    "stake": str(result.dollars),
                    "stake_units": str(result.units),
                    "unit_size": str(limits.unit_size),
                    "model_probability": str(p),
                    "decimal_odds": str(price),
                    "request_hash": request_hash,
                    "model_version": model_version,
                    "tier": tier,
                    "players": sorted(proposal.players),
                    "theses": sorted(proposal.theses),
                }
            )
            conn.execute(
                insert(positions).values(
                    id=key,
                    state="reserved",
                    expires_at=now + timedelta(seconds=ttl),
                    payload=payload,
                )
            )
            self._append(conn, "reservation", key, payload, digest(["reservation", key]))
            return result.dollars

    def transition(self, key, state, *, actor, evidence, event_key):
        if not actor or not evidence:
            raise ValueError("Actor and transition evidence required")
        allowed = {
            "reserved": {"placed", "cancelled"},
            "placed": {"settled"},
            "settled": {"settled"},
        }
        if state not in {"placed", "cancelled", "settled"}:
            raise ValueError("Invalid state")
        with self.transaction() as conn:
            row = conn.execute(select(positions).where(positions.c.id == key)).mappings().first()
            if not row:
                raise ValueError("Unknown reservation")
            payload = clean({"state": state, "actor": actor, "evidence": evidence})
            if conn.execute(select(events.c.id).where(events.c.id == event_key)).first():
                self._append(conn, "position_transition", key, payload, event_key)
                return
            if state not in allowed.get(row["state"], set()):
                raise ValueError("Invalid lifecycle transition")
            if state == "placed" and utc(row["expires_at"]) <= datetime.now(UTC):
                raise ValueError("Expired reservation requires fresh pricing and risk review")
            if state == "settled":
                from jabazi.domain.pricing import number

                number(evidence.get("profit"))
                if row["state"] == "settled" and not evidence.get("correction_reason"):
                    raise ValueError("Settlement correction requires an explicit reason")
            self._append(conn, "position_transition", key, payload, event_key)
            conn.execute(update(positions).where(positions.c.id == key).values(state=state))

    def acquire_lease(self, name, owner, ttl=300):
        if not 1 <= ttl <= 600:
            raise ValueError("Invalid lease duration")
        now = datetime.now(UTC)
        with self.transaction() as conn:
            current = conn.execute(select(leases).where(leases.c.name == name)).mappings().first()
            if current and utc(current["expires_at"]) > now and current["owner"] != owner:
                return False
            values = {"owner": owner, "expires_at": now + timedelta(seconds=ttl)}
            if current:
                conn.execute(update(leases).where(leases.c.name == name).values(**values))
            else:
                conn.execute(insert(leases).values(name=name, **values))
            return True

    def release_lease(self, name, owner):
        with self.transaction() as conn:
            conn.execute(
                update(leases)
                .where(leases.c.name == name, leases.c.owner == owner)
                .values(expires_at=datetime.now(UTC))
            )

    def ready(self):
        with self.engine.connect() as conn:
            return conn.execute(select(versions.c.version)).scalars().all() == [1]

    def close(self):
        self.engine.dispose()
