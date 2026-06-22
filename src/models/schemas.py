from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum


ENTITY_TYPES = ["PER", "ORG", "LOC", "TIME", "EVENT", "WORK", "TECH"]
RELATION_TYPES = ["隶属于", "位于", "创建了", "参与了", "发生在", "合作关系", "竞争关系", "子类关系", "无关系"]


class TaskStatus(str, Enum):
    QUEUED = "排队中"
    PREPROCESSING = "预处理中"
    NER = "实体识别中"
    RE = "关系抽取中"
    FUSION = "融合入图中"
    COMPLETED = "完成"
    FAILED = "失败"


class InputSourceType(str, Enum):
    TEXT = "text"
    FILE = "file"
    URL = "url"


class Entity(BaseModel):
    text: str
    type: str
    start: int
    end: int
    confidence: float = 1.0
    source: str = "model"


class Relation(BaseModel):
    head_text: str
    head_type: str
    tail_text: str
    tail_type: str
    relation: str
    confidence: float
    sentence: str
    need_manual_confirm: bool = False


class Document(BaseModel):
    doc_id: str
    source_type: InputSourceType
    source: str
    raw_text: str
    sentences: List[str] = []


class Triple(BaseModel):
    head: str
    head_type: str
    relation: str
    tail: str
    tail_type: str
    confidence: float
    source_sentence: str
    source_doc_id: str
    extraction_time: datetime = Field(default_factory=datetime.utcnow)
    conflict: bool = False


class EntityNode(BaseModel):
    canonical_name: str
    aliases: List[str] = []
    type: str
    first_source: str
    frequency: int = 1


class TaskCreateRequest(BaseModel):
    source_type: InputSourceType
    text: Optional[str] = None
    urls: Optional[List[str]] = None
    files: Optional[List[Dict[str, str]]] = None
    custom_dict_csv: Optional[str] = None


class TaskResponse(BaseModel):
    task_id: str
    status: TaskStatus
    created_at: datetime
    total_documents: int = 0
    processed_documents: int = 0
    entities_extracted: int = 0
    relations_extracted: int = 0
    error_message: Optional[str] = None
    failed_step: Optional[str] = None


class EntitySearchRequest(BaseModel):
    name: str
    hops: int = 2


class PathSearchRequest(BaseModel):
    entity1: str
    entity2: str
    max_hops: int = 5


class GraphFilterRequest(BaseModel):
    relation_types: Optional[List[str]] = None
    min_confidence: float = 0.0
    entity_types: Optional[List[str]] = None


class QualityEvaluationRequest(BaseModel):
    triple_ids: List[str]
    labels: List[bool]


class GraphStats(BaseModel):
    total_entities: int
    total_relations: int
    entity_type_distribution: Dict[str, int]
    relation_type_distribution: Dict[str, int]


class QAIntent(str, Enum):
    ATTRIBUTE = "attribute"
    RELATION = "relation"
    PATH = "path"
    LIST = "list"


class QuestionRequest(BaseModel):
    question: str


class ParsedQuestion(BaseModel):
    original_question: str
    entities: List[str]
    intent: QAIntent
    query_attributes: List[str] = []


class QAEntity(BaseModel):
    name: str
    type: str
    aliases: List[str] = []
    first_source: str = ""
    frequency: int = 0


class QARelation(BaseModel):
    head: str
    tail: str
    relation: str
    confidence: float = 1.0
    head_type: str = ""
    tail_type: str = ""


class QAPath(BaseModel):
    node_names: List[str]
    node_types: List[str]
    relation_types: List[str]
    confidences: List[float]
    path_length: int


class QAResult(BaseModel):
    answer_text: str
    entities: List[QAEntity] = []
    relations: List[QARelation] = []
    paths: List[QAPath] = []
    raw_data: Dict[str, Any] = {}


class QAResponse(BaseModel):
    success: bool
    question: str
    parsed_question: Optional[ParsedQuestion] = None
    result: Optional[QAResult] = None
    error_message: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
