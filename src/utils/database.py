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

                CREATE TABLE IF NOT EXISTS snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    task_id TEXT,
                    description TEXT,
                    total_entities INTEGER NOT NULL DEFAULT 0,
                    total_relations INTEGER NOT NULL DEFAULT 0,
                    entity_type_distribution TEXT NOT NULL DEFAULT '{}',
                    relation_type_distribution TEXT NOT NULL DEFAULT '{}',
                    entity_list_json TEXT NOT NULL DEFAULT '[]',
                    relation_list_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_snapshots_created ON snapshots(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_snapshots_task ON snapshots(task_id);
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

    def save_snapshot(self, snapshot_data: Dict[str, Any]):
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO snapshots (
                    snapshot_id, task_id, description, total_entities, total_relations,
                    entity_type_distribution, relation_type_distribution,
                    entity_list_json, relation_list_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_data["snapshot_id"],
                    snapshot_data.get("task_id"),
                    snapshot_data.get("description"),
                    snapshot_data.get("total_entities", 0),
                    snapshot_data.get("total_relations", 0),
                    json.dumps(snapshot_data.get("entity_type_distribution", {}), ensure_ascii=False),
                    json.dumps(snapshot_data.get("relation_type_distribution", {}), ensure_ascii=False),
                    json.dumps(snapshot_data.get("entity_list", []), ensure_ascii=False),
                    json.dumps(snapshot_data.get("relation_list", []), ensure_ascii=False),
                    snapshot_data["created_at"],
                ),
            )

    def get_snapshot(self, snapshot_id: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
            if row is None:
                return None
            result = dict(row)
            result["entity_type_distribution"] = json.loads(result.get("entity_type_distribution", "{}"))
            result["relation_type_distribution"] = json.loads(result.get("relation_type_distribution", "{}"))
            result["entity_list"] = json.loads(result.get("entity_list_json", "[]"))
            result["relation_list"] = json.loads(result.get("relation_list_json", "[]"))
            return result

    def list_snapshots(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM snapshots ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            results = []
            for row in rows:
                result = dict(row)
                result["entity_type_distribution"] = json.loads(result.get("entity_type_distribution", "{}"))
                result["relation_type_distribution"] = json.loads(result.get("relation_type_distribution", "{}"))
                result["entity_list"] = json.loads(result.get("entity_list_json", "[]"))
                result["relation_list"] = json.loads(result.get("relation_list_json", "[]"))
                results.append(result)
            return results

    def delete_snapshot(self, snapshot_id: str) -> bool:
        with self._conn() as conn:
            cursor = conn.execute(
                "DELETE FROM snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            )
            return cursor.rowcount > 0


db = Database.get_instance()
