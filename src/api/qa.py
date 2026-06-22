import logging
from typing import List, Dict, Any

from fastapi import APIRouter, HTTPException

from src.models.schemas import (
    QuestionRequest,
    ParsedQuestion,
    QAResponse,
    QAResult,
    QAIntent,
)
from src.pipeline.qa_service import QAService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/qa", tags=["qa"])

qa_service = QAService.get_instance()


@router.get("/health")
async def qa_health():
    return {"connected": qa_service.graph_store.is_connected()}


@router.get("/intents")
async def get_intents():
    return {
        "intents": [
            {
                "key": QAIntent.ATTRIBUTE.value,
                "name": "属性查询",
                "description": "查询实体的类型、别名、来源等属性信息",
                "examples": [
                    "阿里巴巴是什么类型的实体？",
                    "马云的别名有哪些？",
                    "杭州首次出现在哪个文档中？",
                ],
            },
            {
                "key": QAIntent.RELATION.value,
                "name": "关系查询",
                "description": "查询两个实体之间的直接关系",
                "examples": [
                    "马云和阿里巴巴是什么关系？",
                    "阿里巴巴和腾讯有什么关系？",
                ],
            },
            {
                "key": QAIntent.PATH.value,
                "name": "路径查询",
                "description": "查询两个实体之间的关联路径",
                "examples": [
                    "马云和杭州是怎么关联的？",
                    "从阿里巴巴到百度的路径是什么？",
                ],
            },
            {
                "key": QAIntent.LIST.value,
                "name": "列举查询",
                "description": "查询某个实体关联的其他实体列表",
                "examples": [
                    "阿里巴巴有哪些关联的实体？",
                    "马云参与了哪些事情？",
                    "和杭州相关的实体有哪些？",
                ],
            },
        ]
    }


@router.post("/parse", response_model=ParsedQuestion)
async def parse_question(request: QuestionRequest):
    try:
        parsed = qa_service.parse_question(request.question)
        return parsed
    except Exception as e:
        logger.error(f"Failed to parse question: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ask", response_model=QAResponse)
async def ask_question(request: QuestionRequest):
    try:
        if not request.question or not request.question.strip():
            return QAResponse(
                success=False,
                question=request.question,
                error_message="请输入有效的问题内容。",
            )

        parsed = qa_service.parse_question(request.question)
        result = qa_service.answer_question(request.question, parsed_question=parsed)

        return QAResponse(
            success=True,
            question=request.question,
            parsed_question=parsed,
            result=result,
        )
    except Exception as e:
        logger.error(f"Failed to answer question: {e}")
        return QAResponse(
            success=False,
            question=request.question,
            error_message=f"处理问题时发生错误：{str(e)}",
        )
