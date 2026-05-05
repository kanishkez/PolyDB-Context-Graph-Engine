"""
FastAPI routes — low-level and high-level endpoints
"""
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from db.session import get_db
from services.smart_query_service import smart_query_service
from services.graph_service import graph_service
from mcp.tools import mcp_executor, MCP_TOOLS
from mcp.agent_loop import agent_loop
from workers.extraction_worker import run_all_sources, run_enrichment, run_embedding_update
from cache.cache_service import cache_service
from config import settings
from services.llm_service import llm_service as service_llm
import json
from services.embedding_service import embedding_service

router = APIRouter()


# ─── Request models ───────────────────────────────────────────────────────────

class SmartQueryRequest(BaseModel):
    query: str
    user_id: Optional[str] = None
    top_k: int = 5
    skip_llm: bool = False


class MCPToolRequest(BaseModel):
    tool_name: str
    tool_input: dict


class AgentRequest(BaseModel):
    query: str
    user_id: Optional[str] = None


class ExtractionTriggerRequest(BaseModel):
    source_db: Optional[str] = None  # None = all


class SuggestQueryRequest(BaseModel):
    node_id: str
    intent: str
    user_id: Optional[str] = None


class ExplainTableRequest(BaseModel):
    node_id: str
    user_id: Optional[str] = None


# ─── Health ───────────────────────────────────────────────────────────────────

@router.get("/health")
async def health():
    stats = graph_service.graph_stats
    return {
        "status": "ok",
        "graph": stats,
        "embeddings": {
            "total_vectors": embedding_service.total_vectors,
        },
        "cache": {
            "query_cache_size": cache_service.query_cache.size(),
            "context_cache_size": cache_service.context_cache.size(),
        },
    }


# ─── LOW LEVEL ENDPOINTS ──────────────────────────────────────────────────────

@router.get("/search")
async def search_tables(
    q: str = Query(..., description="Search query"),
    top_k: int = Query(default=10, ge=1, le=50),
    user_id: Optional[str] = Query(default=None),
):
    """Semantic table search — no LLM."""
    results = await smart_query_service.search_tables(q, top_k, user_id)
    return {"query": q, "results": results, "count": len(results)}


@router.get("/context/{node_id:path}")
async def get_table_context(
    node_id: str,
    user_id: Optional[str] = Query(default=None),
):
    """Get expanded context for a table including relationships."""
    context = await smart_query_service.get_table_context(node_id, user_id)
    if not context:
        raise HTTPException(status_code=404, detail=f"Table not found: {node_id}")
    return context


@router.get("/relationships/{node_id:path}")
async def get_relationships(
    node_id: str,
    user_id: Optional[str] = Query(default=None),
):
    """Get direct relationships for a table."""
    return await smart_query_service.get_relationships(node_id, user_id)


@router.get("/join-path")
async def find_join_path(
    from_table: str = Query(...),
    to_table: str = Query(...),
    user_id: Optional[str] = Query(default=None),
):
    """Discover join path between two tables."""
    return await smart_query_service.find_join_path(from_table, to_table, user_id)


@router.get("/graph/stats")
async def graph_stats():
    """Graph statistics."""
    return graph_service.graph_stats


@router.get("/graph/clusters")
async def graph_clusters():
    """Relationship clusters + source grouping snapshot."""
    return {
        "clusters": graph_service.cluster_relationships(),
        "by_source": graph_service.graph.cluster_by_source(),
    }


@router.get("/graph/clusters/relationships")
async def graph_relationship_clusters():
    """Connected-component style table clusters from relationship graph only."""
    return {"clusters": graph_service.cluster_relationships()}


@router.get("/graph/hubs")
async def graph_hubs(top_k: int = Query(default=10, ge=1, le=100)):
    """Most highly connected table nodes in the graph."""
    return {"hubs": graph_service.get_highly_connected_tables(top_k=top_k)}


