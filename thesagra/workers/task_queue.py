import json
import sqlite3
import threading
import uuid
from contextlib import closing
from datetime import datetime, timezone
from typing import Optional


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class TaskQueueError(Exception):
    pass


class TaskQueue:
    def __init__(self, database_path: str):
        self.path = str(database_path) + ".tasks.sqlite3"
        self.lock = threading.RLock()
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self):
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS tasks (
                        task_id TEXT PRIMARY KEY,
                        task_type TEXT NOT NULL,
                        payload TEXT NOT NULL,
                        state TEXT NOT NULL,
                        attempts INTEGER NOT NULL,
                        max_attempts INTEGER NOT NULL,
                        idempotency_key TEXT,
                        created_at TEXT NOT NULL,
                        started_at TEXT,
                        completed_at TEXT,
                        error TEXT
                    )
                    """
                )

    def enqueue(
        self,
        task_type: str,
        payload=None,
        max_attempts=3,
        idempotency_key=None,
    ):
        payload = payload or {}
        if not isinstance(payload, dict):
            raise TaskQueueError("Task payload must be a JSON object")
        if not isinstance(task_type, str) or not task_type:
            raise TaskQueueError("Task type must be non-empty")
        if not isinstance(max_attempts, int) or max_attempts < 1:
            raise TaskQueueError("max_attempts must be positive")

        with self.lock:
            with closing(self._connect()) as connection:
                with connection:
                    if idempotency_key:
                        existing = connection.execute(
                            "SELECT task_id FROM tasks WHERE idempotency_key=?",
                            (idempotency_key,),
                        ).fetchone()
                        if existing:
                            return existing["task_id"]
                    task_id = str(uuid.uuid4())
                    connection.execute(
                        """
                        INSERT INTO tasks (
                            task_id, task_type, payload, state, attempts,
                            max_attempts, idempotency_key, created_at
                        ) VALUES (?, ?, ?, 'queued', 0, ?, ?, ?)
                        """,
                        (
                            task_id,
                            task_type,
                            json.dumps(payload, sort_keys=True),
                            max_attempts,
                            idempotency_key,
                            utc_now(),
                        ),
                    )
        return task_id

    def claim(self):
        with self.lock:
            with closing(self._connect()) as connection:
                with connection:
                    row = connection.execute(
                    """
                    SELECT * FROM tasks
                    WHERE state='queued'
                       OR (state='failed' AND attempts < max_attempts)
                    ORDER BY created_at
                    LIMIT 1
                    """
                    ).fetchone()
                    if row is None:
                        return None
                    connection.execute(
                    """
                    UPDATE tasks
                    SET state='running', attempts=attempts+1,
                        started_at=?, completed_at=NULL, error=NULL
                    WHERE task_id=? AND state=?
                    """,
                    (
                        utc_now(),
                        row["task_id"],
                        row["state"],
                    ),
                    )
                    return dict(row)

    def complete(self, task_id, result=None):
        with self.lock:
            with closing(self._connect()) as connection:
                with connection:
                    connection.execute(
                        """
                        UPDATE tasks
                        SET state='completed', completed_at=?, error=?
                        WHERE task_id=?
                        """,
                        (utc_now(), json.dumps(result) if result is not None else None, task_id),
                    )

    def fail(self, task_id, error):
        with self.lock:
            with closing(self._connect()) as connection:
                with connection:
                    row = connection.execute(
                        "SELECT attempts, max_attempts FROM tasks WHERE task_id=?",
                        (task_id,),
                    ).fetchone()
                    if row is None:
                        return
                    state = "failed"
                    if row["attempts"] >= row["max_attempts"]:
                        state = "dead"
                    connection.execute(
                        """
                        UPDATE tasks
                        SET state=?, completed_at=?, error=?
                        WHERE task_id=?
                        """,
                        (state, utc_now(), str(error), task_id),
                    )

    def get(self, task_id):
        with closing(self._connect()) as connection:
            with connection:
                row = connection.execute(
                    "SELECT * FROM tasks WHERE task_id=?",
                    (task_id,),
                ).fetchone()
                return dict(row) if row else None

    def list(self, limit=100):
        with closing(self._connect()) as connection:
            with connection:
                rows = connection.execute(
                    "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
                return [dict(row) for row in rows]

    def recover_interrupted(self):
        with self.lock:
            with closing(self._connect()) as connection:
                with connection:
                    result = connection.execute(
                        """
                        UPDATE tasks
                        SET state='queued', started_at=NULL
                        WHERE state='running'
                        """
                    )
                    return result.rowcount
