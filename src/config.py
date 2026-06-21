from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "kgpipeline2024"
    NEO4J_DATABASE: str = "neo4j"

    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000

    MODEL_CACHE_DIR: str = "./model_cache"
    NER_MODEL_NAME: str = "bert-base-chinese"
    RE_MODEL_NAME: str = "bert-base-chinese"
    SENTENCE_MODEL_NAME: str = "paraphrase-multilingual-MiniLM-L12-v2"

    CONFIDENCE_THRESHOLD: float = 0.6
    MAX_PATH_LENGTH: int = 5
    DEFAULT_SUBGRAPH_HOPS: int = 2

    UPLOAD_DIR: str = "./uploads"
    MAX_UPLOAD_SIZE: int = 50 * 1024 * 1024

    TASK_TIMEOUT_SECONDS: int = 3600


settings = Settings()
