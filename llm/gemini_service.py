"""
Gemini LLM service.
STRICT USAGE: ONLY for offline enrichment + final smart_query reasoning.
Never called for retrieval, search, or graph traversal.
"""
import json
import re
from typing import Optional, Dict, Any, List
import httpx
from config import settings


ENRICHMENT_PROMPT = """You are a data catalog expert. Analyze this table metadata and return ONLY valid JSON.

Table: {table_name}
Schema: {schema_name}
Columns: {columns}

Infer:
1. table_type: one of ["fact", "dimension", "log", "bridge", "staging", "unknown"]
2. column_roles: dict mapping column_name → one of ["metric", "key", "timestamp", "categorical", "text", "foreign_key", "primary_key", "unknown"]
3. description: one sentence describing what this table stores
4. tags: list of 3-5 relevant domain tags

Return ONLY this JSON structure, no other text:
{{
  "table_type": "...",
  "column_roles": {{"col1": "...", "col2": "..."}},
  "description": "...",
  "tags": ["...", "..."]
}}"""

REASONING_PROMPT = """You are a data systems expert helping an AI agent understand database structure.

User Query: {query}

Relevant Database Context (JSON):
{context}

Based ONLY on the provided context, answer the user's query. Include:
1. Which tables are relevant and why
2. How they relate to each other (join paths)
3. What SQL pattern would answer the query
4. Any important caveats about data types or relationships

Be concise and precise. Format as structured prose."""


class LLMService:

    def __init__(self):
        self._api_key = settings.GEMINI_API_KEY
        self._model = settings.GEMINI_MODEL
        self._base_url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self._model}:generateContent"
        )

    async def _call(self, prompt: str) -> str:
        if not self._api_key:
            return '{"error": "GEMINI_API_KEY not configured"}'

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "maxOutputTokens": settings.LLM_MAX_TOKENS,
                "temperature": 0.1,
            },
        }

        # Try configured model first, then safe fallbacks.
        models_to_try = []
        seen = set()
        for m in [
            self._model,
            "gemini-1.5-flash-latest",
            "gemini-2.0-flash",
            "gemini-2.5-flash",
        ]:
            if m and m not in seen:
                seen.add(m)
                models_to_try.append(m)

        last_error = None
        async with httpx.AsyncClient(timeout=30.0) as client:
            for model_name in models_to_try:
                try:
                    url = (
                        "https://generativelanguage.googleapis.com/v1beta/models/"
                        f"{model_name}:generateContent"
                    )
                    resp = await client.post(
                        url,
                        params={"key": self._api_key},
                        json=payload,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    return data["candidates"][0]["content"]["parts"][0]["text"]
                except Exception as exc:
                    last_error = str(exc)
                    continue

        return json.dumps({"error": f"Gemini call failed: {last_error}"})

    async def enrich_table(
        self,
        table_name: str,
        schema_name: str,
        columns: List[Dict[str, str]],
    ) -> Dict[str, Any]:
        """
        Offline enrichment: infer table type + column roles.
        Returns structured dict.
        """
        col_str = ", ".join(
            f"{c['name']} ({c['type']})" for c in columns[:25]
        )
        prompt = ENRICHMENT_PROMPT.format(
            table_name=table_name,
            schema_name=schema_name,
            columns=col_str,
        )

        raw = await self._call(prompt)

        # Extract JSON even if wrapped in markdown
        json_match = re.search(r'\{[\s\S]*\}', raw)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        return {
            "table_type": "unknown",
            "column_roles": {},
            "description": "",
            "tags": [],
        }

    async def reason(
        self,
        query: str,
        context: Dict[str, Any],
    ) -> str:
        """
        Final reasoning call for smart_query.
        Context is pre-filtered, structured JSON — LLM never sees raw graph.
        """
        context_str = json.dumps(context, indent=2)
        # Truncate if too long
        if len(context_str) > 8000:
            context_str = context_str[:8000] + "\n... [truncated]"

        prompt = REASONING_PROMPT.format(
            query=query,
            context=context_str,
        )

        return await self._call(prompt)

    async def suggest_query(
        self,
        table_context: Dict[str, Any],
        user_intent: str,
    ) -> str:
        """Generate SQL query suggestion given context and intent."""
        prompt = f"""Given this database context:
{json.dumps(table_context, indent=2)[:4000]}

User wants to: {user_intent}

Generate a SQL query that satisfies this intent. Return ONLY the SQL, no explanation."""
        return await self._call(prompt)


llm_service = LLMService()
