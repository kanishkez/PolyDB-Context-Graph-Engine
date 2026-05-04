"""
NetworkX graph builder + reasoning layer
Graph is derived state — Postgres is source of truth.
Supports partial loading, cached traversal, multi-hop.
"""
import networkx as nx
from typing import List, Dict, Optional, Tuple, Any
from models.unified import NormalizedTable, NormalizedRelationship
from config import settings


class ContextGraph:
    """
    In-memory MultiDiGraph over table/column nodes.
    DESIGN: loaded per-source-db or on-demand — never full blindly.
    """

    def __init__(self):
        self._graph: nx.MultiDiGraph = nx.MultiDiGraph()
        self._loaded_sources: set = set()

    # ─── Build ────────────────────────────────────────────────────────────────

    def build_from_tables(
        self,
        tables: List[NormalizedTable],
        relationships: List[NormalizedRelationship],
    ):
        """Full or incremental load from normalized models."""
        for table in tables:
            self._add_table_node(table)

        for rel in relationships:
            self._add_relationship_edge(rel)

    def _add_table_node(self, table: NormalizedTable):
        nid = table.node_id
        self._graph.add_node(
            nid,
            type="table",
            source_db=table.source_db,
            schema=table.schema_name,
            table_name=table.table_name,
            table_type=table.table_type.value,
            columns=[c.name for c in table.columns if not c.is_sensitive],
            column_types={c.name: c.data_type for c in table.columns if not c.is_sensitive},
            description=table.description or "",
            tags=table.tags,
        )

        # Add column sub-nodes (lightweight)
        for col in table.columns:
            if col.is_sensitive:
                continue
            col_nid = f"{nid}.{col.name}"
            self._graph.add_node(
                col_nid,
                type="column",
                table_node=nid,
                data_type=col.data_type,
                role=col.role.value,
                is_pk=col.is_primary_key,
                is_fk=col.is_foreign_key,
            )
            self._graph.add_edge(nid, col_nid, edge_type="has_column")

    def _add_relationship_edge(self, rel: NormalizedRelationship):
        from_nid = f"{rel.source_db}:{rel.from_schema}:{rel.from_table}"
        to_nid = f"{rel.source_db}:{rel.to_schema}:{rel.to_table}"
        if from_nid in self._graph and to_nid in self._graph:
            self._graph.add_edge(
                from_nid,
                to_nid,
                edge_type=rel.relationship_type.value,
                from_column=rel.from_column,
                to_column=rel.to_column,
                confidence=rel.confidence,
                key=rel.edge_id,
            )

    def update_table(self, table: NormalizedTable):
        """Incremental update for a single table node."""
        nid = table.node_id
        if self._graph.has_node(nid):
            # Remove old column sub-nodes
            old_cols = [
                n for n in self._graph.successors(nid)
                if self._graph.nodes[n].get("type") == "column"
            ]
            self._graph.remove_nodes_from(old_cols)
        self._add_table_node(table)

    def remove_table(self, node_id: str):
        if self._graph.has_node(node_id):
            self._graph.remove_node(node_id)

    # ─── Traversal ────────────────────────────────────────────────────────────

    def get_neighbors(
        self,
        node_id: str,
        edge_types: Optional[List[str]] = None,
        max_depth: int = 1,
    ) -> List[str]:
        """Return neighboring table nodes (not columns) up to depth."""
        if node_id not in self._graph:
            return []

        visited = set()
        frontier = {node_id}

        for _ in range(max_depth):
            next_frontier = set()
            for n in frontier:
                for neighbor in nx.all_neighbors(self._graph, n):
                    if self._graph.nodes[neighbor].get("type") != "table":
                        continue
                    if neighbor in visited or neighbor == node_id:
                        continue
                    if edge_types:
                        edges = self._graph.get_edge_data(n, neighbor) or {}
                        if not any(
                            e.get("edge_type") in edge_types for e in edges.values()
                        ):
                            continue
                    next_frontier.add(neighbor)
            visited.update(frontier)
            frontier = next_frontier

        return list(visited - {node_id})

    def find_join_path(
        self,
        from_table: str,
        to_table: str,
        max_hops: int = None,
    ) -> Optional[List[str]]:
        """
        Shortest path between two tables (join discovery).
        Only traverses table nodes, ignores column nodes.
        """
        max_hops = max_hops or settings.MAX_HOP_DEPTH
        if from_table not in self._graph or to_table not in self._graph:
            return None

        # Build table-only subgraph for path finding
        table_nodes = [
            n for n, d in self._graph.nodes(data=True) if d.get("type") == "table"
        ]
        subgraph = self._graph.subgraph(table_nodes)

        try:
            path = nx.shortest_path(subgraph, from_table, to_table)
            if len(path) - 1 <= max_hops:
                return path
        except nx.NetworkXNoPath:
            # Try undirected
            try:
                path = nx.shortest_path(
                    subgraph.to_undirected(), from_table, to_table
                )
                if len(path) - 1 <= max_hops:
                    return path
            except nx.NetworkXNoPath:
                pass
        return None

    def expand_context(
        self,
        node_ids: List[str],
        depth: int = 2,
    ) -> Dict[str, Any]:
        """
        Expand multi-hop context from a set of seed nodes.
        Returns structured dict — never raw graph.
        """
        all_nodes = set(node_ids)
        for nid in node_ids:
            neighbors = self.get_neighbors(nid, max_depth=depth)
            all_nodes.update(neighbors)

        result = {}
        for nid in all_nodes:
            if nid not in self._graph:
                continue
            node_data = dict(self._graph.nodes[nid])
            node_type = node_data.get("type")
            if node_type != "table":
                continue

            # Collect edges to other tables
            edges = []
            for successor in self._graph.successors(nid):
                if self._graph.nodes[successor].get("type") != "table":
                    continue
                edge_data = self._graph.get_edge_data(nid, successor)
                for _, edata in edge_data.items():
                    edges.append({
                        "to": successor,
                        "edge_type": edata.get("edge_type"),
                        "from_col": edata.get("from_column"),
                        "to_col": edata.get("to_column"),
                        "confidence": edata.get("confidence", 1.0),
                    })

            result[nid] = {
                "table": node_data.get("table_name"),
                "schema": node_data.get("schema"),
                "source_db": node_data.get("source_db"),
                "table_type": node_data.get("table_type"),
                "columns": node_data.get("columns", []),
                "description": node_data.get("description", ""),
                "relationships": edges,
            }

        return result

    def get_join_edge_info(self, from_node: str, to_node: str) -> List[Dict]:
        """Return join column info between two adjacent table nodes."""
        edges = self._graph.get_edge_data(from_node, to_node) or {}
        result = []
        for _, edata in edges.items():
            if edata.get("edge_type") != "has_column":
                result.append({
                    "from_column": edata.get("from_column"),
                    "to_column": edata.get("to_column"),
                    "type": edata.get("edge_type"),
                    "confidence": edata.get("confidence", 1.0),
                })
        return result

    def cluster_by_source(self) -> Dict[str, List[str]]:
        """Group table nodes by source_db."""
        clusters: Dict[str, List[str]] = {}
        for nid, data in self._graph.nodes(data=True):
            if data.get("type") == "table":
                src = data.get("source_db", "unknown")
                clusters.setdefault(src, []).append(nid)
        return clusters

    @property
    def table_count(self) -> int:
        return sum(
            1 for _, d in self._graph.nodes(data=True) if d.get("type") == "table"
        )

    @property
    def node_ids(self) -> List[str]:
        return [
            n for n, d in self._graph.nodes(data=True) if d.get("type") == "table"
        ]


# Singleton graph instance (loaded per-app lifecycle)
context_graph = ContextGraph()
