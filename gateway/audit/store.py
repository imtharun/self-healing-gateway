# built-in
import json
import os
import re
import uuid
from pathlib import Path

# third-party
import aiosqlite
import asyncpg

# local
from gateway.audit.models import GatewayEvent, HealingSession, RemediationApproval
from gateway.time_utils import now_ist
from gateway.upstreams.models import ManagedUpstream

DATABASE_URL = os.getenv("DATABASE_URL")
DB_SCHEMA = os.getenv("GATEWAY_DB_SCHEMA", "self_healing_gateway")
DB_PATH = Path(
    os.getenv(
        "GATEWAY_AUDIT_DB",
        str(Path(__file__).with_name("audit.db")),
    )
)

_pg_pool: asyncpg.Pool | None = None


def _postgres_enabled() -> bool:
    return bool(DATABASE_URL)


def _postgres_table(table_name: str) -> str:
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", DB_SCHEMA):
        raise ValueError("GATEWAY_DB_SCHEMA must be a valid PostgreSQL identifier")
    return f'"{DB_SCHEMA}".{table_name}'


def _require_pg_pool() -> asyncpg.Pool:
    if _pg_pool is None:
        raise RuntimeError("PostgreSQL audit store has not been initialized")
    return _pg_pool


async def init_db() -> None:
    """Initialize PostgreSQL in production or SQLite for local development."""
    if _postgres_enabled():
        await _init_postgres()
        return

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS healing_sessions (
                session_id TEXT PRIMARY KEY,
                upstream_url TEXT,
                triggered_at TEXT,
                resolved_at TEXT,
                status TEXT,
                reason TEXT,
                actions_taken TEXT
            )
        """)
        await _ensure_sqlite_column(db, "healing_sessions", "suspected_cause", "TEXT")
        await _ensure_sqlite_column(db, "healing_sessions", "action_taken", "TEXT")
        await _ensure_sqlite_column(
            db, "healing_sessions", "operator_next_step", "TEXT"
        )
        await db.execute("""
            CREATE TABLE IF NOT EXISTS gateway_events (
                event_id TEXT PRIMARY KEY,
                event_type TEXT,
                upstream_url TEXT,
                occurred_at TEXT,
                message TEXT,
                metadata TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS managed_upstreams (
                upstream_id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                path TEXT NOT NULL UNIQUE,
                upstream_url TEXT NOT NULL UNIQUE,
                health_check TEXT NOT NULL,
                failure_threshold INTEGER NOT NULL,
                recovery_timeout INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS remediation_approvals (
                approval_id TEXT PRIMARY KEY,
                action TEXT NOT NULL,
                upstream_url TEXT NOT NULL,
                arguments TEXT NOT NULL,
                reason TEXT NOT NULL,
                status TEXT NOT NULL,
                requested_at TEXT NOT NULL,
                decided_at TEXT
            )
        """)
        await db.commit()


async def _init_postgres() -> None:
    global _pg_pool

    sessions_table = _postgres_table("healing_sessions")
    events_table = _postgres_table("gateway_events")
    upstreams_table = _postgres_table("managed_upstreams")
    approvals_table = _postgres_table("remediation_approvals")
    _pg_pool = await asyncpg.create_pool(
        dsn=DATABASE_URL,
        min_size=1,
        max_size=3,
        command_timeout=15,
    )
    async with _pg_pool.acquire() as connection:
        await connection.execute(f'CREATE SCHEMA IF NOT EXISTS "{DB_SCHEMA}"')
        await connection.execute(f"""
            CREATE TABLE IF NOT EXISTS {sessions_table} (
                session_id TEXT PRIMARY KEY,
                upstream_url TEXT,
                triggered_at TEXT,
                resolved_at TEXT,
                status TEXT,
                reason TEXT,
                actions_taken TEXT,
                suspected_cause TEXT,
                action_taken TEXT,
                operator_next_step TEXT
            )
        """)
        await connection.execute(f"""
            CREATE TABLE IF NOT EXISTS {events_table} (
                event_id TEXT PRIMARY KEY,
                event_type TEXT,
                upstream_url TEXT,
                occurred_at TEXT,
                message TEXT,
                metadata TEXT
            )
        """)
        await connection.execute(f"""
            CREATE TABLE IF NOT EXISTS {upstreams_table} (
                upstream_id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                path TEXT NOT NULL UNIQUE,
                upstream_url TEXT NOT NULL UNIQUE,
                health_check TEXT NOT NULL,
                failure_threshold INTEGER NOT NULL,
                recovery_timeout INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        await connection.execute(f"""
            CREATE TABLE IF NOT EXISTS {approvals_table} (
                approval_id TEXT PRIMARY KEY,
                action TEXT NOT NULL,
                upstream_url TEXT NOT NULL,
                arguments TEXT NOT NULL,
                reason TEXT NOT NULL,
                status TEXT NOT NULL,
                requested_at TEXT NOT NULL,
                decided_at TEXT
            )
        """)
        for column_name in (
            "suspected_cause",
            "action_taken",
            "operator_next_step",
        ):
            await connection.execute(
                f"ALTER TABLE {sessions_table} "
                f"ADD COLUMN IF NOT EXISTS {column_name} TEXT"
            )


async def close_db() -> None:
    global _pg_pool
    if _pg_pool is not None:
        await _pg_pool.close()
        _pg_pool = None


async def _ensure_sqlite_column(
    db: aiosqlite.Connection, table_name: str, column_name: str, column_type: str
) -> None:
    async with db.execute(f"PRAGMA table_info({table_name})") as cursor:
        columns = [row[1] for row in await cursor.fetchall()]
    if column_name not in columns:
        await db.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")


async def save_session(session: HealingSession) -> None:
    values = (
        session.session_id,
        session.upstream_url,
        session.triggered_at.isoformat(),
        session.resolved_at.isoformat() if session.resolved_at else None,
        session.status,
        session.reason,
        json.dumps(session.actions_taken),
        session.suspected_cause,
        session.action_taken,
        session.operator_next_step,
    )

    if _postgres_enabled():
        table = _postgres_table("healing_sessions")
        await _require_pg_pool().execute(
            f"""
                INSERT INTO {table} (
                    session_id, upstream_url, triggered_at, resolved_at, status,
                    reason, actions_taken, suspected_cause, action_taken,
                    operator_next_step
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            """,
            *values,
        )
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
                INSERT INTO healing_sessions (
                    session_id, upstream_url, triggered_at, resolved_at, status,
                    reason, actions_taken, suspected_cause, action_taken,
                    operator_next_step
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )
        await db.commit()


async def get_sessions(limit: int = 50) -> list[dict]:
    limit = max(1, min(limit, 200))

    if _postgres_enabled():
        table = _postgres_table("healing_sessions")
        rows = await _require_pg_pool().fetch(
            f"SELECT * FROM {table} ORDER BY triggered_at DESC LIMIT $1",
            limit,
        )
        results = [dict(row) for row in rows]
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT * FROM healing_sessions ORDER BY triggered_at DESC LIMIT ?",
                (limit,),
            ) as cursor:
                rows = await cursor.fetchall()
                columns = [column[0] for column in cursor.description]
                results = [dict(zip(columns, row)) for row in rows]

    for result in results:
        result["actions_taken"] = json.loads(result["actions_taken"] or "[]")
    return results


async def save_event(event: GatewayEvent) -> None:
    values = (
        event.event_id,
        event.event_type,
        event.upstream_url,
        event.occurred_at.isoformat(),
        event.message,
        json.dumps(event.metadata),
    )

    if _postgres_enabled():
        table = _postgres_table("gateway_events")
        await _require_pg_pool().execute(
            f"""
                INSERT INTO {table} (
                    event_id, event_type, upstream_url, occurred_at, message, metadata
                )
                VALUES ($1, $2, $3, $4, $5, $6)
            """,
            *values,
        )
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
                INSERT INTO gateway_events (
                    event_id, event_type, upstream_url, occurred_at, message, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?)
            """,
            values,
        )
        await db.commit()


async def record_event(
    event_type: str,
    message: str,
    upstream_url: str | None = None,
    metadata: dict | None = None,
) -> None:
    event = GatewayEvent(
        event_id=str(uuid.uuid4()),
        event_type=event_type,
        upstream_url=upstream_url,
        occurred_at=now_ist(),
        message=message,
        metadata=metadata or {},
    )
    await save_event(event)


async def get_events(limit: int = 100, upstream_url: str | None = None) -> list[dict]:
    limit = max(1, min(limit, 300))

    if _postgres_enabled():
        table = _postgres_table("gateway_events")
        if upstream_url:
            rows = await _require_pg_pool().fetch(
                f"""
                    SELECT * FROM {table}
                    WHERE upstream_url = $1
                    ORDER BY occurred_at DESC LIMIT $2
                """,
                upstream_url,
                limit,
            )
        else:
            rows = await _require_pg_pool().fetch(
                f"SELECT * FROM {table} ORDER BY occurred_at DESC LIMIT $1",
                limit,
            )
        results = [dict(row) for row in rows]
    else:
        params: tuple = (limit,)
        where_clause = ""
        if upstream_url:
            where_clause = "WHERE upstream_url = ?"
            params = (upstream_url, limit)

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                f"""
                    SELECT * FROM gateway_events
                    {where_clause}
                    ORDER BY occurred_at DESC LIMIT ?
                """,
                params,
            ) as cursor:
                rows = await cursor.fetchall()
                columns = [column[0] for column in cursor.description]
                results = [dict(zip(columns, row)) for row in rows]

    for result in results:
        result["metadata"] = json.loads(result["metadata"] or "{}")
    return results


async def save_upstream(upstream: ManagedUpstream) -> None:
    values = (
        upstream.upstream_id,
        upstream.name,
        upstream.path,
        upstream.upstream_url,
        upstream.health_check,
        upstream.failure_threshold,
        upstream.recovery_timeout,
        upstream.created_at.isoformat(),
    )
    if _postgres_enabled():
        table = _postgres_table("managed_upstreams")
        await _require_pg_pool().execute(
            f"""
                INSERT INTO {table} (
                    upstream_id, name, path, upstream_url, health_check,
                    failure_threshold, recovery_timeout, created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            *values,
        )
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
                INSERT INTO managed_upstreams (
                    upstream_id, name, path, upstream_url, health_check,
                    failure_threshold, recovery_timeout, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )
        await db.commit()


async def get_upstreams() -> list[dict]:
    if _postgres_enabled():
        table = _postgres_table("managed_upstreams")
        rows = await _require_pg_pool().fetch(
            f"SELECT * FROM {table} ORDER BY created_at ASC"
        )
        return [{**dict(row), "managed": True} for row in rows]

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT * FROM managed_upstreams ORDER BY created_at ASC"
        ) as cursor:
            rows = await cursor.fetchall()
            columns = [column[0] for column in cursor.description]
            return [{**dict(zip(columns, row)), "managed": True} for row in rows]


async def delete_upstream(upstream_id: str) -> None:
    if _postgres_enabled():
        table = _postgres_table("managed_upstreams")
        result = await _require_pg_pool().execute(
            f"DELETE FROM {table} WHERE upstream_id = $1", upstream_id
        )
        if result == "DELETE 0":
            raise KeyError(upstream_id)
        return

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM managed_upstreams WHERE upstream_id = ?", (upstream_id,)
        )
        await db.commit()
        if cursor.rowcount == 0:
            raise KeyError(upstream_id)


