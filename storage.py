"""Local SQLite CRM. Stores business information, never API keys."""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent / "data" / "leads.sqlite3"


def connect(path: str | Path | None = None):
    target = Path(path or DB_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target))
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS prospects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        website TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        country TEXT NOT NULL DEFAULT '',
        score INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT '未联系',
        email TEXT NOT NULL DEFAULT '',
        contact_name TEXT NOT NULL DEFAULT '',
        research_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS drafts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        prospect_id INTEGER NOT NULL,
        stage INTEGER NOT NULL,
        subject TEXT NOT NULL,
        body TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(prospect_id) REFERENCES prospects(id)
    )""")
    conn.commit()
    return conn


def upsert_prospect(conn: sqlite3.Connection, data: dict[str, Any]) -> int:
    website = str(data.get("input_website") or data.get("website") or "").strip()
    name = str(data.get("company_name") or data.get("name") or website).strip()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("""INSERT INTO prospects (website,name,country,score,research_json,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?)
                    ON CONFLICT(website) DO UPDATE SET
                    name=excluded.name,country=excluded.country,score=excluded.score,
                    research_json=excluded.research_json,updated_at=excluded.updated_at""",
                 (website, name, str(data.get("country") or ""), int(data.get("score") or 0),
                  json.dumps(data, ensure_ascii=False), now, now))
    conn.commit()
    return conn.execute("SELECT id FROM prospects WHERE website=?", (website,)).fetchone()["id"]


def list_prospects(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(x) for x in conn.execute("SELECT * FROM prospects ORDER BY updated_at DESC").fetchall()]


def get_prospect(conn: sqlite3.Connection, prospect_id: int) -> dict[str, Any] | None:
    r = conn.execute("SELECT * FROM prospects WHERE id=?", (prospect_id,)).fetchone()
    return dict(r) if r else None


def update_details(conn: sqlite3.Connection, pid: int, status: str, email: str, contact_name: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("UPDATE prospects SET status=?,email=?,contact_name=?,updated_at=? WHERE id=?", (status, email, contact_name, now, pid))
    conn.commit()


def save_draft(conn: sqlite3.Connection, pid: int, stage: int, draft: dict[str, str]):
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("INSERT INTO drafts (prospect_id,stage,subject,body,created_at) VALUES (?,?,?,?,?)", (pid, stage, draft["subject"], draft["body"], now))
    conn.commit()


def list_drafts(conn: sqlite3.Connection, pid: int) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute("SELECT * FROM drafts WHERE prospect_id=? ORDER BY created_at DESC", (pid,))]
