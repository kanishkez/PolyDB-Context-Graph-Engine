# MCP Interaction Examples

## List tools
`GET /api/v1/mcp/tools`

## Direct tool call
`POST /api/v1/mcp/call`

```json
{
  "tool_name": "search_tables",
  "tool_input": {"query": "customer orders", "top_k": 5}
}
```

## Agent loop
`POST /api/v1/mcp/agent`

```json
{
  "query": "What tables should I join for customer LTV?"
}
```
