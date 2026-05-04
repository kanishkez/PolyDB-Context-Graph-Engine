"""
Agent loop — LLM agent that drives MCP tool calls to answer user queries.
Pattern: LLM → tool decision → execute → result → LLM → answer
"""
import json
import logging
from typing import List, Dict, Any, Optional
import httpx
from mcp.tools import mcp_executor, MCP_TOOLS
from config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a data systems expert with access to a multi-database catalog.
You have tools to search tables, understand relationships, and reason about data.

RULES:
1. ALWAYS use smart_query for broad questions — it's the most efficient tool
2. Use search_tables only when you need to explore options
3. Use find_join_path when asked about joining or combining tables
4. Never make up table names — only reference what tools return
5. Be concise and technical in your answers

When you call a tool, respond ONLY with this JSON:
{"tool_call": {"name": "<tool_name>", "input": {<input_fields>}}}

When you have a final answer (no more tool calls needed), respond with:
{"final_answer": "<your answer>"}"""


class AgentLoop:

    def __init__(self, max_iterations: int = 5):
        self.max_iterations = max_iterations

    async def _llm_decide(
        self,
        messages: List[Dict[str, str]],
    ) -> str:
        """Ask Gemini what to do next."""
        payload = {
            "contents": [
                {"role": "user" if m["role"] == "user" else "model",
                 "parts": [{"text": m["content"]}]}
                for m in messages
            ],
            "generationConfig": {
                "maxOutputTokens": 512,
                "temperature": 0.1,
            },
        }

        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{settings.GEMINI_MODEL}:generateContent"
        )

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, params={"key": settings.GEMINI_API_KEY}, json=payload)
            resp.raise_for_status()
            data = resp.json()

        return data["candidates"][0]["content"]["parts"][0]["text"]

    async def run(
        self,
        user_query: str,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Main agent loop.
        Returns: {answer, tool_calls_made, iterations}
        """
        messages = [
            {"role": "system_context", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Question: {user_query}\n\nAvailable tools:\n{json.dumps([t['name'] for t in MCP_TOOLS])}"},
        ]

        tool_calls_made = []
        iterations = 0

        while iterations < self.max_iterations:
            iterations += 1

            raw_response = await self._llm_decide(messages)

            # Parse response
            try:
                # Extract JSON from response
                import re
                json_match = re.search(r'\{[\s\S]*\}', raw_response)
                if not json_match:
                    break
                parsed = json.loads(json_match.group())
            except json.JSONDecodeError:
                logger.warning(f"[agent] Could not parse LLM response: {raw_response[:200]}")
                break

            # Final answer
            if "final_answer" in parsed:
                return {
                    "answer": parsed["final_answer"],
                    "tool_calls": tool_calls_made,
                    "iterations": iterations,
                }

            # Tool call
            if "tool_call" in parsed:
                tc = parsed["tool_call"]
                tool_name = tc.get("name")
                tool_input = tc.get("input", {})

                if user_id and "user_id" in tool_input:
                    tool_input["user_id"] = user_id

                logger.info(f"[agent] Calling tool: {tool_name}")
                tool_result = await mcp_executor.execute(tool_name, tool_input)
                tool_calls_made.append({"tool": tool_name, "input": tool_input})

                # Add to conversation
                messages.append({
                    "role": "assistant",
                    "content": f"Tool call: {json.dumps(tc)}"
                })
                messages.append({
                    "role": "user",
                    "content": f"Tool result:\n{json.dumps(tool_result, indent=2)[:3000]}\n\nContinue reasoning or provide final answer."
                })
            else:
                # No tool call, no final answer — force conclusion
                return {
                    "answer": raw_response,
                    "tool_calls": tool_calls_made,
                    "iterations": iterations,
                }

        return {
            "answer": "Agent reached max iterations without a final answer.",
            "tool_calls": tool_calls_made,
            "iterations": iterations,
        }


agent_loop = AgentLoop()
