"""
MetadataService — CRUD operations against PostgreSQL metadata store.
Postgres is the source of truth. Graph + embeddings are derived.
"""
from typing import List, Optional, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from db.orm_models import DBTableRecord, DBColumnRecord, DBRelationshipRecord, EnrichmentRecord
from models.unified import NormalizedTable, NormalizedRelationship


class MetadataService:

    async def upsert_table(
        self, session: AsyncSession, table: NormalizedTable
    ) -> DBTableRecord:
        """Upsert table record. Returns ORM record."""
        stmt = (
            pg_insert(DBTableRecord)
            .values(
                source_db=table.source_db,
                source_type=table.source_type,
                schema_name=table.schema_name,
                table_name=table.table_name,
                table_type=table.table_type.value,
                description=table.description,
                tags=table.tags,
                metadata_hash=table.metadata_hash,
                row_count=table.row_count,
                enriched=False,
                embedding_updated=False,
            )
            .on_conflict_do_update(
                constraint="uq_table",
                set_=dict(
                    table_type=pg_insert(DBTableRecord).excluded.table_type,
                    metadata_hash=pg_insert(DBTableRecord).excluded.metadata_hash,
                    row_count=pg_insert(DBTableRecord).excluded.row_count,
                    embedding_updated=False,
                ),
            )
            .returning(DBTableRecord)
        )
        result = await session.execute(stmt)
        record = result.scalar_one()

        # Upsert columns
        await session.execute(
            delete(DBColumnRecord).where(DBColumnRecord.table_id == record.id)
        )
        for col in table.columns:
            session.add(DBColumnRecord(
                table_id=record.id,
                name=col.name,
                data_type=col.data_type,
                is_nullable=col.is_nullable,
                is_primary_key=col.is_primary_key,
                is_foreign_key=col.is_foreign_key,
                is_sensitive=col.is_sensitive,
                default_value=col.default_value,
                role=col.role.value,
            ))

        return record

    async def get_changed_tables(
        self,
        session: AsyncSession,
        source_db: str,
        current_hashes: Dict[str, str],  # node_id → hash
    ) -> List[str]:
        """
        Return node_ids of tables whose metadata_hash differs from stored.
        This is the core of incremental extraction.
        """
        stmt = select(
            DBTableRecord.schema_name,
            DBTableRecord.table_name,
            DBTableRecord.metadata_hash,
        ).where(DBTableRecord.source_db == source_db)

        rows = (await session.execute(stmt)).all()
        stored = {
            f"{source_db}:{r.schema_name}:{r.table_name}": r.metadata_hash
            for r in rows
        }

        changed = []
        for node_id, new_hash in current_hashes.items():
            if stored.get(node_id) != new_hash:
                changed.append(node_id)

        # Also find deleted tables
        deleted = set(stored.keys()) - set(current_hashes.keys())
        return changed, list(deleted)

    async def upsert_relationship(
        self, session: AsyncSession, rel: NormalizedRelationship
    ):
        stmt = (
            pg_insert(DBRelationshipRecord)
            .values(
                source_db=rel.source_db,
                from_schema=rel.from_schema,
                from_table=rel.from_table,
                from_column=rel.from_column,
                to_schema=rel.to_schema,
                to_table=rel.to_table,
                to_column=rel.to_column,
                relationship_type=rel.relationship_type.value,
                confidence=rel.confidence,
            )
            .on_conflict_do_nothing(constraint="uq_relationship")
        )
        await session.execute(stmt)

    async def get_tables(
        self,
        session: AsyncSession,
        source_db: Optional[str] = None,
        unenriched_only: bool = False,
        embedding_stale_only: bool = False,
    ) -> List[DBTableRecord]:
        stmt = select(DBTableRecord)
        if source_db:
            stmt = stmt.where(DBTableRecord.source_db == source_db)
        if unenriched_only:
            stmt = stmt.where(DBTableRecord.enriched == False)
        if embedding_stale_only:
            stmt = stmt.where(DBTableRecord.embedding_updated == False)
        result = await session.execute(stmt)
        return result.scalars().all()

    async def get_table_with_columns(
        self,
        session: AsyncSession,
        node_id: str,
    ) -> Optional[DBTableRecord]:
        parts = node_id.split(":")
        if len(parts) != 3:
            return None
        source_db, schema, table = parts
        stmt = (
            select(DBTableRecord)
            .where(
                DBTableRecord.source_db == source_db,
                DBTableRecord.schema_name == schema,
                DBTableRecord.table_name == table,
            )
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_relationships(
        self,
        session: AsyncSession,
        source_db: str,
        schema: Optional[str] = None,
        table: Optional[str] = None,
    ) -> List[DBRelationshipRecord]:
        stmt = select(DBRelationshipRecord).where(
            DBRelationshipRecord.source_db == source_db
        )
        if schema:
            stmt = stmt.where(DBRelationshipRecord.from_schema == schema)
        if table:
            stmt = stmt.where(DBRelationshipRecord.from_table == table)
        result = await session.execute(stmt)
        return result.scalars().all()

    async def save_enrichment(
        self,
        session: AsyncSession,
        table_id: int,
        enrichment: dict,
    ):
        stmt = (
            pg_insert(EnrichmentRecord)
            .values(
                table_id=table_id,
                table_type=enrichment.get("table_type"),
                column_roles=enrichment.get("column_roles", {}),
                description=enrichment.get("description"),
                tags=enrichment.get("tags", []),
            )
            .on_conflict_do_update(
                index_elements=["table_id"],
                set_=dict(
                    table_type=enrichment.get("table_type"),
                    column_roles=enrichment.get("column_roles", {}),
                    description=enrichment.get("description"),
                    tags=enrichment.get("tags", []),
                ),
            )
        )
        await session.execute(stmt)
        await session.execute(
            update(DBTableRecord)
            .where(DBTableRecord.id == table_id)
            .values(enriched=True, table_type=enrichment.get("table_type", "unknown"))
        )

    async def mark_embedding_updated(self, session: AsyncSession, table_id: int):
        await session.execute(
            update(DBTableRecord)
            .where(DBTableRecord.id == table_id)
            .values(embedding_updated=True)
        )

    async def delete_table(self, session: AsyncSession, node_id: str):
        parts = node_id.split(":")
        if len(parts) != 3:
            return
        source_db, schema, table = parts
        await session.execute(
            delete(DBTableRecord).where(
                DBTableRecord.source_db == source_db,
                DBTableRecord.schema_name == schema,
                DBTableRecord.table_name == table,
            )
        )


metadata_service = MetadataService()
