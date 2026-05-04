"""
PostgreSQL metadata connector
"""
import hashlib
import json
from typing import List, Optional
import asyncpg
from connectors.base import BaseConnector
from models.unified import (
    NormalizedTable, NormalizedColumn, NormalizedRelationship,
    RelationshipType
)
from config import settings


class PostgreSQLConnector(BaseConnector):

    async def _get_conn(self):
        cfg = self.config
        return await asyncpg.connect(
            host=cfg.get("host", "localhost"),
            port=cfg.get("port", 5432),
            user=cfg["user"],
            password=cfg["password"],
            database=cfg["database"],
        )

    async def test_connection(self) -> bool:
        try:
            conn = await self._get_conn()
            await conn.fetchval("SELECT 1")
            await conn.close()
            return True
        except Exception:
            return False

    async def extract_tables(self) -> List[NormalizedTable]:
        conn = await self._get_conn()
        try:
            excluded = tuple(settings.EXCLUDED_SCHEMAS)

            # Get all tables/views excluding system schemas
            table_rows = await conn.fetch("""
                SELECT table_schema, table_name, table_type
                FROM information_schema.tables
                WHERE table_schema <> ALL($1::text[])
                  AND table_type IN ('BASE TABLE', 'VIEW')
                ORDER BY table_schema, table_name
            """, excluded)

            tables = []
            for row in table_rows:
                schema = row["table_schema"]
                tname = row["table_name"]

                # Fetch columns
                col_rows = await conn.fetch("""
                    SELECT
                        c.column_name, c.data_type, c.is_nullable,
                        c.column_default,
                        CASE WHEN pk.column_name IS NOT NULL THEN true ELSE false END AS is_pk,
                        CASE WHEN fk.column_name IS NOT NULL THEN true ELSE false END AS is_fk
                    FROM information_schema.columns c
                    LEFT JOIN (
                        SELECT ku.column_name
                        FROM information_schema.table_constraints tc
                        JOIN information_schema.key_column_usage ku
                          ON tc.constraint_name = ku.constraint_name
                         AND tc.table_schema = ku.table_schema
                        WHERE tc.constraint_type = 'PRIMARY KEY'
                          AND tc.table_schema = $1 AND tc.table_name = $2
                    ) pk ON pk.column_name = c.column_name
                    LEFT JOIN (
                        SELECT ku.column_name
                        FROM information_schema.table_constraints tc
                        JOIN information_schema.key_column_usage ku
                          ON tc.constraint_name = ku.constraint_name
                         AND tc.table_schema = ku.table_schema
                        WHERE tc.constraint_type = 'FOREIGN KEY'
                          AND tc.table_schema = $1 AND tc.table_name = $2
                    ) fk ON fk.column_name = c.column_name
                    WHERE c.table_schema = $1 AND c.table_name = $2
                    ORDER BY c.ordinal_position
                """, schema, tname)

                columns = []
                for c in col_rows:
                    col_name = c["column_name"].lower()
                    is_sensitive = any(
                        pat in col_name for pat in settings.SENSITIVE_COLUMN_PATTERNS
                    )
                    columns.append(NormalizedColumn(
                        name=c["column_name"],
                        data_type=c["data_type"],
                        is_nullable=(c["is_nullable"] == "YES"),
                        is_primary_key=c["is_pk"],
                        is_foreign_key=c["is_fk"],
                        default_value=str(c["column_default"]) if c["column_default"] else None,
                        is_sensitive=is_sensitive,
                    ))

                # Build hash for change detection
                col_sig = json.dumps(
                    [(c.name, c.data_type) for c in columns], sort_keys=True
                )
                metadata_hash = hashlib.sha256(col_sig.encode()).hexdigest()[:16]

                tables.append(NormalizedTable(
                    source_db=self.source_db,
                    source_type=self.source_type,
                    schema_name=schema,
                    table_name=tname,
                    columns=columns,
                    metadata_hash=metadata_hash,
                ))

            return tables
        finally:
            await conn.close()

    async def extract_relationships(self) -> List[NormalizedRelationship]:
        conn = await self._get_conn()
        try:
            excluded = tuple(settings.EXCLUDED_SCHEMAS)
            rows = await conn.fetch("""
                SELECT
                    tc.table_schema AS from_schema,
                    tc.table_name AS from_table,
                    kcu.column_name AS from_column,
                    ccu.table_schema AS to_schema,
                    ccu.table_name AS to_table,
                    ccu.column_name AS to_column
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage ccu
                  ON ccu.constraint_name = tc.constraint_name
                WHERE tc.constraint_type = 'FOREIGN KEY'
                  AND tc.table_schema <> ALL($1::text[])
            """, excluded)

            return [
                NormalizedRelationship(
                    source_db=self.source_db,
                    from_schema=r["from_schema"],
                    from_table=r["from_table"],
                    from_column=r["from_column"],
                    to_schema=r["to_schema"],
                    to_table=r["to_table"],
                    to_column=r["to_column"],
                    relationship_type=RelationshipType.FOREIGN_KEY,
                    confidence=1.0,
                )
                for r in rows
            ]
        finally:
            await conn.close()
