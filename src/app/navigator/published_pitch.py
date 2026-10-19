"""Immutable approved content per share token, shared by page, PDF and email."""
import json
import sqlite3
from .config import DATA_DIR

DB = DATA_DIR / 'published-pitches.db'


def connection():
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB, timeout=15)
    conn.execute('CREATE TABLE IF NOT EXISTS pitches (token TEXT PRIMARY KEY, case_id TEXT NOT NULL, data TEXT NOT NULL)')
    return conn


def save(token, case_id, data, prepared_at):
    with connection() as conn:
        # preparing the pitch again keeps its link (until disabled), so the same token gets the new content
        conn.execute('INSERT OR REPLACE INTO pitches VALUES (?, ?, ?)', (token, case_id, json.dumps({**data, 'prepared_at': prepared_at})))


def get(token):
    with connection() as conn:
        row = conn.execute('SELECT data FROM pitches WHERE token=?', (token,)).fetchone()
    return json.loads(row[0]) if row else None


def withdraw(case_id):
    with connection() as conn:
        conn.execute('DELETE FROM pitches WHERE case_id=?', (case_id,))
