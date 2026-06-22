import logging
import csv
import io
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, HTTPException, Query, Response

from fastapi.responses import StreamingResponse

from src.models.schemas import (
    SnapshotCreateRequest,
    Snapshot,
    SnapshotListItem,
    SnapshotDiffResponse,
    SnapshotTagsUpdateRequest,
    SnapshotProtectedUpdateRequest,
    BatchDiffResponse,
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
            tags=request.tags,
        )
        return snapshot
    except Exception as e:
        logger.error(f"Failed to create snapshot: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=List[SnapshotListItem])
async def list_snapshots(
    limit: int = Query(100, ge=1, le=500),
    tag: Optional[str] = Query(None, description="按标签关键词筛选"),
):
    try:
        snapshots = snapshot_manager.list_snapshots(limit=limit, tag_filter=tag)
        return snapshots
    except Exception as e:
        logger.error(f"Failed to list snapshots: {e}")
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


@router.get("/diff/export/entities")
async def export_diff_entities_csv(
    snapshot_a_id: str = Query(..., description="基准快照ID"),
    snapshot_b_id: str = Query(..., description="对比快照ID"),
):
    try:
        diff = snapshot_manager.compare_snapshots(snapshot_a_id, snapshot_b_id)
        if diff is None:
            raise HTTPException(
                status_code=404, detail="One or both snapshots not found"
            )

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            ["变更类型", "实体名称", "实体类型", "来源快照ID", "时间"]
        )

        for entity in diff.added_entities:
            writer.writerow(
                [
                    "新增",
                    entity.name,
                    entity.type,
                    entity.source_snapshot_id,
                    entity.source_snapshot_time.isoformat()
                    if hasattr(entity.source_snapshot_time, "isoformat")
                    else str(entity.source_snapshot_time),
                ]
            )

        for entity in diff.removed_entities:
            writer.writerow(
                [
                    "删除",
                    entity.name,
                    entity.type,
                    entity.source_snapshot_id,
                    entity.source_snapshot_time.isoformat()
                    if hasattr(entity.source_snapshot_time, "isoformat")
                    else str(entity.source_snapshot_time),
                ]
            )

        output.seek(0)
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=diff_entities_{snapshot_a_id}_{snapshot_b_id}.csv"
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to export entity diff CSV: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/diff/export/relations")
async def export_diff_relations_csv(
    snapshot_a_id: str = Query(..., description="基准快照ID"),
    snapshot_b_id: str = Query(..., description="对比快照ID"),
):
    try:
        diff = snapshot_manager.compare_snapshots(snapshot_a_id, snapshot_b_id)
        if diff is None:
            raise HTTPException(
                status_code=404, detail="One or both snapshots not found"
            )

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            ["变更类型", "头实体", "关系", "尾实体", "置信度", "来源快照ID", "时间"]
        )

        for rel in diff.added_relations:
            writer.writerow(
                [
                    "新增",
                    rel.head,
                    rel.relation,
                    rel.tail,
                    rel.confidence,
                    rel.source_snapshot_id,
                    rel.source_snapshot_time.isoformat()
                    if hasattr(rel.source_snapshot_time, "isoformat")
                    else str(rel.source_snapshot_time),
                ]
            )

        for rel in diff.removed_relations:
            writer.writerow(
                [
                    "删除",
                    rel.head,
                    rel.relation,
                    rel.tail,
                    rel.confidence,
                    rel.source_snapshot_id,
                    rel.source_snapshot_time.isoformat()
                    if hasattr(rel.source_snapshot_time, "isoformat")
                    else str(rel.source_snapshot_time),
                ]
            )

        output.seek(0)
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=diff_relations_{snapshot_a_id}_{snapshot_b_id}.csv"
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to export relation diff CSV: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/diff/batch", response_model=BatchDiffResponse)
async def batch_compare_snapshots(snapshot_ids: List[str] = Query(..., description="快照ID列表，第一个为基准快照")):
    try:
        if len(snapshot_ids) < 3 or len(snapshot_ids) > 5:
            raise HTTPException(
                status_code=400, detail="需要选择3到5个快照进行批量对比"
            )

        result = snapshot_manager.batch_compare_snapshots(snapshot_ids)
        if result is None:
            raise HTTPException(
                status_code=404, detail="基准快照不存在或无法对比"
            )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to batch compare snapshots: {e}")
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


@router.put("/{snapshot_id}/tags")
async def update_snapshot_tags(snapshot_id: str, request: SnapshotTagsUpdateRequest):
    try:
        success = snapshot_manager.update_tags(snapshot_id, request.tags)
        if not success:
            raise HTTPException(status_code=404, detail="Snapshot not found")
        return {"success": True, "tags": request.tags}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update tags for snapshot {snapshot_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{snapshot_id}/protected")
async def update_snapshot_protected(
    snapshot_id: str, request: SnapshotProtectedUpdateRequest
):
    try:
        success = snapshot_manager.update_protected(snapshot_id, request.is_protected)
        if not success:
            raise HTTPException(status_code=404, detail="Snapshot not found")
        return {"success": True, "is_protected": request.is_protected}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Failed to update protected status for snapshot {snapshot_id}: {e}"
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{snapshot_id}")
async def delete_snapshot(snapshot_id: str):
    try:
        success, message = snapshot_manager.delete_snapshot(snapshot_id)
        if not success:
            if "不存在" in message:
                raise HTTPException(status_code=404, detail=message)
            elif "保护" in message:
                raise HTTPException(status_code=403, detail=message)
            else:
                raise HTTPException(status_code=400, detail=message)
        return {"success": True, "message": message}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete snapshot {snapshot_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
