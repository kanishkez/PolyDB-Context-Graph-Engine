"""Service wrapper for LLM operations in the service layer."""
from typing import Any, Dict, List

from llm.gemini_service import llm_service as gemini_llm


class LLMService:

    async def reason(self, query: str, context: Dict[str, Any]) -> str:
        return await gemini_llm.reason(query, context)

    async def enrich_table(
        self,
        table_name: str,
        schema_name: str,
        columns: List[Dict[str, str]],
    ) -> Dict[str, Any]:
        return await gemini_llm.enrich_table(table_name, schema_name, columns)

    async def suggest_query(self, table_context: Dict[str, Any], user_intent: str) -> str:
        return await gemini_llm.suggest_query(table_context, user_intent)

    async def explain_table(self, node_id: str, table_context: Dict[str, Any]) -> str:
        return await gemini_llm.reason(
            f"Explain what the table {node_id} stores and how it can be used.",
            table_context,
        )


llm_service = LLMService()
