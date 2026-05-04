"""
Unified normalized models for multi-database metadata
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field


class TableType(str, Enum):
    FACT = "fact"
    DIMENSION = "dimension"
    LOG = "log"
    BRIDGE = "bridge"
    STAGING = "staging"
    UNKNOWN = "unknown"


class ColumnRole(str, Enum):
    METRIC = "metric"
    KEY = "key"
    TIMESTAMP = "timestamp"
    CATEGORICAL = "categorical"
    TEXT = "text"
    FOREIGN_KEY = "foreign_key"
    PRIMARY_KEY = "primary_key"
    UNKNOWN = "unknown"


class RelationshipType(str, Enum):
    FOREIGN_KEY = "foreign_key"
    INFERRED_ID = "inferred_id"
    NAMING_SIMILARITY = "naming_similarity"


# ─── Normalized Column ────────────────────────────────────────────────────────

class NormalizedColumn(BaseModel):
    name: str
    data_type: str
    is_nullable: bool = True
    is_primary_key: bool = False
    is_foreign_key: bool = False
    default_value: Optional[str] = None
    role: ColumnRole = ColumnRole.UNKNOWN
    description: Optional[str] = None
    is_sensitive: bool = False


# ─── Normalized Table ─────────────────────────────────────────────────────────

class NormalizedTable(BaseModel):
    source_db: str          # connection name
    source_type: str        # postgresql, mysql, trino
    schema_name: str
    table_name: str
    columns: List[NormalizedColumn] = []
    row_count: Optional[int] = None
    table_type: TableType = TableType.UNKNOWN
    description: Optional[str] = None
    tags: List[str] = []
    last_updated: datetime = Field(default_factory=datetime.utcnow)
    metadata_hash: Optional[str] = None  # for change detection

    @property
    def full_name(self) -> str:
        return f"{self.source_db}.{self.schema_name}.{self.table_name}"

    @property
    def node_id(self) -> str:
        return f"{self.source_db}:{self.schema_name}:{self.table_name}"


# ─── Normalized Relationship ──────────────────────────────────────────────────

class NormalizedRelationship(BaseModel):
    source_db: str
    from_schema: str
    from_table: str
    from_column: str
    to_schema: str
    to_table: str
    to_column: str
    relationship_type: RelationshipType = RelationshipType.FOREIGN_KEY
    confidence: float = 1.0
    last_updated: datetime = Field(default_factory=datetime.utcnow)

    @property
    def edge_id(self) -> str:
        return (
            f"{self.source_db}:{self.from_schema}:{self.from_table}.{self.from_column}"
            f"->{self.to_schema}:{self.to_table}.{self.to_column}"
        )


# ─── Context Models (for LLM / API responses) ────────────────────────────────

class TableContext(BaseModel):
    table: NormalizedTable
    relationships: List[NormalizedRelationship] = []
    related_tables: List[str] = []
    join_paths: List[List[str]] = []
    semantic_neighbors: List[Dict[str, Any]] = []


class SmartQueryResult(BaseModel):
    query: str
    matched_tables: List[str]
    context: Dict[str, Any]
    reasoning: str
    suggested_joins: List[str] = []
    confidence: float = 0.0
    cached: bool = False
