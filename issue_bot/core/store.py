"""
SQLite-backed persistent storage for pending issues and issue history.

Tables:
  - pending_issues: replaces in-memory dict, with auto-expiry
  - issue_history: audit log of created issues
"""

import json
import os
import sqlite3
import time
import logging

log = logging.getLogger("issue-bot")

# Default expiry: 30 minutes
DEFAULT_EXPIRY_SECONDS = 1800


class Store:
    def __init__(self, db_path: str = "data/issuebot.db"):
        os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    def _create_tables(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS pending_issues (
                id TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                user_id TEXT NOT NULL DEFAULT '',
                channel_id TEXT NOT NULL DEFAULT '',
                project_alias TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS issue_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                gitlab_iid INTEGER,
                project_alias TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                created_by TEXT NOT NULL DEFAULT '',
                gitlab_url TEXT NOT NULL DEFAULT '',
                data TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL
            );
        """)
        self._conn.commit()

    def save_pending(
        self,
        issue_id: str,
        data: dict,
        user_id: str = "",
        channel_id: str = "",
        project_alias: str = "",
        expiry_seconds: int = DEFAULT_EXPIRY_SECONDS,
    ):
        now = time.time()
        self._conn.execute(
            """INSERT OR REPLACE INTO pending_issues
               (id, data, user_id, channel_id, project_alias, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (issue_id, json.dumps(data), user_id, channel_id, project_alias, now, now + expiry_seconds),
        )
        self._conn.commit()

    def get_pending(self, issue_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM pending_issues WHERE id = ? AND expires_at > ?",
            (issue_id, time.time()),
        ).fetchone()
        if not row:
            return None
        return json.loads(row["data"])

    def update_pending(self, issue_id: str, data: dict):
        self._conn.execute(
            "UPDATE pending_issues SET data = ? WHERE id = ?",
            (json.dumps(data), issue_id),
        )
        self._conn.commit()

    def delete_pending(self, issue_id: str):
        self._conn.execute("DELETE FROM pending_issues WHERE id = ?", (issue_id,))
        self._conn.commit()

    def cleanup_expired(self) -> int:
        """Remove expired pending issues. Returns count of removed entries."""
        cur = self._conn.execute(
            "DELETE FROM pending_issues WHERE expires_at <= ?", (time.time(),)
        )
        self._conn.commit()
        count = cur.rowcount
        if count:
            log.info(f"Cleaned up {count} expired pending issues")
        return count

    def record_created_issue(
        self,
        gitlab_iid: int,
        project_alias: str,
        title: str,
        created_by: str,
        gitlab_url: str,
        data: dict | None = None,
    ):
        self._conn.execute(
            """INSERT INTO issue_history
               (gitlab_iid, project_alias, title, created_by, gitlab_url, data, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (gitlab_iid, project_alias, title, created_by, gitlab_url,
             json.dumps(data or {}), time.time()),
        )
        self._conn.commit()

    def get_recent_issues(self, limit: int = 20, project_alias: str = "") -> list[dict]:
        if project_alias:
            rows = self._conn.execute(
                "SELECT * FROM issue_history WHERE project_alias = ? ORDER BY created_at DESC LIMIT ?",
                (project_alias, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM issue_history ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def close(self):
        self._conn.close()
