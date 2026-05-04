"""
Trino metadata connector
"""
import hashlib
import json
from typing import List
import aiohttp
from connectors.base import BaseConnector
from models.unified import (
    NormalizedTable, NormalizedColumn, NormalizedRelationship,
    RelationshipType
)
from config import settings


class TrinoConnector(BaseConnector):
    """
    Uses Trino REST API to fetch metadata.
    Trino doesn't natively expose FKs so we rely on inference.
    """

    def _base_url(self) -> str:
        cfg = self.config
        host = cfg.get("host", "localhost")
        port = cfg.get("port", 8080)
        return f"http://{host}:{port}/v1"

    def _headers(self) -> dict:
        cfg = self.config
        return {
            "X-Trino-User": cfg.get("user", "trino"),
            "X-Trino-Catalog": cfg.get("catalog", "hive"),
            "X-Trino-Schema": cfg.get("schema", "default"),
        }

    async def _run_query(self, sql: str) -> List[dict]:
        """Execute a Trino query via REST API (simplified polling)."""
        async with aiohttp.ClientSession() as session:
            headers = {**self._headers(), "Content-Type": "application/json"}
            async with session.post(
                f"{self._base_url()}/statement",
                data=sql,
                headers=headers,
            ) as resp:
                data = await resp.json()

            rows = []
            next_uri = data.get("nextUri")
            columns = [c["name"] for c in data.get("columns", [])]
            if data.get("data"):
                rows.extend([dict(zip(columns, r)) for r in data["data"]])

            while next_uri:
                async with session.get(next_uri, headers=self._headers()) as resp:
                    data = await resp.json()
                if data.get("data"):
                    rows.extend([dict(zip(columns, r)) for r in data["data"]])
                next_uri = data.get("nextUri")
                if data.get("stats", {}).get("state") in ("FINISHED", "FAILED"):
                    break

            return rows

    async def test_connection(self) -> bool:
        try:
            await self._run_query("SELECT 1")
            return True
        except Exception:
            return False

    async def extract_tables(self) -> List[NormalizedTable]:
        catalog = self.config.get("catalog", "hive")
        schema = self.config.get("schema", "default")

        table_rows = await self._run_query(
            f"SHOW TABLES FROM {catalog}.{schema}"
        )

        tables = []
        for row in table_rows:
            tname = list(row.values())[0]

            col_rows = await self._run_query(
                f"DESCRIBE {catalog}.{schema}.{tname}"
            )

            columns = []
            for c in col_rows:
                col_name = c.get("Column", c.get("column", "")).lower()
                dtype = c.get("Type", c.get("type", "unknown"))
                is_sensitive = any(
                    pat in col_name for pat in settings.SENSITIVE_COLUMN_PATTERNS
                )
                columns.append(NormalizedColumn(
                    name=col_name,
                    data_type=dtype,
                    is_nullable=True,
                    is_sensitive=is_sensitive,
                ))

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

    async def extract_relationships(self) -> List[NormalizedRelationship]:
        # Trino has no native FK support — relationships come from inference only
        return []
