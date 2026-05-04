"""
SQLAlchemy ORM models — PostgreSQL metadata store
"""
from datetime import datetime
from sqlalchemy import (
    Column, String, Boolean, Float, Integer,
    DateTime, Text, JSON, ForeignKey, UniqueConstraint, Index
)
from sqlalchemy.orm import relationship, DeclarativeBase


class Base(DeclarativeBase):
    pass


class DBTableRecord(Base):
    __tablename__ = "db_tables"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_db = Column(String(128), nullable=False)
    source_type = Column(String(32), nullable=False)
    schema_name = Column(String(128), nullable=False)
    table_name = Column(String(256), nullable=False)
    table_type = Column(String(32), default="unknown")
    description = Column(Text, nullable=True)
    tags = Column(JSON, default=list)
    row_count = Column(Integer, nullable=True)
    metadata_hash = Column(String(64), nullable=True)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    embedding_updated = Column(Boolean, default=False)
    enriched = Column(Boolean, default=False)

    columns_rel = relationship("DBColumnRecord", back_populates="table", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("source_db", "schema_name", "table_name", name="uq_table"),
        Index("idx_table_source", "source_db"),
        Index("idx_table_hash", "metadata_hash"),
    )

    @property
    def node_id(self):
        return f"{self.source_db}:{self.schema_name}:{self.table_name}"


class DBColumnRecord(Base):
    __tablename__ = "db_columns"

    id = Column(Integer, primary_key=True, autoincrement=True)
    table_id = Column(Integer, ForeignKey("db_tables.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(256), nullable=False)
    data_type = Column(String(64), nullable=False)
    is_nullable = Column(Boolean, default=True)
    is_primary_key = Column(Boolean, default=False)
    is_foreign_key = Column(Boolean, default=False)
    is_sensitive = Column(Boolean, default=False)
    default_value = Column(String(256), nullable=True)
    role = Column(String(32), default="unknown")
    description = Column(Text, nullable=True)

    table = relationship("DBTableRecord", back_populates="columns_rel")

    __table_args__ = (
        UniqueConstraint("table_id", "name", name="uq_column"),
        Index("idx_col_table", "table_id"),
    )


class DBRelationshipRecord(Base):
    __tablename__ = "db_relationships"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_db = Column(String(128), nullable=False)
    from_schema = Column(String(128), nullable=False)
    from_table = Column(String(256), nullable=False)
    from_column = Column(String(256), nullable=False)
    to_schema = Column(String(128), nullable=False)
    to_table = Column(String(256), nullable=False)
    to_column = Column(String(256), nullable=False)
    relationship_type = Column(String(32), default="foreign_key")
    confidence = Column(Float, default=1.0)
    last_updated = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "source_db", "from_schema", "from_table", "from_column",
            "to_schema", "to_table", "to_column",
            name="uq_relationship"
        ),
        Index("idx_rel_from", "source_db", "from_schema", "from_table"),
        Index("idx_rel_to", "source_db", "to_schema", "to_table"),
    )


class EnrichmentRecord(Base):
    __tablename__ = "enrichments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    table_id = Column(Integer, ForeignKey("db_tables.id", ondelete="CASCADE"), unique=True)
    table_type = Column(String(32), nullable=True)
    column_roles = Column(JSON, default=dict)
    description = Column(Text, nullable=True)
    tags = Column(JSON, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
