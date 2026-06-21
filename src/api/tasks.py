import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse

from src.models.schemas import (
    TaskCreateRequest,
    TaskResponse,
    InputSourceType,
)
from src.pipeline.manager import TaskManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

task_manager = TaskManager.get_instance()


def _decode_file(content: bytes, filename: str) -> str:
    encodings = ["utf-8", "utf-8-sig", "gbk", "gb2312", "gb18030", "latin-1"]
    for enc in encodings:
        try:
            return content.decode(enc)
        except Exception:
            continue
    logger.warning(f"Failed to decode file {filename}, falling back to utf-8 with errors ignored")
    return content.decode("utf-8", errors="ignore")


@router.post("", response_model=TaskResponse, status_code=202)
async def create_task(
    source_type: InputSourceType = Form(...),
    text: Optional[str] = Form(None),
    urls: Optional[str] = Form(None),
    custom_dict: Optional[UploadFile] = File(None),
    files: Optional[List[UploadFile]] = File(None),
):
    try:
        custom_dict_csv: Optional[str] = None
        if custom_dict is not None:
            content = await custom_dict.read()
            custom_dict_csv = content.decode("utf-8")

        urls_list: Optional[List[str]] = None
        if urls:
            urls_list = [u.strip() for u in urls.split(",") if u.strip()]

        files_list: Optional[List[dict]] = None
        if source_type == InputSourceType.FILE and files:
            files_list = []
            for f in files:
                try:
                    raw = await f.read()
                    decoded = _decode_file(raw, f.filename or "unknown")
                    files_list.append({
                        "filename": f.filename or "unknown",
                        "content": decoded,
                    })
                except Exception as e:
                    logger.warning(f"Failed to read uploaded file {getattr(f, 'filename', 'unknown')}: {e}")

        request = TaskCreateRequest(
            source_type=source_type,
            text=text,
            urls=urls_list,
            files=files_list,
            custom_dict_csv=custom_dict_csv,
        )

        if source_type == InputSourceType.TEXT and not request.text:
            raise HTTPException(status_code=400, detail="text is required for TEXT source type")
        if source_type == InputSourceType.URL and not request.urls:
            raise HTTPException(status_code=400, detail="urls is required for URL source type")
        if source_type == InputSourceType.FILE and not request.files:
            raise HTTPException(status_code=400, detail="at least one .txt/.md file is required for FILE source type")

        response = task_manager.submit_task(request)
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create task: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/json", response_model=TaskResponse, status_code=202)
async def create_task_json(request: TaskCreateRequest):
    try:
        if request.source_type == InputSourceType.TEXT and not request.text:
            raise HTTPException(status_code=400, detail="text is required for TEXT source type")
        if request.source_type == InputSourceType.URL and not request.urls:
            raise HTTPException(status_code=400, detail="urls is required for URL source type")
        if request.source_type == InputSourceType.FILE:
            raise HTTPException(status_code=400, detail="Use the form-data endpoint for FILE uploads")

        response = task_manager.submit_task(request)
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create task: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task_status(task_id: str):
    try:
        status = task_manager.get_task_status(task_id)
        if status is None:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
        return status
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get task status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=List[TaskResponse])
async def list_tasks(limit: int = 50):
    try:
        return task_manager.list_task_history(limit)
    except Exception as e:
        logger.error(f"Failed to list tasks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{task_id}/retry", response_model=TaskResponse)
async def retry_task(task_id: str):
    try:
        response = task_manager.retry_task(task_id)
        if response is None:
            raise HTTPException(
                status_code=400,
                detail=f"Task {task_id} not found or not in FAILED state",
            )
        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to retry task: {e}")
        raise HTTPException(status_code=500, detail=str(e))
