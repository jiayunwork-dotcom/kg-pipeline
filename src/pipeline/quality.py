import json
import logging
from typing import List, Dict, Optional, Any
from datetime import datetime
from collections import deque

from src.graph.store import GraphStore
from src.utils.database import db

logger = logging.getLogger(__name__)

MAX_EVALUATION_HISTORY = 50


class QualityEvaluator:
    _instance: Optional["QualityEvaluator"] = None

    def __init__(self):
        self._graph = GraphStore.get_instance()
        self._evaluation_history: deque = deque(maxlen=MAX_EVALUATION_HISTORY)
        self._current_sample: List[Dict[str, Any]] = []
        self._load_from_db()

    def _load_from_db(self):
        try:
            rows = db.list_evaluations(limit=MAX_EVALUATION_HISTORY)
            loaded = 0
            for row in rows:
                try:
                    record = {
                        "precision": row["precision"],
                        "total": row["total"],
                        "correct": row["correct"],
                        "evaluated_at": row["evaluated_at"],
                        "triples": json.loads(row.get("results_json", "[]")),
                    }
                    self._evaluation_history.append(record)
                    loaded += 1
                except Exception as e:
                    logger.warning(f"Failed to restore evaluation: {e}")
            logger.info(f"Restored {loaded} quality evaluations from database")
        except Exception as e:
            logger.warning(f"Failed to load evaluations from database: {e}")

    @classmethod
    def get_instance(cls) -> "QualityEvaluator":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def generate_sample(self, count: int = 100) -> List[Dict[str, Any]]:
        triples = self._graph.get_random_triples(count)
        self._current_sample = triples
        return triples

    def evaluate_sample(
        self,
        labels: Dict[str, bool],
    ) -> Dict[str, Any]:
        if not self._current_sample:
            return {
                "precision": 0.0,
                "total": 0,
                "correct": 0,
                "evaluated_at": datetime.utcnow().isoformat(),
            }

        total = 0
        correct = 0
        evaluated_triples = []

        for triple in self._current_sample:
            tid = triple.get("id", "")
            if tid in labels:
                total += 1
                if labels[tid]:
                    correct += 1
                evaluated_triples.append(
                    {
                        **triple,
                        "label": labels[tid],
                    }
                )

        precision = correct / total if total > 0 else 0.0
        eval_time = datetime.utcnow().isoformat()

        evaluation_record = {
            "precision": precision,
            "total": total,
            "correct": correct,
            "evaluated_at": eval_time,
            "triples": evaluated_triples,
        }

        self._evaluation_history.appendleft(evaluation_record)

        try:
            db.save_evaluation(
                {
                    "precision": precision,
                    "total": total,
                    "correct": correct,
                    "evaluated_at": eval_time,
                    "results_json": json.dumps(evaluated_triples, ensure_ascii=False),
                }
            )
        except Exception as e:
            logger.warning(f"Failed to persist evaluation: {e}")

        return evaluation_record

    def get_evaluation_history(self, limit: int = 5) -> List[Dict[str, Any]]:
        if len(self._evaluation_history) < limit:
            try:
                rows = db.list_evaluations(limit=limit)
                existing_times = {r["evaluated_at"] for r in self._evaluation_history}
                for row in rows:
                    if row["evaluated_at"] not in existing_times:
                        record = {
                            "precision": row["precision"],
                            "total": row["total"],
                            "correct": row["correct"],
                            "evaluated_at": row["evaluated_at"],
                        }
                        self._evaluation_history.append(record)
            except Exception as e:
                logger.warning(f"Failed to load evaluations from DB: {e}")

        history = list(self._evaluation_history)[:limit]
        simplified = []
        for rec in history:
            simplified.append(
                {
                    "precision": rec["precision"],
                    "total": rec["total"],
                    "correct": rec["correct"],
                    "evaluated_at": rec["evaluated_at"],
                }
            )
        return simplified

    def get_precision_trend(self, limit: int = 5) -> Dict[str, List]:
        history = self.get_evaluation_history(limit=limit)
        history.reverse()
        return {
            "dates": [r["evaluated_at"] for r in history],
            "precisions": [r["precision"] for r in history],
            "totals": [r["total"] for r in history],
        }
