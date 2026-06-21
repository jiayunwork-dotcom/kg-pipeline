import logging
from typing import List, Dict, Any

from fastapi import APIRouter, HTTPException

from src.models.schemas import QualityEvaluationRequest
from src.pipeline.quality import QualityEvaluator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/quality", tags=["quality"])

evaluator = QualityEvaluator.get_instance()


@router.get("/sample")
async def generate_sample(count: int = 100):
    try:
        return {"triples": evaluator.generate_sample(count)}
    except Exception as e:
        logger.error(f"Failed to generate sample: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/evaluate")
async def evaluate(labels: Dict[str, bool]):
    try:
        result = evaluator.evaluate_sample(labels)
        return result
    except Exception as e:
        logger.error(f"Failed to evaluate: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history")
async def get_history(limit: int = 5):
    try:
        return {"evaluations": evaluator.get_evaluation_history(limit)}
    except Exception as e:
        logger.error(f"Failed to get history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trend")
async def get_trend(limit: int = 5):
    try:
        return evaluator.get_precision_trend(limit)
    except Exception as e:
        logger.error(f"Failed to get trend: {e}")
        raise HTTPException(status_code=500, detail=str(e))
