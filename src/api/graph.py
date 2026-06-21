import logging
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, HTTPException, Query

from src.models.schemas import (
    EntitySearchRequest,
    PathSearchRequest,
    GraphFilterRequest,
    GraphStats,
    EntityNode,
)
from src.graph.store import GraphStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/graph", tags=["graph"])

graph_store = GraphStore.get_instance()


@router.get("/health")
async def graph_health():
    return {"connected": graph_store.is_connected()}


@router.get("/stats", response_model=GraphStats)
async def get_graph_stats():
    try:
        return graph_store.get_graph_stats()
    except Exception as e:
        logger.error(f"Failed to get graph stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/entities/search", response_model=List[EntityNode])
async def search_entities(
    name: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=200),
):
    try:
        return graph_store.search_entity(name, limit)
    except Exception as e:
        logger.error(f"Failed to search entities: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/entities/{entity_name}")
async def get_entity_details(entity_name: str):
    try:
        entities = graph_store.search_entity(entity_name, 1)
        if not entities:
            raise HTTPException(status_code=404, detail=f"Entity '{entity_name}' not found")
        node = entities[0]
        relations = graph_store.get_entity_relations(entity_name)
        return {
            "entity": node.model_dump(),
            "relations": relations,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get entity details: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/entities/{entity_name}/relations")
async def get_entity_relations(
    entity_name: str,
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    relation_types: Optional[str] = Query(None),
):
    try:
        rtypes = None
        if relation_types:
            rtypes = [t.strip() for t in relation_types.split(",") if t.strip()]
        return graph_store.get_entity_relations(entity_name, min_confidence, rtypes)
    except Exception as e:
        logger.error(f"Failed to get entity relations: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/subgraph")
async def get_subgraph(
    request: EntitySearchRequest,
):
    try:
        return graph_store.get_subgraph(
            request.name,
            request.hops,
        )
    except Exception as e:
        logger.error(f"Failed to get subgraph: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/subgraph/{entity_name}")
async def get_subgraph_get(
    entity_name: str,
    hops: int = Query(2, ge=1, le=5),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    relation_types: Optional[str] = Query(None),
):
    try:
        rtypes = None
        if relation_types:
            rtypes = [t.strip() for t in relation_types.split(",") if t.strip()]
        return graph_store.get_subgraph(
            entity_name, hops, min_confidence, rtypes
        )
    except Exception as e:
        logger.error(f"Failed to get subgraph: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/path")
async def find_path(request: PathSearchRequest):
    try:
        return graph_store.find_shortest_path(
            request.entity1,
            request.entity2,
            request.max_hops,
        )
    except Exception as e:
        logger.error(f"Failed to find path: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/path")
async def find_path_get(
    entity1: str = Query(...),
    entity2: str = Query(...),
    max_hops: int = Query(5, ge=1, le=10),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
):
    try:
        return graph_store.find_shortest_path(
            entity1, entity2, max_hops, min_confidence
        )
    except Exception as e:
        logger.error(f"Failed to find path: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/filter")
async def filter_graph(request: GraphFilterRequest):
    try:
        return graph_store.get_all_graph_data(
            min_confidence=request.min_confidence,
        )
    except Exception as e:
        logger.error(f"Failed to filter graph: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/data")
async def get_all_graph_data(
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    max_nodes: int = Query(1000, ge=10, le=10000),
):
    try:
        return graph_store.get_all_graph_data(min_confidence, max_nodes)
    except Exception as e:
        logger.error(f"Failed to get all graph data: {e}")
        raise HTTPException(status_code=500, detail=str(e))
