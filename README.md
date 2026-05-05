# PolyDB Context Graph Engine

PolyDB Context Graph Engine is an API-first backend that gives LLMs and agents structured context about databases.

It connects to multiple data sources, extracts metadata, normalizes it into a unified internal model, builds a context graph, and creates embedding-based retrieval. Agents can then query this context through REST APIs or MCP tools.

## What This Project Is

This is not a dashboard product. The UI in this repo is optional and only for local inspection.  
The core product is the engine exposed through:

- FastAPI endpoints (`/api/v1/...`)
- MCP-compatible tool endpoints (`/api/v1/mcp/...`)

## What It Does

1. Connects to source databases (`postgres`, `mysql`, `trino`)
2. Extracts metadata (tables, columns, keys, relationships)
3. Normalizes metadata into unified models
4. Stores normalized metadata in PostgreSQL
5. Builds an in-memory context graph (NetworkX)
6. Builds embeddings over table context (Sentence Transformers + FAISS)
7. Serves reasoning/query APIs for agents

## Architecture At A Glance

- `db/`: metadata store models and sessions (SQLAlchemy)
- `connectors/`: source-specific extractors
- `services/metadata_service.py`: persistence and diff logic
- `services/graph_service.py`: graph operations and join-path reasoning
- `embeddings/faiss_store.py`: vector index lifecycle
- `services/smart_query_service.py`: orchestration path for `smart_query`
- `workers/`: background extraction/enrichment/embedding updates
- `api/routes.py`: HTTP interface
- `mcp/`: MCP tool wrappers and agent loop

## Environment Variables

Required:

- `METADATA_DB_URL`: PostgreSQL URL for the engine's internal metadata store
- `TARGET_DATABASES`: JSON array of source connection configs

Optional:

- `GEMINI_API_KEY`: required only for LLM-backed reasoning/enrichment
- `ENABLE_EVENT_LISTENER`: defaults to `true`; disable if you only want polling

Example:

```bash
export METADATA_DB_URL='postgresql+asyncpg://engine@localhost:55432/metadata_store'
export TARGET_DATABASES='[
  {"name":"sales_demo","type":"postgres","host":"localhost","port":55432,"database":"sales_demo","user":"engine","password":""},
  {"name":"marketing_demo","type":"postgres","host":"localhost","port":55432,"database":"marketing_demo","user":"engine","password":""},
  {"name":"ops_demo","type":"postgres","host":"localhost","port":55432,"database":"ops_demo","user":"engine","password":""}
]'
export GEMINI_API_KEY='YOUR_KEY'
```

## Setup

```bash
pip install -r requirements.txt
alembic upgrade head
uvicorn main:app --host 0.0.0.0 --port 8000
```

## How People Should Use The Engine

Typical operator flow:

1. Start server with env vars configured.
2. Trigger metadata extraction:
   `POST /api/v1/admin/extract`
3. Optionally trigger enrichment:
   `POST /api/v1/admin/enrich`
4. Build embeddings:
   `POST /api/v1/admin/embeddings`
5. Query through:
   - `POST /api/v1/smart_query` (high-level path)
   - or low-level graph/search endpoints
6. For agent integration, use MCP endpoints:
   - `GET /api/v1/mcp/tools`
   - `POST /api/v1/mcp/call`
   - `POST /api/v1/mcp/agent`

## Core API Endpoints

High-level:

- `POST /api/v1/smart_query`

Low-level:

- `GET /api/v1/search`
- `GET /api/v1/context/{node_id}`
- `GET /api/v1/relationships/{node_id}`
- `GET /api/v1/join-path`
- `GET /api/v1/graph/stats`
- `GET /api/v1/graph/clusters`
- `GET /api/v1/health`

Admin/Workers:

- `POST /api/v1/admin/extract`
- `POST /api/v1/admin/enrich`
- `POST /api/v1/admin/embeddings`
- `DELETE /api/v1/admin/cache`

## Example Calls

Trigger extraction:

```bash
curl -X POST http://localhost:8000/api/v1/admin/extract \
  -H "Content-Type: application/json" \
  -d '{}'
```

Run query (retrieval-only mode):

```bash
curl -X POST http://localhost:8000/api/v1/smart_query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What tables should I use for monthly revenue by segment?",
    "top_k": 5,
    "skip_llm": true
  }'
```

## Security Notes

- Sensitive columns are flagged and filtered before context is exposed.
- The engine reasons over metadata/context, not raw table rows by default.
- Access filtering hooks are available in the security layer.

## Operational Notes

- Metadata store (PostgreSQL) is source of truth for normalized catalog state.
- Graph and embeddings are derived layers rebuilt incrementally.
- If no source DB changes are detected, extraction may complete with zero deltas.
