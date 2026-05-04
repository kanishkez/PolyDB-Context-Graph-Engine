"""
SmartQueryService — the core orchestrator.
Single call path: embed search → graph expansion → join discovery → LLM reasoning.
Minimizes LLM calls. Uses cache aggressively.
"""
import time
from typing import Optional, Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from embeddings.faiss_store import embedding_store
from services.graph_service import graph_service
from services.llm_service import llm_service
from cache.cache_service import cache_service
from security.security_service import security_service
from config import settings


class SmartQueryService:

    async def smart_query(
        self,
        query: str,
        user_id: Optional[str] = None,
        top_k: int = 5,
        skip_llm: bool = False,
    ) -> Dict[str, Any]:
        """
        Primary query interface.
        Steps:
        1. Check cache
        2. Embedding search (top-k tables)
        3. Security filter
        4. Graph expansion (multi-hop)
        5. Join path discovery
        6. Assemble structured context
        7. ONE Gemini call
        8. Cache + return
        """
        start = time.perf_counter()

        # Step 1: Cache check
        cached = cache_service.get_query(query, user_id)
        if cached:
            cached["cached"] = True
            return cached

        # Step 2: Embedding search
        search_cached = cache_service.get_search(query, top_k)
        if search_cached:
            top_tables = search_cached
        else:
            top_tables = embedding_store.search(query, top_k=top_k)
            cache_service.set_search(query, top_k, top_tables)

        if not top_tables:
            return {
                "query": query,
                "matched_tables": [],
                "context": {},
                "reasoning": "No relevant tables found in the database catalog.",
                "suggested_joins": [],
                "confidence": 0.0,
                "cached": False,
                "elapsed_ms": int((time.perf_counter() - start) * 1000),
            }

        # Step 3: Security filter
        node_ids = [nid for nid, _ in top_tables]
        node_ids = security_service.filter_table_list(node_ids, user_id)
        scores = {nid: score for nid, score in top_tables}

        # Step 4: Graph expansion
        ctx_cached = None
        context_key = "|".join(sorted(node_ids))
        ctx_cached = cache_service.get_context(context_key)
        if ctx_cached:
            context = ctx_cached
        else:
            context = graph_service.expand_context(node_ids, depth=2)
            context = security_service.filter_context(context, user_id)
            cache_service.set_context(context_key, context)

        # Step 5: Join path discovery (between top 2 tables if different)
        suggested_joins = []
        if len(node_ids) >= 2:
            path = graph_service.find_join_path(node_ids[0], node_ids[1])
            if path and len(path) > 1:
                details = graph_service.get_join_details(path)
                suggested_joins = [
                    f"{d['from'].split(':')[-1]} JOIN {d['to'].split(':')[-1]} "
                    f"ON {d['join_conditions'][0]['from_column'] if d['join_conditions'] else '?'} = "
                    f"{d['join_conditions'][0]['to_column'] if d['join_conditions'] else '?'}"
                    for d in details
                    if d["join_conditions"]
                ]

        # Step 6: Assemble structured context
        structured_context = {
            "query": query,
            "matched_tables": [
                {
                    "node_id": nid,
                    "relevance_score": round(scores.get(nid, 0.0), 3),
                    **context.get(nid, {}),
                }
                for nid in node_ids
                if nid in context
            ],
            "join_paths": suggested_joins,
        }

        # Step 7: LLM reasoning (single call, only if not skipped)
        if skip_llm:
            reasoning = "LLM reasoning skipped (fast mode)"
            confidence = scores.get(node_ids[0], 0.0) if node_ids else 0.0
        else:
            reasoning = await llm_service.reason(query, structured_context)
            confidence = scores.get(node_ids[0], 0.0) if node_ids else 0.0

        result = {
            "query": query,
            "matched_tables": node_ids,
            "context": structured_context,
            "reasoning": reasoning,
            "suggested_joins": suggested_joins,
            "confidence": round(confidence, 3),
            "cached": False,
            "elapsed_ms": int((time.perf_counter() - start) * 1000),
        }

        # Step 8: Cache result
        cache_service.set_query(query, result, user_id)

        return result

    async def get_table_context(
        self,
        node_id: str,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get expanded context for a single table."""
        if not security_service.can_access_db(user_id, node_id.split(":")[0]):
            return {"error": "Access denied"}

        cached = cache_service.get_context(node_id)
        if cached:
            return cached

        context = graph_service.expand_context([node_id], depth=2)
        context = security_service.filter_context(context, user_id)
        cache_service.set_context(node_id, context)
        return context

    async def search_tables(
        self,
        query: str,
        top_k: int = 10,
        user_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fast semantic search — no LLM."""
        results = embedding_store.search(query, top_k=top_k)
        node_ids = [nid for nid, _ in results]
        node_ids = security_service.filter_table_list(node_ids, user_id)
        scores = {nid: score for nid, score in results}

        return [
            {"node_id": nid, "score": round(scores[nid], 3)}
            for nid in node_ids
        ]

    async def get_relationships(
        self,
        node_id: str,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get direct relationships for a table node."""
        neighbors = graph_service.get_neighbors(node_id, depth=1)
        neighbors = security_service.filter_table_list(neighbors, user_id)

        result = {"table": node_id, "relationships": []}
        for n in neighbors:
            edge_info = graph_service.graph.get_join_edge_info(node_id, n)
            result["relationships"].append({
                "related_table": n,
                "join_info": edge_info,
            })
        return result

    async def find_join_path(
        self,
        from_table: str,
        to_table: str,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Discover join path between two tables — pure graph, no LLM."""
        if not security_service.can_access_db(user_id, from_table.split(":")[0]):
            return {"error": "Access denied"}

        path = graph_service.find_join_path(from_table, to_table)
        if not path:
            return {"from": from_table, "to": to_table, "path": None, "found": False}

        details = graph_service.get_join_details(path)
        return {
            "from": from_table,
            "to": to_table,
            "path": path,
            "hops": len(path) - 1,
            "join_details": details,
            "found": True,
        }


smart_query_service = SmartQueryService()
