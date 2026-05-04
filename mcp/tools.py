"""
MCP Tool Layer — defines tools and maps them to service calls.
Tools are the interface for AI agents (MCP-style).
"""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from services.smart_query_service import smart_query_service


# ─── Tool Input Schemas ───────────────────────────────────────────────────────

class SearchTablesInput(BaseModel):
    query: str = Field(..., description="Natural language description of tables to find")
    top_k: int = Field(default=10, ge=1, le=50, description="Max results")
    user_id: Optional[str] = None


class GetTableContextInput(BaseModel):
    node_id: str = Field(..., description="Table node ID: source_db:schema:table_name")
    user_id: Optional[str] = None


class GetRelationshipsInput(BaseModel):
    node_id: str = Field(..., description="Table node ID")
    user_id: Optional[str] = None


class FindJoinPathInput(BaseModel):
    from_table: str = Field(..., description="Source table node ID")
    to_table: str = Field(..., description="Target table node ID")
    user_id: Optional[str] = None


class SmartQueryInput(BaseModel):
    query: str = Field(..., description="Natural language query about your data")
    user_id: Optional[str] = None
    top_k: int = Field(default=5, ge=1, le=20)
    skip_llm: bool = Field(default=False, description="Skip LLM for fast retrieval-only mode")


class SuggestQueryInput(BaseModel):
    node_id: str
    intent: str
    user_id: Optional[str] = None


class ExplainTableInput(BaseModel):
    node_id: str
    user_id: Optional[str] = None


# ─── Tool Registry ────────────────────────────────────────────────────────────

MCP_TOOLS = [
    {
        "name": "search_tables",
        "description": "Semantic search for database tables by description or intent",
        "input_schema": SearchTablesInput.model_json_schema(),
    },
    {
        "name": "get_table_context",
        "description": "Get full context for a table including columns, relationships, type",
        "input_schema": GetTableContextInput.model_json_schema(),
    },
    {
        "name": "get_relationships",
        "description": "Get direct relationships and join info for a table",
        "input_schema": GetRelationshipsInput.model_json_schema(),
    },
    {
        "name": "find_join_path",
        "description": "Discover the shortest join path between two tables",
        "input_schema": FindJoinPathInput.model_json_schema(),
    },
    {
        "name": "smart_query",
        "description": "PRIMARY TOOL: Full pipeline - semantic search + graph reasoning + LLM answer",
        "input_schema": SmartQueryInput.model_json_schema(),
    },
    {
        "name": "suggest_query",
        "description": "Generate a SQL query suggestion for a given table and intent",
        "input_schema": SuggestQueryInput.model_json_schema(),
    },
    {
        "name": "explain_table",
        "description": "Get a plain-language explanation of what a table stores and how to use it",
        "input_schema": ExplainTableInput.model_json_schema(),
    },
]


# ─── Tool Executor ────────────────────────────────────────────────────────────

class MCPToolExecutor:

    async def execute(self, tool_name: str, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        """
        Route a tool call to the appropriate service.
        Returns structured result dict.
        """
        if tool_name == "search_tables":
            inp = SearchTablesInput(**tool_input)
            return {
                "tool": tool_name,
                "result": await smart_query_service.search_tables(
                    inp.query, inp.top_k, inp.user_id
                ),
            }

        elif tool_name == "get_table_context":
            inp = GetTableContextInput(**tool_input)
            return {
                "tool": tool_name,
                "result": await smart_query_service.get_table_context(
                    inp.node_id, inp.user_id
                ),
            }

        elif tool_name == "get_relationships":
            inp = GetRelationshipsInput(**tool_input)
            return {
                "tool": tool_name,
                "result": await smart_query_service.get_relationships(
                    inp.node_id, inp.user_id
                ),
            }

        elif tool_name == "find_join_path":
            inp = FindJoinPathInput(**tool_input)
            return {
                "tool": tool_name,
                "result": await smart_query_service.find_join_path(
                    inp.from_table, inp.to_table, inp.user_id
                ),
            }

        elif tool_name == "smart_query":
            inp = SmartQueryInput(**tool_input)
            return {
                "tool": tool_name,
                "result": await smart_query_service.smart_query(
                    inp.query, inp.user_id, inp.top_k, inp.skip_llm
                ),
            }

        elif tool_name == "suggest_query":
            inp = SuggestQueryInput(**tool_input)
            context = await smart_query_service.get_table_context(inp.node_id, inp.user_id)
            from services.llm_service import llm_service
            sql = await llm_service.suggest_query(context, inp.intent)
            return {"tool": tool_name, "result": {"sql": sql}}

        elif tool_name == "explain_table":
            inp = ExplainTableInput(**tool_input)
            context = await smart_query_service.get_table_context(inp.node_id, inp.user_id)
            from services.llm_service import llm_service
            explanation = await llm_service.explain_table(inp.node_id, context)
            return {"tool": tool_name, "result": {"explanation": explanation}}

        else:
            return {"tool": tool_name, "error": f"Unknown tool: {tool_name}"}


mcp_executor = MCPToolExecutor()
