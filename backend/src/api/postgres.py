import json
import logging

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from api.runs import PlanRun, PlanRunStore
from api.traces import RunTrace, RunTraceSummary, TraceStore

logger = logging.getLogger(__name__)

# The durable half of observability, and the run lineage an adjustment needs.
#
# `tech-stack.md` chose local Postgres over Langfuse, LangSmith and Jaeger for
# one reason that still holds: no account, no key, no free tier to lapse
# between submission and review. It also resolves that document's open
# sub-decision — *one wide append-only row per run* rather than a run/event
# pair of tables. Spans are only ever written together with their run and only
# ever read as a whole waterfall, so splitting them would buy a join and cost
# the atomic write.

SCHEMA = """
CREATE TABLE IF NOT EXISTS trace_runs (
    run_id      TEXT PRIMARY KEY,
    source      TEXT             NOT NULL,
    prompt      TEXT             NOT NULL,
    started_at  TIMESTAMPTZ      NOT NULL,
    duration_ms DOUBLE PRECISION NOT NULL,
    status      TEXT             NOT NULL,
    totals      JSONB            NOT NULL,
    spans       JSONB            NOT NULL
);

CREATE INDEX IF NOT EXISTS trace_runs_started_at_idx ON trace_runs (started_at DESC);

CREATE TABLE IF NOT EXISTS plan_runs (
    run_id               TEXT PRIMARY KEY,
    parent_run_id        TEXT REFERENCES plan_runs (run_id),
    member_id            TEXT        NOT NULL,
    prompt               TEXT        NOT NULL,
    duration_min         INTEGER     NOT NULL,
    declared_constraints JSONB       NOT NULL DEFAULT '{}',
    message_history      JSONB       NOT NULL DEFAULT '[]',
    plan                 JSONB,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Agentic migration: this table's columns changed twice (instructions/
-- emphasis dropped, then declared_constraints/message_history/plan added).
-- CREATE IF NOT EXISTS will not alter an existing table — reset a
-- pre-migration local Postgres volume rather than migrating a dev-only store.

CREATE INDEX IF NOT EXISTS plan_runs_parent_idx ON plan_runs (parent_run_id);
"""

MAX_LINEAGE_DEPTH = 64
"""Ceiling on a refinement chain walk.

The foreign key makes a cycle unreachable — a parent must already exist — so
this guards against a corrupted table rather than normal operation. A recursive
CTE with no bound is an unkillable query, which is a worse failure than a
truncated trail."""


class PostgresTraceStore:
    """Append-only run storage, one wide row per run."""

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def record(self, trace: RunTrace) -> None:
        """Store one finished run.

        Idempotent on `run_id`: a retry writes the same row rather than a
        duplicate, and a trace is never edited after the fact, so the conflict
        arm does nothing.
        """
        body = trace.model_dump(mode="json")
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO trace_runs
                    (run_id, source, prompt, started_at, duration_ms, status, totals, spans)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (run_id) DO NOTHING
                """,
                (
                    body["run_id"],
                    body["source"],
                    body["prompt"],
                    body["started_at"],
                    body["duration_ms"],
                    body["status"],
                    Jsonb(body["totals"]),
                    Jsonb(body["spans"]),
                ),
            )

    def list(self) -> list[RunTraceSummary]:
        """Every recorded run, newest first.

        Spans are excluded from the projection rather than fetched and dropped:
        they are the bulk of a row, and the list view never renders them.
        """
        with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT run_id, source, prompt, started_at, duration_ms, status, totals
                FROM trace_runs
                ORDER BY started_at DESC
                LIMIT 200
                """
            )
            return [
                RunTraceSummary(
                    **row | {"started_at": row["started_at"].isoformat()}
                )
                for row in cur.fetchall()
            ]

    def get(self, run_id: str) -> RunTrace | None:
        with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM trace_runs WHERE run_id = %s", (run_id,))
            row = cur.fetchone()
            if row is None:
                return None
            return RunTrace(**row | {"started_at": row["started_at"].isoformat()})


class PostgresPlanRunStore:
    """What each generation was asked for, so an adjustment can build on it."""

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def record(self, run: PlanRun) -> None:
        body = run.model_dump(mode="json")
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO plan_runs
                    (run_id, parent_run_id, member_id, prompt, duration_min,
                     declared_constraints, message_history, plan)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (run_id) DO NOTHING
                """,
                (
                    body["run_id"],
                    body["parent_run_id"],
                    body["member_id"],
                    body["prompt"],
                    body["duration_min"],
                    Jsonb(body["declared_constraints"]),
                    Jsonb(json.loads(run.message_history) if run.message_history else []),
                    Jsonb(body["plan"]) if body["plan"] is not None else None,
                ),
            )

    @staticmethod
    def _row(row: dict) -> PlanRun:
        """Rebuild a run from its stored columns."""
        return PlanRun(
            run_id=row["run_id"],
            parent_run_id=row["parent_run_id"],
            member_id=row["member_id"],
            prompt=row["prompt"],
            duration_min=row["duration_min"],
            declared_constraints=row["declared_constraints"],
            message_history=json.dumps(row["message_history"]),
            plan=row["plan"],
        )

    def get(self, run_id: str) -> PlanRun | None:
        with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM plan_runs WHERE run_id = %s", (run_id,))
            row = cur.fetchone()
            return self._row(row) if row else None

    def lineage(self, run_id: str) -> list[PlanRun]:
        """The whole refinement chain, oldest first.

        A recursive CTE rather than a walk in Python: the chain is what the
        console prints above a plan, and one round trip for it beats one per
        ancestor.
        """
        with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                WITH RECURSIVE chain AS (
                    SELECT r.*, 1 AS depth
                    FROM plan_runs r
                    WHERE r.run_id = %s
                  UNION ALL
                    SELECT p.*, c.depth + 1
                    FROM plan_runs p
                    JOIN chain c ON p.run_id = c.parent_run_id
                    WHERE c.depth < %s
                )
                SELECT * FROM chain ORDER BY depth DESC
                """,
                (run_id, MAX_LINEAGE_DEPTH),
            )
            return [self._row(row) for row in cur.fetchall()]


def open_stores(url: str) -> tuple[TraceStore, PlanRunStore, ConnectionPool]:
    """Connect, create the schema if it is absent, and build both stores.

    The schema is applied on every boot rather than through a migration tool.
    Two `CREATE TABLE IF NOT EXISTS` statements do not justify Alembic, and the
    trace tables are derived data — a reviewer who drops them loses history, not
    the system.

    Args:
        url: A libpq connection string.

    Returns:
        The trace store, the plan-run store, and the pool they share, which the
        caller closes on shutdown.

    Raises:
        psycopg.OperationalError: If the database cannot be reached. Raised
            rather than swallowed: compose waits for Postgres to be healthy, so
            a failure here is a real misconfiguration and not a cold start.
    """
    pool = ConnectionPool(url, min_size=1, max_size=8, open=True, timeout=10)
    pool.wait(timeout=30)
    with pool.connection() as conn:
        conn.execute(SCHEMA)
    logger.info("trace and plan-run storage ready")
    return PostgresTraceStore(pool), PostgresPlanRunStore(pool), pool
