import os
import json
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
from src.utils.database import db

logger = logging.getLogger(__name__)

MAX_HISTORY = 500


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

    def to_db_dict(self) -> Dict[str, Any]:
        request_dict = self.request.model_dump() if hasattr(self.request, "model_dump") else {}
        return {
            "task_id": self.task_id,
            "request_json": json.dumps(request_dict, ensure_ascii=False),
            "status": self.status.value if hasattr(self.status, "value") else str(self.status),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "total_documents": self.total_documents,
            "processed_documents": self.processed_documents,
            "entities_extracted": self.entities_extracted,
            "relations_extracted": self.relations_extracted,
            "error_message": self.error_message,
            "failed_step": self.failed_step,
        }


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
        self._load_from_db()

    def _load_from_db(self):
        try:
            rows = db.list_tasks(limit=MAX_HISTORY)
            loaded = 0
            for row in rows:
                try:
                    req_json = json.loads(row.get("request_json", "{}"))
                    request = TaskCreateRequest(**req_json)
                    task = PipelineTask(row["task_id"], request)
                    status_val = row.get("status", TaskStatus.QUEUED.value)
                    for s in TaskStatus:
                        if s.value == status_val:
                            task.status = s
                            break
                    task.created_at = datetime.fromisoformat(row["created_at"])
                    task.updated_at = datetime.fromisoformat(row["updated_at"])
                    task.total_documents = row.get("total_documents", 0)
                    task.processed_documents = row.get("processed_documents", 0)
                    task.entities_extracted = row.get("entities_extracted", 0)
                    task.relations_extracted = row.get("relations_extracted", 0)
                    task.error_message = row.get("error_message")
                    task.failed_step = row.get("failed_step")
                    if request.custom_dict_csv:
                        task.custom_dict = CustomDictionary.from_csv(request.custom_dict_csv)
                    with self._lock:
                        self._tasks[task.task_id] = task
                        self._history.append(task.task_id)
                    loaded += 1
                except Exception as e:
                    logger.warning(f"Failed to restore task {row.get('task_id')}: {e}")
            logger.info(f"Restored {loaded} tasks from database")
        except Exception as e:
            logger.warning(f"Failed to load tasks from database: {e}")

    @classmethod
    def get_instance(cls) -> "TaskManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _persist_task(self, task: PipelineTask):
        try:
            db.save_task(task.to_db_dict())
        except Exception as e:
            logger.warning(f"Failed to persist task {task.task_id}: {e}")

    def _update_status(self, task: PipelineTask, status: TaskStatus):
        task.status = status
        task.updated_at = datetime.utcnow()
        logger.info(f"Task {task.task_id} status: {status.value}")
        self._persist_task(task)

    def _set_failure(self, task: PipelineTask, step: str, error: str):
        task.status = TaskStatus.FAILED
        task.failed_step = step
        task.error_message = error
        task.updated_at = datetime.utcnow()
        logger.error(f"Task {task.task_id} failed at {step}: {error}")
        self._persist_task(task)

    def create_task(self, request: TaskCreateRequest) -> PipelineTask:
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        task = PipelineTask(task_id, request)

        if request.custom_dict_csv:
            task.custom_dict = CustomDictionary.from_csv(request.custom_dict_csv)

        with self._lock:
            self._tasks[task_id] = task
            self._history.appendleft(task_id)

        self._persist_task(task)
        return task

    def get_task(self, task_id: str) -> Optional[PipelineTask]:
        with self._lock:
            task = self._tasks.get(task_id)
        if task is None:
            row = db.get_task(task_id)
            if row:
                try:
                    req_json = json.loads(row.get("request_json", "{}"))
                    request = TaskCreateRequest(**req_json)
                    task = PipelineTask(row["task_id"], request)
                    status_val = row.get("status", TaskStatus.QUEUED.value)
                    for s in TaskStatus:
                        if s.value == status_val:
                            task.status = s
                            break
                    task.created_at = datetime.fromisoformat(row["created_at"])
                    task.updated_at = datetime.fromisoformat(row["updated_at"])
                    task.total_documents = row.get("total_documents", 0)
                    task.processed_documents = row.get("processed_documents", 0)
                    task.entities_extracted = row.get("entities_extracted", 0)
                    task.relations_extracted = row.get("relations_extracted", 0)
                    task.error_message = row.get("error_message")
                    task.failed_step = row.get("failed_step")
                    with self._lock:
                        self._tasks[task_id] = task
                except Exception as e:
                    logger.warning(f"Failed to restore task from DB {task_id}: {e}")
        return task

    def list_tasks(self, limit: int = 50) -> List[PipelineTask]:
        task_ids = []
        with self._lock:
            task_ids = list(self._history)[:limit]
        tasks = []
        for tid in task_ids:
            t = self.get_task(tid)
            if t:
                tasks.append(t)
        if len(tasks) < limit:
            try:
                rows = db.list_tasks(limit=limit)
                existing_ids = {t.task_id for t in tasks}
                for row in rows:
                    if row["task_id"] not in existing_ids:
                        t = self.get_task(row["task_id"])
                        if t:
                            tasks.append(t)
                        if len(tasks) >= limit:
                            break
            except Exception as e:
                logger.warning(f"Failed to list tasks from DB: {e}")
        return tasks[:limit]

    def _collect_documents(self, task: PipelineTask) -> List[Document]:
        docs: List[Document] = []
        req = task.request

        if req.source_type == InputSourceType.TEXT and req.text:
            doc_id = f"{task.task_id}_txt_0"
            logger.info(f"Task {task.task_id}: processing direct text input ({len(req.text)} chars)")
            docs.append(
                Document(
                    doc_id=doc_id,
                    source_type=InputSourceType.TEXT,
                    source="direct_text",
                    raw_text=req.text,
                )
            )

        elif req.source_type == InputSourceType.URL and req.urls:
            logger.info(f"Task {task.task_id}: fetching {len(req.urls)} URLs")
            for i, url in enumerate(req.urls):
                try:
                    logger.info(f"  Fetching URL [{i+1}/{len(req.urls)}]: {url}")
                    content = fetch_and_extract(url)
                    if content and len(content.strip()) > 20:
                        doc_id = f"{task.task_id}_url_{i}"
                        logger.info(f"  -> OK, extracted {len(content)} chars from {url}")
                        docs.append(
                            Document(
                                doc_id=doc_id,
                                source_type=InputSourceType.URL,
                                source=url,
                                raw_text=content,
                            )
                        )
                    else:
                        logger.warning(f"  -> FAILED, extracted empty content from {url}")
                except Exception as e:
                    logger.error(f"  -> ERROR fetching {url}: {e}")
            logger.info(f"Task {task.task_id}: successfully fetched {len(docs)}/{len(req.urls)} URLs")

        return docs

    def _preprocess_step(self, task: PipelineTask):
        self._update_status(task, TaskStatus.PREPROCESSING)
        docs = self._collect_documents(task)
        logger.info(f"Task {task.task_id}: preprocessing {len(docs)} documents")

        processed = 0
        for doc in docs:
            cleaned, sentences = preprocess_text(doc.raw_text)
            doc.raw_text = cleaned
            doc.sentences = sentences
            if sentences:
                processed += 1
            logger.info(f"  Doc {doc.doc_id}: {len(sentences)} sentences, {len(cleaned)} chars")

        task.documents = docs
        task.total_documents = len(docs)
        self._persist_task(task)

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
            logger.info(f"  Doc {doc.doc_id}: {len(all_entities)} entities in {len(doc.sentences)} sentences")

        task.entities_extracted = total_entities
        self._persist_task(task)

    def _re_step(self, task: PipelineTask):
        self._update_status(task, TaskStatus.RE)
        total_relations = 0

        for doc in task.documents:
            sent_entity_pairs = getattr(doc, "_sent_entity_pairs", [])
            all_relations: List[Relation] = []

            for sentence, entities in sent_entity_pairs:
                if len(entities) >= 2:
                    rels = self._re.predict_sentence(sentence, entities)
                    valid_rels = [r for r in rels if r.relation != "无关系"]
                    all_relations.extend(valid_rels)

            doc._relations = all_relations
            total_relations += len(all_relations)
            logger.info(f"  Doc {doc.doc_id}: {len(all_relations)} relations extracted")

        task.relations_extracted = total_relations
        self._persist_task(task)

    def _fusion_step(self, task: PipelineTask):
        self._update_status(task, TaskStatus.FUSION)

        try:
            existing_nodes = self._graph.get_all_entity_nodes()
            logger.info(f"Task {task.task_id}: existing nodes in graph: {len(existing_nodes)}")
            self._fusion.set_existing_nodes(existing_nodes)
        except Exception as e:
            logger.warning(f"Failed to load existing nodes (graph may be empty): {e}")
            self._fusion.set_existing_nodes([])

        all_triples: List[Triple] = []

        for doc in task.documents:
            sent_entity_pairs = getattr(doc, "_sent_entity_pairs", [])
            relations = getattr(doc, "_relations", [])

            for sentence, entities in sent_entity_pairs:
                for ent in entities:
                    self._fusion.add_or_merge(ent, doc.source, sentence)

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

        logger.info(f"Task {task.task_id}: inserting {len(all_triples)} triples into graph")
        if all_triples:
            try:
                result = self._graph.add_triples_bulk(all_triples)
                logger.info(f"  -> Graph result: {result}")
            except Exception as e:
                logger.error(f"Failed to insert triples: {e}")
        else:
            logger.warning("  -> No triples to insert (check NER/RE output)")

        task.processed_documents = len(task.documents)
        self._persist_task(task)

    def execute_task(self, task_id: str):
        task = self.get_task(task_id)
        if task is None:
            logger.error(f"Task {task_id} not found")
            return

        if task.status not in (TaskStatus.QUEUED, TaskStatus.FAILED):
            logger.warning(f"Task {task_id} already running or completed (status={task.status})")
            return

        try:
            self._preprocess_step(task)
            self._ner_step(task)
            self._re_step(task)
            self._fusion_step(task)
            self._update_status(task, TaskStatus.COMPLETED)
            logger.info(
                f"Task {task_id} COMPLETED: "
                f"docs={task.processed_documents}/{task.total_documents}, "
                f"entities={task.entities_extracted}, "
                f"relations={task.relations_extracted}"
            )
        except Exception as e:
            import traceback
            trace_str = traceback.format_exc()
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
            logger.error(f"Task {task_id} exception: {trace_str}")
            self._set_failure(task, current_step, f"{str(e)}")

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
        task.total_documents = 0
        task.processed_documents = 0
        task.entities_extracted = 0
        task.relations_extracted = 0
        task.documents = []
        task.updated_at = datetime.utcnow()
        self._persist_task(task)

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
