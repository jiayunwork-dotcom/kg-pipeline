import os
import json
import sqlite3
import logging
from typing import List, Dict, Any, Optional
from contextlib import contextmanager
from datetime import datetime

from src.config import settings

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(settings.UPLOAD_DIR, "kg_pipeline.db")


def _get_db_dir() -> str:
    db_dir = os.path.dirname(DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
    return db_dir


class Database:
    _instance: Optional["Database"] = None

    def __init__(self):
        _get_db_dir()
        self._init_schema()

    @classmethod
    def get_instance(cls) -> "Database":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self):
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    request_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    total_documents INTEGER DEFAULT 0,
                    processed_documents INTEGER DEFAULT 0,
                    entities_extracted INTEGER DEFAULT 0,
                    relations_extracted INTEGER DEFAULT 0,
                    error_message TEXT,
                    failed_step TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
                CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at DESC);

                CREATE TABLE IF NOT EXISTS quality_evaluations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    precision REAL NOT NULL,
                    total INTEGER NOT NULL,
                    correct INTEGER NOT NULL,
                    evaluated_at TEXT NOT NULL,
                    results_json TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_eval_time ON quality_evaluations(evaluated_at DESC);
                """
            )
        logger.info(f"SQLite database initialized at: {DB_PATH}")

    def save_task(self, task_data: Dict[str, Any]):
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO tasks (
                    task_id, request_json, status, created_at, updated_at,
                    total_documents, processed_documents, entities_extracted,
                    relations_extracted, error_message, failed_step
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_data["task_id"],
                    task_data.get("request_json", "{}"),
                    task_data["status"],
                    task_data["created_at"],
                    task_data["updated_at"],
                    task_data.get("total_documents", 0),
                    task_data.get("processed_documents", 0),
                    task_data.get("entities_extracted", 0),
                    task_data.get("relations_extracted", 0),
                    task_data.get("error_message"),
                    task_data.get("failed_step"),
                ),
            )

    def update_task_status(self, task_id: str, **kwargs):
        fields = []
        values = []
        for key, val in kwargs.items():
            fields.append(f"{key} = ?")
            values.append(val)
        fields.append("updated_at = ?")
        values.append(datetime.utcnow().isoformat())
        values.append(task_id)
        with self._conn() as conn:
            conn.execute(
                f"UPDATE tasks SET {', '.join(fields)} WHERE task_id = ?",
                values,
            )

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            return dict(row) if row else None

    def list_tasks(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def save_evaluation(self, eval_data: Dict[str, Any]):
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO quality_evaluations (
                    precision, total, correct, evaluated_at, results_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    eval_data["precision"],
                    eval_data["total"],
                    eval_data["correct"],
                    eval_data["evaluated_at"],
                    eval_data.get("results_json", "[]"),
                ),
            )

    def list_evaluations(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM quality_evaluations ORDER BY evaluated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]


db = Database.get_instance()
