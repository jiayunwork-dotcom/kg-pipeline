import logging
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, HTTPException, Query

from src.models.schemas import (
    SnapshotCreateRequest,
    Snapshot,
    SnapshotListItem,
    SnapshotDiffResponse,
)
from src.pipeline.snapshot_manager import snapshot_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/snapshots", tags=["snapshots"])


@router.post("", response_model=Snapshot)
async def create_snapshot(request: SnapshotCreateRequest):
    try:
        snapshot = snapshot_manager.create_snapshot(
            description=request.description,
            task_id=request.task_id,
        )
        return snapshot
    except Exception as e:
        logger.error(f"Failed to create snapshot: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=List[SnapshotListItem])
async def list_snapshots(limit: int = Query(100, ge=1, le=500)):
    try:
        snapshots = snapshot_manager.list_snapshots(limit=limit)
        return snapshots
    except Exception as e:
        logger.error(f"Failed to list snapshots: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{snapshot_id}", response_model=Snapshot)
async def get_snapshot(snapshot_id: str):
    try:
        snapshot = snapshot_manager.get_snapshot(snapshot_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="Snapshot not found")
        return snapshot
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get snapshot {snapshot_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/diff/compare", response_model=SnapshotDiffResponse)
async def compare_snapshots(
    snapshot_a_id: str = Query(..., description="基准快照ID"),
    snapshot_b_id: str = Query(..., description="对比快照ID"),
):
    try:
        diff = snapshot_manager.compare_snapshots(snapshot_a_id, snapshot_b_id)
        if diff is None:
            raise HTTPException(
                status_code=404, detail="One or both snapshots not found"
            )
        return diff
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to compare snapshots: {e}")
        raise HTTPException(status_code=500, detail=str(e))
