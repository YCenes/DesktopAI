"""SQLite transaction ve append-only task event/journal sınırı."""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import threading
import time

from nova.domain.tasks import TaskError, TaskStatus, TRANSITIONS


class TaskStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(path, timeout=5, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=FULL")
        try:
            self.migrate()
        except BaseException:
            self.conn.close()
            raise

    @contextmanager
    def transaction(self):
        with self._lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield self.conn
                self.conn.execute("COMMIT")
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise

    def migrate(self):
        with self.transaction() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > 1:
                raise TaskError("SCHEMA_UNSUPPORTED", "Görev veritabanı sürümü desteklenmiyor.", 503)
            if version == 0:
                statements = [
                    "CREATE TABLE tasks (task_id TEXT PRIMARY KEY, action_id TEXT UNIQUE NOT NULL, spec TEXT NOT NULL, session_id TEXT NOT NULL, status TEXT NOT NULL, result TEXT, error_code TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0)",
                    "CREATE TABLE task_events (task_id TEXT NOT NULL REFERENCES tasks(task_id), sequence INTEGER NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL, created_at REAL NOT NULL, PRIMARY KEY(task_id,sequence))",
                    "CREATE TABLE approvals (approval_id TEXT PRIMARY KEY, task_id TEXT UNIQUE NOT NULL REFERENCES tasks(task_id), action_id TEXT NOT NULL, specification TEXT NOT NULL, session_id TEXT NOT NULL, policy_version TEXT NOT NULL, expires_at REAL NOT NULL, state TEXT NOT NULL)",
                    "CREATE TABLE execution_journal (action_id TEXT PRIMARY KEY, task_id TEXT UNIQUE NOT NULL REFERENCES tasks(task_id), state TEXT NOT NULL, result TEXT)",
                    "CREATE TRIGGER immutable_task_action BEFORE UPDATE OF task_id, action_id, spec, session_id ON tasks BEGIN SELECT RAISE(ABORT, 'immutable_action'); END",
                    "PRAGMA user_version=1",
                ]
                for sql in statements:
                    db.execute(sql)

    def event(self, db, task_id: str, kind: str):
        status = self.row(db, task_id)["status"]
        seq = db.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM task_events WHERE task_id=?", (task_id,)).fetchone()[0]
        db.execute("INSERT INTO task_events VALUES (?,?,?,?,?)", (task_id, seq, kind, status, time.time()))

    def row(self, db, task_id):
        row = db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if row is None:
            raise TaskError("TASK_NOT_FOUND", "Görev bulunamadı.", 404)
        return row

    def transition(self, db, task_id, status, kind, error=None, result=None):
        old = self.row(db, task_id)["status"]
        if status not in TRANSITIONS.get(TaskStatus(old), set()):
            raise TaskError("TASK_STATE_CONFLICT", "Görev bu duruma geçirilemez.")
        db.execute("UPDATE tasks SET status=?, error_code=?, result=? WHERE task_id=?", (status, error, json.dumps(result, ensure_ascii=False) if result else None, task_id))
        self.event(db, task_id, kind)

    def recover(self, session_id):
        with self.transaction() as db:
            rows = db.execute("SELECT * FROM tasks WHERE status IN ('queued','running','awaiting_approval')").fetchall()
            for row in rows:
                if row["session_id"] == session_id:
                    continue
                journal = db.execute("SELECT state FROM execution_journal WHERE action_id=?", (row["action_id"],)).fetchone()
                if journal and journal["state"] == "started":
                    status, code = "unknown", "OUTCOME_UNKNOWN"
                    db.execute("UPDATE execution_journal SET state='unknown' WHERE action_id=?", (row["action_id"],))
                elif row["status"] == "awaiting_approval":
                    status, code = "cancelled", "SESSION_EXPIRED"
                else:
                    status, code = "failed", "RECOVERY_REQUIRED"
                self.transition(db, row["task_id"], status, "restart_recovery", code)
            db.execute("UPDATE approvals SET state='invalidated' WHERE session_id<>? AND state IN ('pending','granted')", (session_id,))

    def close(self):
        with self._lock:
            self.conn.close()