async def update_upstream(upstream: ManagedUpstream) -> None:
    values = (
        upstream.name,
        upstream.path,
        upstream.upstream_url,
        upstream.health_check,
        upstream.failure_threshold,
        upstream.recovery_timeout,
        upstream.upstream_id,
    )
    if _postgres_enabled():
        table = _postgres_table("managed_upstreams")
        result = await _require_pg_pool().execute(
            f"""
                UPDATE {table}
                SET name = $1, path = $2, upstream_url = $3,
                    health_check = $4, failure_threshold = $5,
                    recovery_timeout = $6
                WHERE upstream_id = $7
            """,
            *values,
        )
        if result == "UPDATE 0":
            raise KeyError(upstream.upstream_id)
        return

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
                UPDATE managed_upstreams
                SET name = ?, path = ?, upstream_url = ?, health_check = ?,
                    failure_threshold = ?, recovery_timeout = ?
                WHERE upstream_id = ?
            """,
            values,
        )
        await db.commit()
        if cursor.rowcount == 0:
            raise KeyError(upstream.upstream_id)


async def save_approval(approval: RemediationApproval) -> None:
    values = (
        approval.approval_id,
        approval.action,
        approval.upstream_url,
        json.dumps(approval.arguments),
        approval.reason,
        approval.status,
        approval.requested_at.isoformat(),
        approval.decided_at.isoformat() if approval.decided_at else None,
    )
    if _postgres_enabled():
        table = _postgres_table("remediation_approvals")
        await _require_pg_pool().execute(
            f"""
                INSERT INTO {table} (
                    approval_id, action, upstream_url, arguments, reason,
                    status, requested_at, decided_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            *values,
        )
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
                INSERT INTO remediation_approvals (
                    approval_id, action, upstream_url, arguments, reason,
                    status, requested_at, decided_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )
        await db.commit()


