"""initial schema

Revision ID: 0001_initial_schema
Revises: 
Create Date: 2026-05-04
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "db_tables",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_db", sa.String(length=128), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("schema_name", sa.String(length=128), nullable=False),
        sa.Column("table_name", sa.String(length=256), nullable=False),
        sa.Column("table_type", sa.String(length=32), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("metadata_hash", sa.String(length=64), nullable=True),
        sa.Column("last_updated", sa.DateTime(), nullable=True),
        sa.Column("embedding_updated", sa.Boolean(), nullable=True),
        sa.Column("enriched", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_db", "schema_name", "table_name", name="uq_table"),
    )
    op.create_index("idx_table_source", "db_tables", ["source_db"], unique=False)
    op.create_index("idx_table_hash", "db_tables", ["metadata_hash"], unique=False)

    op.create_table(
        "db_columns",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("table_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("data_type", sa.String(length=64), nullable=False),
        sa.Column("is_nullable", sa.Boolean(), nullable=True),
        sa.Column("is_primary_key", sa.Boolean(), nullable=True),
        sa.Column("is_foreign_key", sa.Boolean(), nullable=True),
        sa.Column("is_sensitive", sa.Boolean(), nullable=True),
        sa.Column("default_value", sa.String(length=256), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["table_id"], ["db_tables.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("table_id", "name", name="uq_column"),
    )
    op.create_index("idx_col_table", "db_columns", ["table_id"], unique=False)

    op.create_table(
        "db_relationships",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_db", sa.String(length=128), nullable=False),
        sa.Column("from_schema", sa.String(length=128), nullable=False),
        sa.Column("from_table", sa.String(length=256), nullable=False),
        sa.Column("from_column", sa.String(length=256), nullable=False),
        sa.Column("to_schema", sa.String(length=128), nullable=False),
        sa.Column("to_table", sa.String(length=256), nullable=False),
        sa.Column("to_column", sa.String(length=256), nullable=False),
        sa.Column("relationship_type", sa.String(length=32), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("last_updated", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_db",
            "from_schema",
            "from_table",
            "from_column",
            "to_schema",
            "to_table",
            "to_column",
            name="uq_relationship",
        ),
    )
    op.create_index("idx_rel_from", "db_relationships", ["source_db", "from_schema", "from_table"], unique=False)
    op.create_index("idx_rel_to", "db_relationships", ["source_db", "to_schema", "to_table"], unique=False)

    op.create_table(
        "enrichments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("table_id", sa.Integer(), nullable=True),
        sa.Column("table_type", sa.String(length=32), nullable=True),
        sa.Column("column_roles", sa.JSON(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["table_id"], ["db_tables.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("table_id"),
    )


def downgrade() -> None:
    op.drop_table("enrichments")
    op.drop_index("idx_rel_to", table_name="db_relationships")
    op.drop_index("idx_rel_from", table_name="db_relationships")
    op.drop_table("db_relationships")
    op.drop_index("idx_col_table", table_name="db_columns")
    op.drop_table("db_columns")
    op.drop_index("idx_table_hash", table_name="db_tables")
    op.drop_index("idx_table_source", table_name="db_tables")
    op.drop_table("db_tables")
