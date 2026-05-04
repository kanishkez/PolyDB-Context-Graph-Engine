"""
Background workers — extraction, enrichment, embedding generation.
All incremental: only processes changed data.
"""
import asyncio
import json
import logging
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from connectors.factory import get_connector
from graph.inference import infer_relationships
from models.unified import NormalizedTable
from services.metadata_service import metadata_service
from services.graph_service import graph_service
from embeddings.faiss_store import embedding_store
from services.llm_service import llm_service
from cache.cache_service import cache_service
from config import settings
from db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def run_extraction(db_config: dict):
    """
    Incremental extraction pipeline for a single database.
    Only processes changed tables.
    """
    connector = get_connector(db_config)
    source_db = db_config["name"]

    logger.info(f"[extraction] Starting for {source_db}")

    if not await connector.test_connection():
        logger.error(f"[extraction] Cannot connect to {source_db}")
        return

    # Extract all metadata from source
    tables = await connector.extract_tables()
    relationships = await connector.extract_relationships()

    # Infer additional relationships
    inferred = infer_relationships(tables)
    all_relationships = relationships + inferred

    # Build hash map for change detection
    current_hashes = {t.node_id: t.metadata_hash for t in tables}

    async with AsyncSessionLocal() as session:
        changed_ids, deleted_ids = await metadata_service.get_changed_tables(
            session, source_db, current_hashes
        )

        logger.info(
            f"[extraction] {source_db}: {len(changed_ids)} changed, "
            f"{len(deleted_ids)} deleted out of {len(tables)} total"
        )

        # Process only changed tables
        changed_set = set(changed_ids)
        changed_tables = [t for t in tables if t.node_id in changed_set]

        for table in changed_tables:
            record = await metadata_service.upsert_table(session, table)
            graph_service.update_table_in_graph(table)
            cache_service.invalidate_table(table.node_id)

        # Persist all relationships (upsert idempotent)
        for rel in all_relationships:
            await metadata_service.upsert_relationship(session, rel)
            graph_service.add_relationship_to_graph(rel)

        # Handle deletions
        for node_id in deleted_ids:
            await metadata_service.delete_table(session, node_id)
            graph_service.graph.remove_table(node_id)

        await session.commit()

    logger.info(f"[extraction] {source_db}: complete")


async def run_enrichment():
    """
    Offline LLM enrichment for unenriched tables.
    Batched — minimizes Gemini calls.
    """
    async with AsyncSessionLocal() as session:
        tables = await metadata_service.get_tables(
            session, unenriched_only=True
        )

    logger.info(f"[enrichment] Processing {len(tables)} unenriched tables")

    batch_size = settings.ENRICHMENT_BATCH_SIZE
    for i in range(0, len(tables), batch_size):
        batch = tables[i:i + batch_size]

        async with AsyncSessionLocal() as session:
            for table_rec in batch:
                # Get columns
                from sqlalchemy import select
                from db.orm_models import DBColumnRecord
                col_result = await session.execute(
                    select(DBColumnRecord).where(DBColumnRecord.table_id == table_rec.id)
                )
                columns = [
                    {"name": c.name, "type": c.data_type}
                    for c in col_result.scalars().all()
                    if not c.is_sensitive
                ]

                try:
                    enrichment = await llm_service.enrich_table(
                        table_name=table_rec.table_name,
                        schema_name=table_rec.schema_name,
                        columns=columns,
                    )
                    await metadata_service.save_enrichment(
                        session, table_rec.id, enrichment
                    )
                    logger.info(
                        f"[enrichment] Enriched {table_rec.source_db}."
                        f"{table_rec.schema_name}.{table_rec.table_name}"
                    )
                except Exception as e:
                    logger.error(f"[enrichment] Failed {table_rec.table_name}: {e}")

            await session.commit()

        await asyncio.sleep(0.5)  # rate limit buffer


async def run_embedding_update():
    """
    Update FAISS embeddings for tables with stale embeddings.
    Incremental — only tables where embedding_updated=False.
    """
    async with AsyncSessionLocal() as session:
        tables = await metadata_service.get_tables(
            session, embedding_stale_only=True
        )
        all_tables = await metadata_service.get_tables(session)

    if not tables:
        logger.info("[embeddings] All embeddings up to date")
        return

    logger.info(f"[embeddings] Updating {len(tables)} table embeddings")

    # Build items for batch upsert
    items = []
    for rec in all_tables:
        node_id = rec.node_id
        # Get graph node data for rich embedding
        graph_data = graph_service.graph._graph.nodes.get(node_id, {})
        if not graph_data:
            continue
        items.append((node_id, graph_data))

    if items:
        embedding_store.batch_upsert(items)
        embedding_store.save()

    # Mark as updated
    async with AsyncSessionLocal() as session:
        for rec in tables:
            await metadata_service.mark_embedding_updated(session, rec.id)
        await session.commit()

    logger.info("[embeddings] Update complete")


async def run_all_sources():
    """Run extraction for all configured databases."""
    db_configs = json.loads(settings.TARGET_DATABASES)
    tasks = [run_extraction(cfg) for cfg in db_configs]
    await asyncio.gather(*tasks, return_exceptions=True)


async def periodic_refresh(interval_seconds: int = 3600):
    """Periodic background refresh loop."""
    while True:
        try:
            await run_all_sources()
            await run_enrichment()
            await run_embedding_update()
        except Exception as e:
            logger.error(f"[periodic_refresh] Error: {e}")
        await asyncio.sleep(interval_seconds)
