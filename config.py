"""Central configuration for PolyDB Context Graph Engine."""
import os
from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # App
    APP_NAME: str = "PolyDB Context Graph Engine"
    DEBUG: bool = False
    API_VERSION: str = "v1"

    # Metadata Store (PostgreSQL - system DB)
    METADATA_DB_URL: str = os.getenv(
        "METADATA_DB_URL",
        "postgresql+asyncpg://user:password@localhost:5432/metadata_store"
    )

    # Target databases to analyze (JSON list of connection configs)
    TARGET_DATABASES: str = os.getenv("TARGET_DATABASES", "[]")

    # Gemini
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = "gemini-2.5-flash"
    LLM_MAX_TOKENS: int = 2048

    # Embeddings
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    FAISS_INDEX_PATH: str = "./faiss_index"
    EMBEDDING_DIM: int = 384

    # Graph
    GRAPH_PARTIAL_LOAD: bool = True
    MAX_HOP_DEPTH: int = 3
    INFERENCE_CONFIDENCE_THRESHOLD: float = 0.6

    # Cache
    CACHE_TTL_SECONDS: int = 300
    QUERY_CACHE_SIZE: int = 1000

    # Security
    SENSITIVE_COLUMN_PATTERNS: list = [
        "password", "passwd", "secret", "token", "ssn",
        "credit_card", "cvv", "private_key", "api_key"
    ]
    EXCLUDED_SCHEMAS: list = [
        "pg_catalog", "information_schema", "pg_toast",
        "performance_schema", "sys", "mysql"
    ]

    # Workers
    EXTRACTION_BATCH_SIZE: int = 50
    ENRICHMENT_BATCH_SIZE: int = 10

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
