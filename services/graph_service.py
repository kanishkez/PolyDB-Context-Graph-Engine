"""
GraphService — orchestrates graph loading, updates, and traversal queries.
Wraps ContextGraph with DB-backed initialization and incremental updates.
"""
from collections import defaultdict
from typing import List, Optional, Dict, Any, Tuple
import networkx as nx
from sqlalchemy.ext.asyncio import AsyncSession
from graph.context_graph import context_graph, ContextGraph
from graph.inference import infer_relationships
from models.unified import NormalizedTable, NormalizedRelationship, RelationshipType
from db.orm_models import DBTableRecord, DBColumnRecord, DBRelationshipRecord
from models.unified import ColumnRole, TableType
from sqlalchemy import select


class GraphService:

    def __init__(self):
        self.graph = context_graph

    async def initialize_from_db(self, session: AsyncSession):
        """
        Load full graph from Postgres on startup.
        Called once; incremental updates after that.
        """
        # Load all tables
        result = await session.execute(select(DBTableRecord))
        table_records = result.scalars().all()

        tables = []
        for rec in table_records:
            col_result = await session.execute(
                select(DBColumnRecord).where(DBColumnRecord.table_id == rec.id)
            )
            col_records = col_result.scalars().all()

            from models.unified import NormalizedColumn
            columns = [
                NormalizedColumn(
                    name=c.name,
                    data_type=c.data_type,
                    is_nullable=c.is_nullable,
                    is_primary_key=c.is_primary_key,
                    is_foreign_key=c.is_foreign_key,
                    is_sensitive=c.is_sensitive,
                    role=ColumnRole(c.role),
                )
                for c in col_records
            ]

            tables.append(NormalizedTable(
                source_db=rec.source_db,
                source_type=rec.source_type,
                schema_name=rec.schema_name,
                table_name=rec.table_name,
                columns=columns,
                table_type=TableType(rec.table_type) if rec.table_type else TableType.UNKNOWN,
                description=rec.description or "",
                tags=rec.tags or [],
                metadata_hash=rec.metadata_hash,
            ))

        # Load relationships
        rel_result = await session.execute(select(DBRelationshipRecord))
        rel_records = rel_result.scalars().all()
        relationships = [
            NormalizedRelationship(
                source_db=r.source_db,
                from_schema=r.from_schema,
                from_table=r.from_table,
                from_column=r.from_column,
                to_schema=r.to_schema,
                to_table=r.to_table,
                to_column=r.to_column,
                relationship_type=RelationshipType(r.relationship_type),
                confidence=r.confidence,
            )
            for r in rel_records
        ]

        self.graph.build_from_tables(tables, relationships)

    def get_neighbors(
        self,
        node_id: str,
        edge_types: Optional[List[str]] = None,
        depth: int = 1,
    ) -> List[str]:
        return self.graph.get_neighbors(node_id, edge_types=edge_types, max_depth=depth)

    def find_join_path(
        self,
        from_table: str,
        to_table: str,
    ) -> Optional[List[str]]:
        return self.graph.find_join_path(from_table, to_table)

    def expand_context(
        self,
        node_ids: List[str],
        depth: int = 2,
    ) -> Dict[str, Any]:
        return self.graph.expand_context(node_ids, depth=depth)

    def get_join_details(
        self,
        path: List[str],
    ) -> List[Dict[str, Any]]:
        """Given a path of table node_ids, return join column info for each hop."""
        details = []
        for i in range(len(path) - 1):
            edge_info = self.graph.get_join_edge_info(path[i], path[i + 1])
            details.append({
                "from": path[i],
                "to": path[i + 1],
                "join_conditions": edge_info,
            })
        return details

    def update_table_in_graph(self, table: NormalizedTable):
        self.graph.update_table(table)

    def add_relationship_to_graph(self, rel: NormalizedRelationship):
        self.graph._add_relationship_edge(rel)

    def cluster_relationships(self, min_component_size: int = 1) -> List[Dict[str, Any]]:
        """
        Cluster table nodes by connected components across relationship edges.
        Useful to inspect isolated domains and tightly-coupled table groups.
        """
        table_nodes = [
            n for n, d in self.graph._graph.nodes(data=True)
            if d.get("type") == "table"
        ]
        if not table_nodes:
            return []

        subgraph = self.graph._graph.subgraph(table_nodes).to_undirected()
        clusters: List[Dict[str, Any]] = []
        for component in nx.connected_components(subgraph):
            nodes = sorted(component)
            if len(nodes) < min_component_size:
                continue

            by_source = defaultdict(int)
            for node in nodes:
                src = node.split(":")[0] if ":" in node else "unknown"
                by_source[src] += 1

            clusters.append({
                "size": len(nodes),
                "nodes": nodes,
                "source_breakdown": dict(by_source),
            })

        clusters.sort(key=lambda c: c["size"], reverse=True)
        return clusters

    @property
    def graph_stats(self) -> Dict[str, int]:
        return {
            "tables": self.graph.table_count,
            "nodes": self.graph._graph.number_of_nodes(),
            "edges": self.graph._graph.number_of_edges(),
        }


graph_service = GraphService()
