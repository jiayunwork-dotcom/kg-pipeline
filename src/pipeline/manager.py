import os
import uuid
import logging
import threading
from typing import List, Optional, Dict, Any
from datetime import datetime
from collections import deque

from src.models.schemas import (
    TaskStatus,
    TaskResponse,
    InputSourceType,
    Document,
    Entity,
    Relation,
    Triple,
    TaskCreateRequest,
)
from src.pipeline.text_processor import preprocess_text
from src.pipeline.web_crawler import fetch_and_extract
from src.pipeline.ner import NERPredictor, CustomDictionary
from src.pipeline.re import REPredictor
from src.pipeline.entity_fusion import EntityFusion
from src.graph.store import GraphStore
from src.config import settings

logger = logging.getLogger(__name__)

MAX_HISTORY = 200


class PipelineTask:
    def __init__(self, task_id: str, request: TaskCreateRequest):
        self.task_id = task_id
        self.request = request
        self.status: TaskStatus = TaskStatus.QUEUED
        self.created_at: datetime = datetime.utcnow()
        self.updated_at: datetime = datetime.utcnow()
        self.total_documents: int = 0
        self.processed_documents: int = 0
        self.entities_extracted: int = 0
        self.relations_extracted: int = 0
        self.error_message: Optional[str] = None
        self.failed_step: Optional[str] = None
        self.custom_dict: Optional[CustomDictionary] = None
        self.documents: List[Document] = []