async def get_approvals(limit: int = 100) -> list[dict]:
    limit = max(1, min(limit, 200))
    if _postgres_enabled():
        table = _postgres_table("remediation_approvals")
        rows = await _require_pg_pool().fetch(
            f"SELECT * FROM {table} ORDER BY requested_at DESC LIMIT $1", limit
        )
        results = [dict(row) for row in rows]
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT * FROM remediation_approvals "
                "ORDER BY requested_at DESC LIMIT ?",
                (limit,),
            ) as cursor:
                rows = await cursor.fetchall()
                columns = [column[0] for column in cursor.description]
                results = [dict(zip(columns, row)) for row in rows]
    for result in results:
        result["arguments"] = json.loads(result["arguments"] or "{}")
    return results


async def get_approval(approval_id: str) -> dict | None:
    if _postgres_enabled():
        table = _postgres_table("remediation_approvals")
        row = await _require_pg_pool().fetchrow(
            f"SELECT * FROM {table} WHERE approval_id = $1", approval_id
        )
        result = dict(row) if row else None
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT * FROM remediation_approvals WHERE approval_id = ?",
                (approval_id,),
            ) as cursor:
                row = await cursor.fetchone()
                columns = [column[0] for column in cursor.description]
                result = dict(zip(columns, row)) if row else None
    if result is not None:
        result["arguments"] = json.loads(result["arguments"] or "{}")
    return result


