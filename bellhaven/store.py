"""SQLite decision store. Proposals are upserted only if their key has never
been seen — that is the idempotency mechanism: a second pipeline run
recognizes every already-decided proposal and proposes nothing."""
import json
import os
import sqlite3
from datetime import datetime, timezone

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    key         TEXT PRIMARY KEY,
    change_type TEXT NOT NULL,
    title       TEXT NOT NULL,
    proposal    TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending|approved|rejected
    decided_at  TEXT,
    apply_log   TEXT
);
"""


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def upsert_proposals(proposals: list[dict]) -> tuple[int, int]:
    """Insert proposals that have never been seen. Returns (new, already_known)."""
    new = known = 0
    with _conn() as conn:
        for p in proposals:
            cur = conn.execute(
                "INSERT OR IGNORE INTO decisions (key, change_type, title, proposal) VALUES (?,?,?,?)",
                (p["key"], p["change_type"], p["title"], json.dumps(p)))
            if cur.rowcount:
                new += 1
            else:
                known += 1
    return new, known


def get(key: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM decisions WHERE key=?", (key,)).fetchone()
        return dict(row) if row else None


def list_decisions(status: str | None = None) -> list[dict]:
    with _conn() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM decisions WHERE status=? ORDER BY rowid", (status,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM decisions ORDER BY rowid").fetchall()
        return [dict(r) for r in rows]


def counts() -> dict:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) n FROM decisions GROUP BY status").fetchall()
        return {r["status"]: r["n"] for r in rows}


def decide(key: str, status: str, apply_log: list | None = None) -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE decisions SET status=?, decided_at=?, apply_log=? WHERE key=?",
            (status, datetime.now(timezone.utc).isoformat(timespec="seconds"),
             json.dumps(apply_log) if apply_log else None, key))