@router.get("/stats")
async def system_stats():
    """Combined service stats snapshot."""
    return {
        "graph": graph_service.graph_stats,
        "embeddings": {"total_vectors": embedding_service.total_vectors},
        "cache": {
            "query_cache_size": cache_service.query_cache.size(),
            "context_cache_size": cache_service.context_cache.size(),
            "embedding_cache_size": cache_service.embedding_cache.size(),
        },
    }


# ─── HIGH LEVEL ENDPOINT ──────────────────────────────────────────────────────

@router.post("/smart_query")
async def smart_query(req: SmartQueryRequest):
    """
    PRIMARY ENDPOINT.
    Single call: semantic search + graph reasoning + LLM answer.
    """
    result = await smart_query_service.smart_query(
        req.query,
        req.user_id,
        req.top_k,
        req.skip_llm,
    )
    return result


@router.post("/suggest_query")
async def suggest_query(req: SuggestQueryRequest):
    """Generate a SQL query suggestion for a table + intent."""
    context = await smart_query_service.get_table_context(req.node_id, req.user_id)
    if not context or context.get("error"):
        raise HTTPException(status_code=404, detail=f"Table not found or inaccessible: {req.node_id}")
    sql = await service_llm.suggest_query(context, req.intent)
    return {"node_id": req.node_id, "intent": req.intent, "sql": sql}


@router.post("/explain_table")
async def explain_table(req: ExplainTableRequest):
    """Plain-language explanation of table purpose and usage."""
    context = await smart_query_service.get_table_context(req.node_id, req.user_id)
    if not context or context.get("error"):
        raise HTTPException(status_code=404, detail=f"Table not found or inaccessible: {req.node_id}")
    explanation = await service_llm.explain_table(req.node_id, context)
    return {"node_id": req.node_id, "explanation": explanation}


# ─── MCP TOOL ENDPOINTS ───────────────────────────────────────────────────────

@router.get("/mcp/tools")
async def list_mcp_tools():
    """List all available MCP tools."""
    return {"tools": MCP_TOOLS}


@router.post("/mcp/call")
async def call_mcp_tool(req: MCPToolRequest):
    """Execute a single MCP tool call."""
    result = await mcp_executor.execute(req.tool_name, req.tool_input)
    return result


@router.post("/mcp/agent")
async def run_agent(req: AgentRequest):
    """
    Run the full agent loop.
    LLM decides which tools to call, iterates, returns final answer.
    """
    result = await agent_loop.run(req.query, req.user_id)
    return result


# ─── ADMIN / WORKER ENDPOINTS ─────────────────────────────────────────────────

@router.post("/admin/extract")
async def trigger_extraction(
    req: ExtractionTriggerRequest,
    background_tasks: BackgroundTasks,
):
    """Trigger incremental metadata extraction (background)."""
    if req.source_db:
        db_configs = json.loads(settings.TARGET_DATABASES)
        cfg = next((c for c in db_configs if c["name"] == req.source_db), None)
        if not cfg:
            raise HTTPException(status_code=404, detail=f"DB not found: {req.source_db}")
        from workers.extraction_worker import run_extraction
        background_tasks.add_task(run_extraction, cfg)
    else:
        background_tasks.add_task(run_all_sources)
    return {"status": "triggered", "source_db": req.source_db or "all"}


@router.post("/admin/enrich")
async def trigger_enrichment(background_tasks: BackgroundTasks):
    """Trigger offline LLM enrichment for unenriched tables."""
    background_tasks.add_task(run_enrichment)
    return {"status": "triggered"}


@router.post("/admin/embeddings")
async def trigger_embedding_update(background_tasks: BackgroundTasks):
    """Trigger embedding update for stale tables."""
    background_tasks.add_task(run_embedding_update)
    return {"status": "triggered"}


@router.delete("/admin/cache")
async def clear_cache():
    """Clear all caches."""
    cache_service.query_cache.clear()
    cache_service.context_cache.clear()
    cache_service.embedding_cache.clear()
    return {"status": "cleared"}