async def decide_approval(approval_id: str, decision: str) -> None:
    decided_at = now_ist().isoformat()
    if _postgres_enabled():
        table = _postgres_table("remediation_approvals")
        result = await _require_pg_pool().execute(
            f"""
                UPDATE {table} SET status = $1, decided_at = $2
                WHERE approval_id = $3 AND status = 'pending'
            """,
            decision,
            decided_at,
            approval_id,
        )
        if result == "UPDATE 0":
            raise KeyError(approval_id)
        return

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
                UPDATE remediation_approvals SET status = ?, decided_at = ?
                WHERE approval_id = ? AND status = 'pending'
            """,
            (decision, decided_at, approval_id),
        )
        await db.commit()
        if cursor.rowcount == 0:
            raise KeyError(approval_id)


async def set_approval_status(approval_id: str, approval_status: str) -> None:
    decided_at = now_ist().isoformat()
    if _postgres_enabled():
        table = _postgres_table("remediation_approvals")
        result = await _require_pg_pool().execute(
            f"UPDATE {table} SET status = $1, decided_at = $2 WHERE approval_id = $3",
            approval_status,
            decided_at,
            approval_id,
        )
        if result == "UPDATE 0":
            raise KeyError(approval_id)
        return

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE remediation_approvals SET status = ?, decided_at = ? "
            "WHERE approval_id = ?",
            (approval_status, decided_at, approval_id),
        )
        await db.commit()
        if cursor.rowcount == 0:
            raise KeyError(approval_id)
