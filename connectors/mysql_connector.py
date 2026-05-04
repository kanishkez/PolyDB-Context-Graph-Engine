"""
MySQL metadata connector
"""
import hashlib
import json
from typing import List
import aiomysql
from connectors.base import BaseConnector
from models.unified import (
    NormalizedTable, NormalizedColumn, NormalizedRelationship,
    RelationshipType
)
from config import settings


class MySQLConnector(BaseConnector):

    async def _get_conn(self):
        cfg = self.config
        return await aiomysql.connect(
            host=cfg.get("host", "localhost"),
            port=cfg.get("port", 3306),
            user=cfg["user"],
            password=cfg["password"],
            db=cfg["database"],
            autocommit=True,
        )

    async def test_connection(self) -> bool:
        try:
            conn = await self._get_conn()
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1")
            conn.close()
            return True
        except Exception:
            return False

    async def extract_tables(self) -> List[NormalizedTable]:
        conn = await self._get_conn()
        try:
            excluded = settings.EXCLUDED_SCHEMAS
            database = self.config["database"]

            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute("""
                    SELECT TABLE_NAME, TABLE_TYPE
                    FROM information_schema.TABLES
                    WHERE TABLE_SCHEMA = %s
                      AND TABLE_TYPE IN ('BASE TABLE', 'VIEW')
                """, (database,))
                table_rows = await cur.fetchall()

            tables = []
            for row in table_rows:
                tname = row["TABLE_NAME"]

                async with conn.cursor(aiomysql.DictCursor) as cur:
                    await cur.execute("""
                        SELECT
                            COLUMN_NAME, DATA_TYPE, IS_NULLABLE,
                            COLUMN_DEFAULT, COLUMN_KEY
                        FROM information_schema.COLUMNS
                        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
                        ORDER BY ORDINAL_POSITION
                    """, (database, tname))
                    col_rows = await cur.fetchall()

                columns = []
                for c in col_rows:
                    col_name = c["COLUMN_NAME"].lower()
                    is_sensitive = any(
                        pat in col_name for pat in settings.SENSITIVE_COLUMN_PATTERNS
                    )
                    columns.append(NormalizedColumn(
                        name=c["COLUMN_NAME"],
                        data_type=c["DATA_TYPE"],
                        is_nullable=(c["IS_NULLABLE"] == "YES"),
                        is_primary_key=(c["COLUMN_KEY"] == "PRI"),
                        is_foreign_key=(c["COLUMN_KEY"] == "MUL"),
                        default_value=str(c["COLUMN_DEFAULT"]) if c["COLUMN_DEFAULT"] else None,
                        is_sensitive=is_sensitive,
                    ))

                col_sig = json.dumps(
                    [(c.name, c.data_type) for c in columns], sort_keys=True
                )
                metadata_hash = hashlib.sha256(col_sig.encode()).hexdigest()[:16]

                tables.append(NormalizedTable(
                    source_db=self.source_db,
                    source_type=self.source_type,
                    schema_name=database,
                    table_name=tname,
                    columns=columns,
                    metadata_hash=metadata_hash,
                ))

            return tables
        finally:
            conn.close()

    async def extract_relationships(self) -> List[NormalizedRelationship]:
        conn = await self._get_conn()
        try:
            database = self.config["database"]
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute("""
                    SELECT
                        TABLE_NAME AS from_table,
                        COLUMN_NAME AS from_column,
                        REFERENCED_TABLE_NAME AS to_table,
                        REFERENCED_COLUMN_NAME AS to_column
                    FROM information_schema.KEY_COLUMN_USAGE
                    WHERE TABLE_SCHEMA = %s
                      AND REFERENCED_TABLE_NAME IS NOT NULL
                """, (database,))
                rows = await cur.fetchall()

            return [
                NormalizedRelationship(
                    source_db=self.source_db,
                    from_schema=database,
                    from_table=r["from_table"],
                    from_column=r["from_column"],
                    to_schema=database,
                    to_table=r["to_table"],
                    to_column=r["to_column"],
                    relationship_type=RelationshipType.FOREIGN_KEY,
                    confidence=1.0,
                )
                for r in rows
            ]
        finally:
            conn.close()
