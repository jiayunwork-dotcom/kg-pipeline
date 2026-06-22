import uuid
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime

from src.models.schemas import (
    Snapshot,
    SnapshotEntity,
    SnapshotRelation,
    SnapshotDiffResponse,
    SnapshotListItem,
    DiffEntity,
    DiffRelation,
)
from src.graph.store import GraphStore
from src.utils.database import db

logger = logging.getLogger(__name__)

MAX_ENTITY_LIST = 500
MAX_RELATION_LIST = 500


class SnapshotManager:
    _instance: Optional["SnapshotManager"] = None

    def __init__(self):
        self._graph = GraphStore.get_instance()

    @classmethod
    def get_instance(cls) -> "SnapshotManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def create_snapshot(
        self,
        description: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> Snapshot:
        snapshot_id = f"snap_{uuid.uuid4().hex[:12]}"
        created_at = datetime.utcnow()

        try:
            stats = self._graph.get_graph_stats()
            entity_list = self._graph.get_top_entities(limit=MAX_ENTITY_LIST)
            relation_list = self._graph.get_top_relations(limit=MAX_RELATION_LIST)
        except Exception as e:
            logger.error(f"Failed to collect graph data for snapshot: {e}")
            stats = None
            entity_list = []
            relation_list = []

        snapshot_data = {
            "snapshot_id": snapshot_id,
            "task_id": task_id,
            "description": description,
            "total_entities": stats.total_entities if stats else 0,
            "total_relations": stats.total_relations if stats else 0,
            "entity_type_distribution": (
                stats.entity_type_distribution if stats else {}
            ),
            "relation_type_distribution": (
                stats.relation_type_distribution if stats else {}
            ),
            "entity_list": entity_list,
            "relation_list": relation_list,
            "created_at": created_at.isoformat(),
        }

        try:
            db.save_snapshot(snapshot_data)
            logger.info(
                f"Snapshot {snapshot_id} created: "
                f"entities={snapshot_data['total_entities']}, "
                f"relations={snapshot_data['total_relations']}"
            )
        except Exception as e:
            logger.error(f"Failed to save snapshot {snapshot_id}: {e}")

        return Snapshot(
            snapshot_id=snapshot_id,
            task_id=task_id,
            description=description,
            total_entities=snapshot_data["total_entities"],
            total_relations=snapshot_data["total_relations"],
            entity_type_distribution=snapshot_data["entity_type_distribution"],
            relation_type_distribution=snapshot_data["relation_type_distribution"],
            entity_list=[SnapshotEntity(**e) for e in entity_list],
            relation_list=[SnapshotRelation(**r) for r in relation_list],
            created_at=created_at,
        )

    def get_snapshot(self, snapshot_id: str) -> Optional[Snapshot]:
        try:
            data = db.get_snapshot(snapshot_id)
        except Exception as e:
            logger.error(f"Failed to get snapshot {snapshot_id}: {e}")
            return None

        if data is None:
            return None

        return Snapshot(
            snapshot_id=data["snapshot_id"],
            task_id=data.get("task_id"),
            description=data.get("description"),
            total_entities=data.get("total_entities", 0),
            total_relations=data.get("total_relations", 0),
            entity_type_distribution=data.get("entity_type_distribution", {}),
            relation_type_distribution=data.get("relation_type_distribution", {}),
            entity_list=[SnapshotEntity(**e) for e in data.get("entity_list", [])],
            relation_list=[
                SnapshotRelation(**r) for r in data.get("relation_list", [])
            ],
            created_at=datetime.fromisoformat(data["created_at"]),
        )

    def list_snapshots(self, limit: int = 100) -> List[SnapshotListItem]:
        try:
            rows = db.list_snapshots(limit=limit)
        except Exception as e:
            logger.error(f"Failed to list snapshots: {e}")
            return []

        return [
            SnapshotListItem(
                snapshot_id=row["snapshot_id"],
                task_id=row.get("task_id"),
                description=row.get("description"),
                total_entities=row.get("total_entities", 0),
                total_relations=row.get("total_relations", 0),
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    def compare_snapshots(
        self, snapshot_a_id: str, snapshot_b_id: str
    ) -> Optional[SnapshotDiffResponse]:
        snap_a = self.get_snapshot(snapshot_a_id)
        snap_b = self.get_snapshot(snapshot_b_id)

        if snap_a is None or snap_b is None:
            return None

        a_entities = {e.name: e for e in snap_a.entity_list}
        b_entities = {e.name: e for e in snap_b.entity_list}

        added_entity_names = set(b_entities.keys()) - set(a_entities.keys())
        removed_entity_names = set(a_entities.keys()) - set(b_entities.keys())

        added_entities = [
            DiffEntity(
                name=b_entities[name].name,
                type=b_entities[name].type,
                frequency=b_entities[name].frequency,
                change_type="added",
                source_snapshot_id=snapshot_b_id,
                source_snapshot_time=snap_b.created_at,
            )
            for name in added_entity_names
        ]
        added_entities.sort(key=lambda e: e.frequency, reverse=True)

        removed_entities = [
            DiffEntity(
                name=a_entities[name].name,
                type=a_entities[name].type,
                frequency=a_entities[name].frequency,
                change_type="removed",
                source_snapshot_id=snapshot_a_id,
                source_snapshot_time=snap_a.created_at,
            )
            for name in removed_entity_names
        ]
        removed_entities.sort(key=lambda e: e.frequency, reverse=True)

        a_relations = {
            (r.head, r.relation, r.tail): r for r in snap_a.relation_list
        }
        b_relations = {
            (r.head, r.relation, r.tail): r for r in snap_b.relation_list
        }

        added_rel_keys = set(b_relations.keys()) - set(a_relations.keys())
        removed_rel_keys = set(a_relations.keys()) - set(b_relations.keys())

        added_relations = [
            DiffRelation(
                head=b_relations[key].head,
                head_type=b_relations[key].head_type,
                relation=b_relations[key].relation,
                tail=b_relations[key].tail,
                tail_type=b_relations[key].tail_type,
                confidence=b_relations[key].confidence,
                change_type="added",
                source_snapshot_id=snapshot_b_id,
                source_snapshot_time=snap_b.created_at,
            )
            for key in added_rel_keys
        ]
        added_relations.sort(key=lambda r: r.confidence, reverse=True)

        removed_relations = [
            DiffRelation(
                head=a_relations[key].head,
                head_type=a_relations[key].head_type,
                relation=a_relations[key].relation,
                tail=a_relations[key].tail,
                tail_type=a_relations[key].tail_type,
                confidence=a_relations[key].confidence,
                change_type="removed",
                source_snapshot_id=snapshot_a_id,
                source_snapshot_time=snap_a.created_at,
            )
            for key in removed_rel_keys
        ]
        removed_relations.sort(key=lambda r: r.confidence, reverse=True)

        return SnapshotDiffResponse(
            snapshot_a_id=snapshot_a_id,
            snapshot_b_id=snapshot_b_id,
            snapshot_a_time=snap_a.created_at,
            snapshot_b_time=snap_b.created_at,
            added_entities=added_entities,
            removed_entities=removed_entities,
            added_relations=added_relations,
            removed_relations=removed_relations,
            entity_change_count=len(added_entities) + len(removed_entities),
            relation_change_count=len(added_relations) + len(removed_relations),
        )


snapshot_manager = SnapshotManager.get_instance()
