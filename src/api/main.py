import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import settings
from src.api.tasks import router as tasks_router
from src.api.graph import router as graph_router
from src.api.quality import router as quality_router
from src.api.qa import router as qa_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting KG Pipeline API server...")
    try:
        from src.graph.store import GraphStore
        store = GraphStore.get_instance()
        if store.is_connected():
            logger.info("Neo4j connection verified on startup")
        else:
            logger.warning("Neo4j not connected on startup")
    except Exception as e:
        logger.error(f"Startup initialization error: {e}")
    yield
    logger.info("Shutting down KG Pipeline API server...")
    try:
        from src.graph.store import GraphStore
        store = GraphStore.get_instance()
        store.close()
    except Exception as e:
        logger.error(f"Shutdown error: {e}")


app = FastAPI(
    title="Knowledge Graph Pipeline API",
    description=(
        "企业级知识图谱自动构建与实体关系抽取后端Pipeline服务。 "
        "支持从非结构化文本中抽取实体和关系，构建可查询的知识图谱。"
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tasks_router)
app.include_router(graph_router)
app.include_router(quality_router)
app.include_router(qa_router)


@app.get("/")
async def root():
    return {
        "name": "Knowledge Graph Pipeline API",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
    }


@app.get("/health")
async def health_check():
    from src.graph.store import GraphStore
    store = GraphStore.get_instance()
    return {
        "status": "healthy",
        "neo4j_connected": store.is_connected(),
    }
