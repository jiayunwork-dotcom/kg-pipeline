import logging
from typing import List, Dict, Optional, Set, Any
from datetime import datetime
from contextlib import contextmanager

from neo4j import GraphDatabase, Driver, Session, Transaction

from src.config import settings
from src.models.schemas import EntityNode, Triple, GraphStats, RELATION_TYPES

logger = logging.getLogger(__name__)


class GraphStore:
    _instance: Optional["GraphStore"] = None

    def __init__(self):
        self._driver: Optional[Driver] = None
        self._connect()
        self._initialize_schema()

    @classmethod
    def get_instance(cls) -> "GraphStore":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _connect(self):
        try:
            self._driver = GraphDatabase.driver(
                settings.NEO4J_URI,
                auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
            )
            self._driver.verify_connectivity()
            logger.info("Connected to Neo4j successfully")
        except Exception as e:
            logger.error(f"Failed to connect to Neo4j: {e}")
            self._driver = None

    def _initialize_schema(self):
        if self._driver is None:
            return
        try:
            with self._driver.session() as session:
                session.run(
                    "CREATE CONSTRAINT entity_name_unique IF NOT EXISTS "
                    "FOR (e:Entity) REQUIRE e.name IS UNIQUE"
                )
                session.run(
                    "CREATE INDEX entity_type IF NOT EXISTS "
                    "FOR (e:Entity) ON (e.type)"
                )
                session.run(
                    "CREATE INDEX relation_type IF NOT EXISTS "
                    "FOR ()-[r:RELATES]->() ON (r.type)"
                )
                session.run(
                    "CREATE INDEX relation_confidence IF NOT EXISTS "
                    "FOR ()-[r:RELATES]->() ON (r.confidence)"
                )
            logger.info("Neo4j schema initialized")
        except Exception as e:
            logger.warning(f"Schema initialization skipped: {e}")

    @contextmanager
    def _session(self):
        if self._driver is None:
            raise RuntimeError("Neo4j driver not initialized")
        session = self._driver.session(database=settings.NEO4J_DATABASE)
        try:
            yield session
        finally:
            session.close()

    def is_connected(self) -> bool:
        if self._driver is None:
            return False
        try:
            self._driver.verify_connectivity()
            return True
        except Exception:
            return False

    def upsert_entity_node(
        self,
        node: EntityNode,
    ) -> bool:
        if self._driver is None:
            return False
        try:
            with self._session() as session:
                result = session.run(
                    """
                    MERGE (e:Entity {name: $name})
                    ON CREATE SET
                        e.type = $type,
                        e.aliases = $aliases,
                        e.first_source = $first_source,
                        e.frequency = $frequency,
                        e.created_at = datetime()
                    ON MATCH SET
                        e.frequency = COALESCE(e.frequency, 0) + $freq_increment,
                        e.aliases = CASE
                            WHEN $new_alias IS NOT NULL AND NOT $new_alias IN COALESCE(e.aliases, [])
                            THEN COALESCE(e.aliases, []) + $new_alias
                            ELSE COALESCE(e.aliases, [])
                        END
                    RETURN e
                    """,
                    name=node.canonical_name,
                    type=node.type,
                    aliases=node.aliases,
                    first_source=node.first_source,
                    frequency=node.frequency,
                    freq_increment=node.frequency,
                    new_alias=node.aliases[0] if node.aliases else None,
                )
                return result.single() is not None
        except Exception as e:
            logger.error(f"Failed to upsert entity node: {e}")
            return False

    def _check_conflict(
        self,
        tx: Transaction,
        head: str,
        tail: str,
        new_relation: str,
    ) -> bool:
        hierarchical_rels = {"隶属于", "子类关系", "位于"}
        if new_relation not in hierarchical_rels:
            return False

        result = tx.run(
            """
            MATCH (h:Entity {name: $head})-[r:RELATES]->(t:Entity)
            WHERE r.type IN $hierarchical_rels AND t.name <> $tail
            RETURN r.type AS existing_relation, t.name AS existing_tail
            LIMIT 10
            """,
            head=head,
            tail=tail,
            hierarchical_rels=list(hierarchical_rels),
        )

        existing_targets: Dict[str, str] = {}
        for record in result:
            existing_targets[record["existing_tail"]] = record["existing_relation"]

        if new_relation in existing_targets.values():
            for etail, erel in existing_targets.items():
                if erel == new_relation and etail != tail:
                    return True

        return False

    def add_triple(
        self,
        triple: Triple,
    ) -> Dict[str, Any]:
        if self._driver is None:
            return {"success": False, "conflict": False, "updated": False}
        try:
            with self._session() as session:
                conflict = session.execute_write(
                    self._check_conflict,
                    triple.head,
                    triple.tail,
                    triple.relation,
                )

                result = session.run(
                    """
                    MERGE (h:Entity {name: $head_name})
                    ON CREATE SET
                        h.type = $head_type,
                        h.aliases = [],
                        h.first_source = $source_doc,
                        h.frequency = 1,
                        h.created_at = datetime()
                    MERGE (t:Entity {name: $tail_name})
                    ON CREATE SET
                        t.type = $tail_type,
                        t.aliases = [],
                        t.first_source = $source_doc,
                        t.frequency = 1,
                        t.created_at = datetime()
                    MERGE (h)-[r:RELATES]->(t)
                    ON CREATE SET
                        r.type = $rel_type,
                        r.confidence = $confidence,
                        r.sentences = [$sentence],
                        r.source_docs = [$source_doc],
                        r.extraction_time = datetime(),
                        r.conflict = $conflict
                    ON MATCH SET
                        r.confidence = CASE
                            WHEN $confidence > COALESCE(r.confidence, 0)
                            THEN $confidence
                            ELSE COALESCE(r.confidence, 0)
                        END,
                        r.sentences = CASE
                            WHEN NOT $sentence IN COALESCE(r.sentences, [])
                            THEN COALESCE(r.sentences, []) + $sentence
                            ELSE COALESCE(r.sentences, [])
                        END,
                        r.source_docs = CASE
                            WHEN NOT $source_doc IN COALESCE(r.source_docs, [])
                            THEN COALESCE(r.source_docs, []) + $source_doc
                            ELSE COALESCE(r.source_docs, [])
                        END,
                        r.conflict = COALESCE(r.conflict, false) OR $conflict,
                        r.update_time = datetime()
                    RETURN
                        r.type AS rel_type,
                        r.confidence AS confidence,
                        r.conflict AS conflict,
                        EXISTS { MATCH (h)-[r:RELATES]->(t) WHERE r IS NOT NULL } AS existed
                    """,
                    head_name=triple.head,
                    head_type=triple.head_type,
                    tail_name=triple.tail,
                    tail_type=triple.tail_type,
                    rel_type=triple.relation,
                    confidence=triple.confidence,
                    sentence=triple.source_sentence,
                    source_doc=triple.source_doc_id,
                    conflict=conflict,
                )

                record = result.single()
                return {
                    "success": True,
                    "conflict": conflict,
                    "updated": record is not None,
                }
        except Exception as e:
            logger.error(f"Failed to add triple: {e}")
            return {"success": False, "conflict": False, "updated": False}

    def add_triples_bulk(
        self,
        triples: List[Triple],
    ) -> Dict[str, int]:
        stats = {"success": 0, "failed": 0, "conflict": 0}
        for triple in triples:
            result = self.add_triple(triple)
            if result.get("success"):
                stats["success"] += 1
                if result.get("conflict"):
                    stats["conflict"] += 1
            else:
                stats["failed"] += 1
        return stats

    def get_all_entity_nodes(self) -> List[EntityNode]:
        if self._driver is None:
            return []
        try:
            with self._session() as session:
                result = session.run(
                    """
                    MATCH (e:Entity)
                    RETURN
                        e.name AS name,
                        COALESCE(e.type, 'UNKNOWN') AS type,
                        COALESCE(e.aliases, []) AS aliases,
                        COALESCE(e.first_source, '') AS first_source,
                        COALESCE(e.frequency, 1) AS frequency
                    """
                )
                nodes = []
                for record in result:
                    nodes.append(
                        EntityNode(
                            canonical_name=record["name"],
                            type=record["type"],
                            aliases=list(record["aliases"]),
                            first_source=record["first_source"],
                            frequency=record["frequency"],
                        )
                    )
                return nodes
        except Exception as e:
            logger.error(f"Failed to get all entity nodes: {e}")
            return []

    def search_entity(
        self,
        name: str,
        limit: int = 20,
    ) -> List[EntityNode]:
        if self._driver is None:
            return []
        try:
            with self._session() as session:
                result = session.run(
                    """
                    MATCH (e:Entity)
                    WHERE e.name CONTAINS $name
                       OR ANY(alias IN COALESCE(e.aliases, []) WHERE alias CONTAINS $name)
                    RETURN
                        e.name AS name,
                        COALESCE(e.type, 'UNKNOWN') AS type,
                        COALESCE(e.aliases, []) AS aliases,
                        COALESCE(e.first_source, '') AS first_source,
                        COALESCE(e.frequency, 1) AS frequency
                    ORDER BY e.frequency DESC
                    LIMIT $limit
                    """,
                    name=name,
                    limit=limit,
                )
                nodes = []
                for record in result:
                    nodes.append(
                        EntityNode(
                            canonical_name=record["name"],
                            type=record["type"],
                            aliases=list(record["aliases"]),
                            first_source=record["first_source"],
                            frequency=record["frequency"],
                        )
                    )
                return nodes
        except Exception as e:
            logger.error(f"Failed to search entity: {e}")
            return []

    def get_entity_relations(
        self,
        entity_name: str,
        min_confidence: float = 0.0,
        relation_types: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        if self._driver is None:
            return []
        try:
            with self._session() as session:
                cypher = """
                    MATCH (e:Entity {name: $name})-[r:RELATES]-(other:Entity)
                    WHERE r.confidence >= $min_confidence
                """
                params = {
                    "name": entity_name,
                    "min_confidence": min_confidence,
                }
                if relation_types:
                    cypher += " AND r.type IN $relation_types"
                    params["relation_types"] = relation_types

                cypher += """
                    RETURN
                        CASE WHEN startNode(r) = e THEN 'out' ELSE 'in' END AS direction,
                        r.type AS relation,
                        r.confidence AS confidence,
                        COALESCE(r.sentences, []) AS sentences,
                        COALESCE(r.source_docs, []) AS source_docs,
                        other.name AS other_name,
                        COALESCE(other.type, 'UNKNOWN') AS other_type
                    ORDER BY r.confidence DESC
                """

                result = session.run(cypher, **params)
                relations = []
                for record in result:
                    relations.append(
                        {
                            "direction": record["direction"],
                            "relation": record["relation"],
                            "confidence": record["confidence"],
                            "sentences": list(record["sentences"]),
                            "source_docs": list(record["source_docs"]),
                            "other_name": record["other_name"],
                            "other_type": record["other_type"],
                        }
                    )
                return relations
        except Exception as e:
            logger.error(f"Failed to get entity relations: {e}")
            return []

    def get_subgraph(
        self,
        entity_name: str,
        hops: int = 2,
        min_confidence: float = 0.0,
        relation_types: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        if self._driver is None:
            return {"nodes": [], "edges": []}
        try:
            with self._session() as session:
                cypher = """
                    MATCH path = (start:Entity {name: $name})-[:RELATES*1..%d]-(connected:Entity)
                    WHERE ALL(r IN relationships(path) WHERE r.confidence >= $min_confidence)
                """ % hops
                params = {
                    "name": entity_name,
                    "min_confidence": min_confidence,
                }
                if relation_types:
                    cypher += " AND ALL(r IN relationships(path) WHERE r.type IN $relation_types)"
                    params["relation_types"] = relation_types

                cypher += """
                    WITH DISTINCT nodes(path) AS all_nodes, relationships(path) AS all_rels
                    UNWIND all_nodes AS n
                    WITH COLLECT(DISTINCT {
                        id: n.name,
                        name: n.name,
                        type: COALESCE(n.type, 'UNKNOWN'),
                        frequency: COALESCE(n.frequency, 1),
                        aliases: COALESCE(n.aliases, [])
                    }) AS nodes, all_rels
                    UNWIND all_rels AS r
                    WITH nodes, COLLECT(DISTINCT {
                        source: startNode(r).name,
                        target: endNode(r).name,
                        relation: r.type,
                        confidence: r.confidence
                    }) AS edges
                    RETURN nodes, edges
                """

                result = session.run(cypher, **params)
                record = result.single()
                if record is None:
                    start_node = session.run(
                        """
                        MATCH (e:Entity {name: $name})
                        RETURN {
                            id: e.name,
                            name: e.name,
                            type: COALESCE(e.type, 'UNKNOWN'),
                            frequency: COALESCE(e.frequency, 1),
                            aliases: COALESCE(e.aliases, [])
                        } AS node
                        """,
                        name=entity_name,
                    ).single()
                    if start_node:
                        return {"nodes": [start_node["node"]], "edges": []}
                    return {"nodes": [], "edges": []}
                return {
                    "nodes": list(record["nodes"]),
                    "edges": list(record["edges"]),
                }
        except Exception as e:
            logger.error(f"Failed to get subgraph: {e}")
            return {"nodes": [], "edges": []}

    def find_shortest_path(
        self,
        entity1: str,
        entity2: str,
        max_hops: int = 5,
        min_confidence: float = 0.0,
    ) -> List[Dict[str, Any]]:
        if self._driver is None:
            return []
        try:
            with self._session() as session:
                result = session.run(
                    """
                    MATCH (a:Entity {name: $e1}), (b:Entity {name: $e2})
                    MATCH path = shortestPath((a)-[:RELATES*1..%d]-(b))
                    WHERE ALL(r IN relationships(path) WHERE r.confidence >= $min_confidence)
                    RETURN
                        [n IN nodes(path) | n.name] AS node_names,
                        [n IN nodes(path) | COALESCE(n.type, 'UNKNOWN')] AS node_types,
                        [r IN relationships(path) | r.type] AS relation_types,
                        [r IN relationships(path) | r.confidence] AS confidences,
                        length(path) AS path_length
                    """
                    % max_hops,
                    e1=entity1,
                    e2=entity2,
                    min_confidence=min_confidence,
                )
                paths = []
                for record in result:
                    paths.append(
                        {
                            "node_names": list(record["node_names"]),
                            "node_types": list(record["node_types"]),
                            "relation_types": list(record["relation_types"]),
                            "confidences": list(record["confidences"]),
                            "path_length": record["path_length"],
                        }
                    )
                return paths
        except Exception as e:
            logger.error(f"Failed to find shortest path: {e}")
            return []

    def get_graph_stats(self) -> GraphStats:
        if self._driver is None:
            return GraphStats(
                total_entities=0,
                total_relations=0,
                entity_type_distribution={},
                relation_type_distribution={},
            )
        try:
            with self._session() as session:
                entity_count = session.run(
                    "MATCH (e:Entity) RETURN count(e) AS cnt"
                ).single()["cnt"]

                rel_count = session.run(
                    "MATCH ()-[r:RELATES]->() RETURN count(r) AS cnt"
                ).single()["cnt"]

                entity_types = session.run(
                    """
                    MATCH (e:Entity)
                    RETURN COALESCE(e.type, 'UNKNOWN') AS type, count(e) AS cnt
                    ORDER BY cnt DESC
                    """
                )
                entity_type_dist = {}
                for record in entity_types:
                    entity_type_dist[record["type"]] = record["cnt"]

                rel_types = session.run(
                    """
                    MATCH ()-[r:RELATES]->()
                    RETURN r.type AS type, count(r) AS cnt
                    ORDER BY cnt DESC
                    """
                )
                rel_type_dist = {}
                for record in rel_types:
                    rel_type_dist[record["type"]] = record["cnt"]

                return GraphStats(
                    total_entities=entity_count,
                    total_relations=rel_count,
                    entity_type_distribution=entity_type_dist,
                    relation_type_distribution=rel_type_dist,
                )
        except Exception as e:
            logger.error(f"Failed to get graph stats: {e}")
            return GraphStats(
                total_entities=0,
                total_relations=0,
                entity_type_distribution={},
                relation_type_distribution={},
            )

    def get_all_graph_data(
        self,
        min_confidence: float = 0.0,
        max_nodes: int = 1000,
    ) -> Dict[str, Any]:
        if self._driver is None:
            return {"nodes": [], "edges": []}
        try:
            with self._session() as session:
                result = session.run(
                    """
                    MATCH (e:Entity)
                    WITH e ORDER BY COALESCE(e.frequency, 1) DESC
                    LIMIT $max_nodes
                    WITH COLLECT(e) AS top_nodes
                    UNWIND top_nodes AS n
                    WITH COLLECT({
                        id: n.name,
                        name: n.name,
                        type: COALESCE(n.type, 'UNKNOWN'),
                        frequency: COALESCE(n.frequency, 1),
                        aliases: COALESCE(n.aliases, [])
                    }) AS nodes, top_nodes
                    MATCH (a)-[r:RELATES]->(b)
                    WHERE a IN top_nodes AND b IN top_nodes AND r.confidence >= $min_confidence
                    WITH nodes, COLLECT(DISTINCT {
                        source: a.name,
                        target: b.name,
                        relation: r.type,
                        confidence: r.confidence
                    }) AS edges
                    RETURN nodes, edges
                    """,
                    min_confidence=min_confidence,
                    max_nodes=max_nodes,
                )
                record = result.single()
                if record is None:
                    return {"nodes": [], "edges": []}
                return {
                    "nodes": list(record["nodes"]),
                    "edges": list(record["edges"]),
                }
        except Exception as e:
            logger.error(f"Failed to get all graph data: {e}")
            return {"nodes": [], "edges": []}

    def get_random_triples(self, count: int = 100) -> List[Dict[str, Any]]:
        if self._driver is None:
            return []
        try:
            with self._session() as session:
                result = session.run(
                    """
                    MATCH (a)-[r:RELATES]->(b)
                    WITH a, r, b, rand() AS random
                    ORDER BY random
                    LIMIT $count
                    RETURN
                        a.name AS head,
                        COALESCE(a.type, 'UNKNOWN') AS head_type,
                        r.type AS relation,
                        b.name AS tail,
                        COALESCE(b.type, 'UNKNOWN') AS tail_type,
                        r.confidence AS confidence,
                        r.sentences AS sentences,
                        COALESCE(r.source_docs, []) AS source_docs
                    """,
                    count=count,
                )
                triples = []
                for record in result:
                    triples.append(
                        {
                            "id": f"{record['head']}_{record['relation']}_{record['tail']}",
                            "head": record["head"],
                            "head_type": record["head_type"],
                            "relation": record["relation"],
                            "tail": record["tail"],
                            "tail_type": record["tail_type"],
                            "confidence": record["confidence"],
                            "sentences": list(record["sentences"]) if record["sentences"] else [],
                            "source_docs": list(record["source_docs"]),
                        }
                    )
                return triples
        except Exception as e:
            logger.error(f"Failed to get random triples: {e}")
            return []

    def get_top_entities(self, limit: int = 500) -> List[Dict[str, Any]]:
        if self._driver is None:
            return []
        try:
            with self._session() as session:
                result = session.run(
                    """
                    MATCH (e:Entity)
                    RETURN
                        e.name AS name,
                        COALESCE(e.type, 'UNKNOWN') AS type,
                        COALESCE(e.frequency, 1) AS frequency
                    ORDER BY frequency DESC
                    LIMIT $limit
                    """,
                    limit=limit,
                )
                entities = []
                for record in result:
                    entities.append(
                        {
                            "name": record["name"],
                            "type": record["type"],
                            "frequency": record["frequency"],
                        }
                    )
                return entities
        except Exception as e:
            logger.error(f"Failed to get top entities: {e}")
            return []

    def get_top_relations(self, limit: int = 500) -> List[Dict[str, Any]]:
        if self._driver is None:
            return []
        try:
            with self._session() as session:
                result = session.run(
                    """
                    MATCH (a)-[r:RELATES]->(b)
                    RETURN
                        a.name AS head,
                        COALESCE(a.type, 'UNKNOWN') AS head_type,
                        r.type AS relation,
                        b.name AS tail,
                        COALESCE(b.type, 'UNKNOWN') AS tail_type,
                        r.confidence AS confidence,
                        COALESCE(size(r.sentences), 1) AS freq
                    ORDER BY freq DESC, confidence DESC
                    LIMIT $limit
                    """,
                    limit=limit,
                )
                relations = []
                for record in result:
                    relations.append(
                        {
                            "head": record["head"],
                            "head_type": record["head_type"],
                            "relation": record["relation"],
                            "tail": record["tail"],
                            "tail_type": record["tail_type"],
                            "confidence": record["confidence"],
                        }
                    )
                return relations
        except Exception as e:
            logger.error(f"Failed to get top relations: {e}")
            return []

    def close(self):
        if self._driver is not None:
            self._driver.close()
            self._driver = None
