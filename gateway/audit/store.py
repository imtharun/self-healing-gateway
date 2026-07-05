# built-in
import json
import os
from pathlib import Path

# third-party
import aiosqlite

# local
from gateway.audit.models import HealingSession

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
        await db.commit()


async def save_session(session: HealingSession) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO healing_sessions VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (
                session.session_id,
                session.upstream_url,
                session.triggered_at.isoformat(),
                session.resolved_at.isoformat() if session.resolved_at else None,
                session.status,
                session.reason,
                json.dumps(session.actions_taken),
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
