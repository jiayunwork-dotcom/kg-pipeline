import logging
from typing import List, Dict, Optional, Any
from datetime import datetime
from collections import deque

from src.graph.store import GraphStore

logger = logging.getLogger(__name__)

MAX_EVALUATION_HISTORY = 20


class QualityEvaluator:
    _instance: Optional["QualityEvaluator"] = None

    def __init__(self):
        self._graph = GraphStore.get_instance()
        self._evaluation_history: deque = deque(maxlen=MAX_EVALUATION_HISTORY)
        self._current_sample: List[Dict[str, Any]] = []

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

        evaluation_record = {
            "precision": precision,
            "total": total,
            "correct": correct,
            "evaluated_at": datetime.utcnow().isoformat(),
            "triples": evaluated_triples,
        }

        self._evaluation_history.appendleft(evaluation_record)

        return evaluation_record

    def get_evaluation_history(self, limit: int = 5) -> List[Dict[str, Any]]:
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
        history = list(self._evaluation_history)[:limit]
        history.reverse()
        return {
            "dates": [r["evaluated_at"] for r in history],
            "precisions": [r["precision"] for r in history],
            "totals": [r["total"] for r in history],
        }