class TaskManager:
    _instance: Optional["TaskManager"] = None

    def __init__(self):
        self._tasks: Dict[str, PipelineTask] = {}
        self._history: deque = deque(maxlen=MAX_HISTORY)
        self._lock = threading.Lock()
        self._execution_thread: Optional[threading.Thread] = None
        self._ner = NERPredictor.get_instance()
        self._re = REPredictor.get_instance()
        self._fusion = EntityFusion.get_instance()
        self._graph = GraphStore.get_instance()

    @classmethod
    def get_instance(cls) -> "TaskManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _update_status(self, task: PipelineTask, status: TaskStatus):
        task.status = status
        task.updated_at = datetime.utcnow()
        logger.info(f"Task {task.task_id} status: {status.value}")

    def _set_failure(self, task: PipelineTask, step: str, error: str):
        task.status = TaskStatus.FAILED
        task.failed_step = step
        task.error_message = error
        task.updated_at = datetime.utcnow()
        logger.error(f"Task {task.task_id} failed at {step}: {error}")

    def create_task(self, request: TaskCreateRequest) -> PipelineTask:
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        task = PipelineTask(task_id, request)

        if request.custom_dict_csv:
            task.custom_dict = CustomDictionary.from_csv(request.custom_dict_csv)

        with self._lock:
            self._tasks[task_id] = task
            self._history.appendleft(task_id)

        return task

    def get_task(self, task_id: str) -> Optional[PipelineTask]:
        with self._lock:
            return self._tasks.get(task_id)

    def list_tasks(self, limit: int = 50) -> List[PipelineTask]:
        with self._lock:
            task_ids = list(self._history)[:limit]
            return [self._tasks[tid] for tid in task_ids if tid in self._tasks]

    def _collect_documents(self, task: PipelineTask) -> List[Document]:
        docs: List[Document] = []
        req = task.request

        if req.source_type == InputSourceType.TEXT and req.text:
            doc_id = f"{task.task_id}_txt_0"
            docs.append(
                Document(
                    doc_id=doc_id,
                    source_type=InputSourceType.TEXT,
                    source="direct_text",
                    raw_text=req.text,
                )
            )

        elif req.source_type == InputSourceType.URL and req.urls:
            for i, url in enumerate(req.urls):
                content = fetch_and_extract(url)
                if content:
                    doc_id = f"{task.task_id}_url_{i}"
                    docs.append(
                        Document(
                            doc_id=doc_id,
                            source_type=InputSourceType.URL,
                            source=url,
                            raw_text=content,
                        )
                    )

        return docs

    def _preprocess_step(self, task: PipelineTask):
        self._update_status(task, TaskStatus.PREPROCESSING)
        docs = self._collect_documents(task)

        for doc in docs:
            cleaned, sentences = preprocess_text(doc.raw_text)
            doc.raw_text = cleaned
            doc.sentences = sentences

        task.documents = docs
        task.total_documents = len(docs)

    def _ner_step(self, task: PipelineTask):
        self._update_status(task, TaskStatus.NER)
        total_entities = 0

        for doc in task.documents:
            all_entities: List[Entity] = []
            sent_entity_pairs = []

            for sent in doc.sentences:
                entities = self._ner.predict(sent, task.custom_dict)
                all_entities.extend(entities)
                sent_entity_pairs.append((sent, entities))

            doc._sent_entity_pairs = sent_entity_pairs
            total_entities += len(all_entities)

        task.entities_extracted = total_entities

    def _re_step(self, task: PipelineTask):
        self._update_status(task, TaskStatus.RE)
        total_relations = 0

        for doc in task.documents:
            sent_entity_pairs = getattr(doc, "_sent_entity_pairs", [])
            all_relations: List[Relation] = []

            for sentence, entities in sent_entity_pairs:
                if len(entities) >= 2:
                    rels = self._re.predict_sentence(sentence, entities)
                    all_relations.extend(rels)

            doc._relations = all_relations
            total_relations += len(all_relations)

        task.relations_extracted = total_relations

    def _fusion_step(self, task: PipelineTask):
        self._update_status(task, TaskStatus.FUSION)

        existing_nodes = self._graph.get_all_entity_nodes()
        self._fusion.set_existing_nodes(existing_nodes)

        all_triples: List[Triple] = []

        for doc in task.documents:
            sent_entity_pairs = getattr(doc, "_sent_entity_pairs", [])
            relations = getattr(doc, "_relations", [])

            sentence_ctx_map = {}
            for sentence, entities in sent_entity_pairs:
                for ent in entities:
                    self._fusion.add_or_merge(ent, doc.source, sentence)
                sentence_ctx_map[sentence] = entities

            for rel in relations:
                head_mapped = self._fusion.find_match(
                    Entity(text=rel.head_text, type=rel.head_type, start=0, end=0),
                    rel.sentence,
                ) or rel.head_text
                tail_mapped = self._fusion.find_match(
                    Entity(text=rel.tail_text, type=rel.tail_type, start=0, end=0),
                    rel.sentence,
                ) or rel.tail_text

                if rel.relation != "无关系":
                    triple = Triple(
                        head=head_mapped,
                        head_type=rel.head_type,
                        relation=rel.relation,
                        tail=tail_mapped,
                        tail_type=rel.tail_type,
                        confidence=rel.confidence,
                        source_sentence=rel.sentence,
                        source_doc_id=doc.doc_id,
                    )
                    all_triples.append(triple)

        self._graph.add_triples_bulk(all_triples)

        task.processed_documents = len(task.documents)

    def execute_task(self, task_id: str):
        task = self.get_task(task_id)
        if task is None:
            logger.error(f"Task {task_id} not found")
            return

        if task.status not in (TaskStatus.QUEUED, TaskStatus.FAILED):
            logger.warning(f"Task {task_id} already running or completed")
            return

        try:
            self._preprocess_step(task)
            self._ner_step(task)
            self._re_step(task)
            self._fusion_step(task)
            self._update_status(task, TaskStatus.COMPLETED)
        except Exception as e:
            current_step = ""
            if task.status == TaskStatus.PREPROCESSING:
                current_step = "预处理"
            elif task.status == TaskStatus.NER:
                current_step = "实体识别"
            elif task.status == TaskStatus.RE:
                current_step = "关系抽取"
            elif task.status == TaskStatus.FUSION:
                current_step = "融合入图"
            else:
                current_step = "未知步骤"
            self._set_failure(task, current_step, str(e))

    def submit_task(self, request: TaskCreateRequest) -> TaskResponse:
        task = self.create_task(request)

        thread = threading.Thread(
            target=self.execute_task,
            args=(task.task_id,),
            daemon=True,
        )
        thread.start()

        return self._task_to_response(task)

    def retry_task(self, task_id: str) -> Optional[TaskResponse]:
        task = self.get_task(task_id)
        if task is None or task.status != TaskStatus.FAILED:
            return None

        task.status = TaskStatus.QUEUED
        task.error_message = None
        task.failed_step = None
        task.updated_at = datetime.utcnow()

        thread = threading.Thread(
            target=self.execute_task,
            args=(task.task_id,),
            daemon=True,
        )
        thread.start()

        return self._task_to_response(task)

    @staticmethod
    def _task_to_response(task: PipelineTask) -> TaskResponse:
        return TaskResponse(
            task_id=task.task_id,
            status=task.status,
            created_at=task.created_at,
            total_documents=task.total_documents,
            processed_documents=task.processed_documents,
            entities_extracted=task.entities_extracted,
            relations_extracted=task.relations_extracted,
            error_message=task.error_message,
            failed_step=task.failed_step,
        )

    def get_task_status(self, task_id: str) -> Optional[TaskResponse]:
        task = self.get_task(task_id)
        if task is None:
            return None
        return self._task_to_response(task)

    def list_task_history(self, limit: int = 50) -> List[TaskResponse]:
        tasks = self.list_tasks(limit)
        return [self._task_to_response(t) for t in tasks]
