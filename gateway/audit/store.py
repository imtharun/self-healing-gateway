# built-in
import json
import os
import uuid
from datetime import datetime
from pathlib import Path

# third-party
import aiosqlite

# local
from gateway.audit.models import GatewayEvent, HealingSession

DB_PATH = Path(
    os.getenv(
        "GATEWAY_AUDIT_DB",
        str(Path(__file__).with_name("audit.db")),
    )
)


async def init_db():
    """Create the sessions table if it doesn't exist"""
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
                actions_taken TEXT  -- JSON serialized list
            )
        """)
        await _ensure_column(db, "healing_sessions", "suspected_cause", "TEXT")
        await _ensure_column(db, "healing_sessions", "action_taken", "TEXT")
        await _ensure_column(db, "healing_sessions", "operator_next_step", "TEXT")
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
        await db.commit()


async def _ensure_column(
    db: aiosqlite.Connection, table_name: str, column_name: str, column_type: str
) -> None:
    async with db.execute(f"PRAGMA table_info({table_name})") as cursor:
        columns = [row[1] for row in await cursor.fetchall()]
    if column_name not in columns:
        await db.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")


async def save_session(session: HealingSession) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO healing_sessions (
                session_id,
                upstream_url,
                triggered_at,
                resolved_at,
                status,
                reason,
                actions_taken,
                suspected_cause,
                action_taken,
                operator_next_step
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
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
            ),
        )
        await db.commit()


async def get_sessions(limit: int = 50) -> list[dict]:
    limit = max(1, min(limit, 200))
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """
            SELECT * FROM healing_sessions ORDER BY triggered_at DESC LIMIT ?
        """,
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
            columns = [col[0] for col in cursor.description]

            results = []
            for row in rows:
                d = dict(zip(columns, row))
                d["actions_taken"] = json.loads(d["actions_taken"] or "[]")
                results.append(d)
            return results


async def save_event(event: GatewayEvent) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO gateway_events VALUES (?, ?, ?, ?, ?, ?)
        """,
            (
                event.event_id,
                event.event_type,
                event.upstream_url,
                event.occurred_at.isoformat(),
                event.message,
                json.dumps(event.metadata),
            ),
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
        occurred_at=datetime.now(),
        message=message,
        metadata=metadata or {},
    )
    await save_event(event)


async def get_events(limit: int = 100) -> list[dict]:
    limit = max(1, min(limit, 300))
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """
            SELECT * FROM gateway_events ORDER BY occurred_at DESC LIMIT ?
        """,
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
            columns = [col[0] for col in cursor.description]

            results = []
            for row in rows:
                d = dict(zip(columns, row))
                d["metadata"] = json.loads(d["metadata"] or "{}")
                results.append(d)
            return results
