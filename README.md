# PolyDB Context Graph Engine

PolyDB Context Graph Engine is a backend context engine for databases, designed to help LLMs and AI agents reason over enterprise data systems safely and accurately.

It connects to multiple databases (PostgreSQL, MySQL, Trino), extracts and normalizes metadata into a unified internal model, builds a context graph with NetworkX, and creates semantic retrieval with embeddings in FAISS. It exposes these capabilities through FastAPI and MCP-compatible tools so agents can discover relevant tables, relationships, join paths, and query patterns with grounded context.

It is a context engine for structured systems, not a basic RAG stack. The system combines metadata extraction, graph reasoning, semantic retrieval, and constrained LLM usage to answer data-system questions in one API call.

## What It Solves

Modern organizations store business logic across multiple databases. Agents and developers need to answer questions such as:

- Which tables are relevant for a metric?
- How can these tables be joined safely?
- What is the shortest relationship path between two entities?
- What query pattern should be used for a business question?

PolyDB builds a normalized metadata layer, an in-memory context graph, and a retrieval index so these questions can be answered quickly and consistently.

## Core Architecture

The platform has two pipelines.

### 1. Offline Ingestion Pipeline

1. Connect to source databases (PostgreSQL, MySQL, Trino)
2. Extract metadata from `information_schema`
3. Normalize tables, columns, and relationships into unified models
4. Persist metadata to PostgreSQL (source of truth)
5. Build and update NetworkX context graph (derived state)
6. Build and update FAISS embeddings
7. Optionally run LLM enrichment for semantic metadata

### 2. Online Query Pipeline

1. Receive request through FastAPI (`/api/v1/smart_query`)
2. Search relevant tables via FAISS
3. Expand context through graph traversal and join-path reasoning
4. Apply security filters
5. Assemble structured JSON context
6. Perform one LLM reasoning call
7. Return final answer and cache results

## Technology Choices

- **FastAPI**: async API runtime with strong schema support.
- **SQLAlchemy + Alembic + PostgreSQL**: durable metadata store and migration discipline.
- **NetworkX**: in-memory multi-hop graph traversal and join-path discovery.
- **Sentence Transformers + FAISS**: low-latency semantic table retrieval.
- **Gemini**: offline enrichment and final query reasoning.
- **Pydantic**: strict typed contracts for request/response and internal models.

## Project Structure

```text
api/                 FastAPI routes
cache/               TTL cache implementation
connectors/          Source DB connectors (postgres, mysql, trino)
db/                  SQLAlchemy models and session setup
embeddings/          FAISS embedding store
examples/            Example query and integration payloads
graph/               Graph build and reasoning logic
llm/                 Gemini client
mcp/                 MCP tool definitions and agent loop
models/              Unified normalized data models
services/            Application service layer
workers/             Background ingestion/enrichment/embedding workers
alembic/             Database migrations
main.py              FastAPI app entrypoint
```

## API Surface

### High-Level Endpoint

- `POST /api/v1/smart_query` (primary endpoint)

### Low-Level Endpoints

- `GET /api/v1/search`
- `GET /api/v1/context/{node_id}`
- `GET /api/v1/relationships/{node_id}`
- `GET /api/v1/join-path`
- `GET /api/v1/graph/stats`
- `GET /api/v1/graph/clusters`

### LLM Utility Endpoints

- `POST /api/v1/suggest_query`
- `POST /api/v1/explain_table`

### MCP Endpoints

- `GET /api/v1/mcp/tools`
- `POST /api/v1/mcp/call`
- `POST /api/v1/mcp/agent`

## Service Layer

- `MetadataService`: metadata CRUD, incremental diffing, relationship persistence.
- `GraphService`: graph initialization, neighbor traversal, join-path discovery, clustering.
- `EmbeddingService`: embedding upsert/search wrappers over FAISS.
- `LLMService`: semantic reasoning and query suggestion wrappers.
- `CacheService`: query/search/context caches.

## Security Controls

- Sensitive columns are flagged by pattern and filtered from context.
- Access filtering hooks exist at database/schema context boundaries.
- Responses are structured JSON only.
- Runtime query path reasons over metadata, not raw table rows.

## Performance and Optimization

- Incremental extraction via metadata hashing.
- Derived graph state loaded in-memory for fast traversal.
- Batched embedding updates.
- Query/search/context caches to avoid recomputation.
- Single LLM call per `smart_query` response path.

## Quick Start

### 1) Install

```bash
pip install -r requirements.txt
```

### 2) Configure Environment

Set at least:

- `METADATA_DB_URL`
- `TARGET_DATABASES` (JSON array)
- `GEMINI_API_KEY` (for LLM-backed responses)

Example `TARGET_DATABASES`:

```json
[
  {
    "name": "sales_demo",
    "type": "postgres",
    "host": "localhost",
    "port": 5432,
    "database": "sales_demo",
    "user": "engine",
    "password": ""
  }
]
```

### 3) Migrate Metadata Store

```bash
alembic upgrade head
```

### 4) Run API

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

### 5) Trigger Initial Pipeline

```bash
curl -X POST http://localhost:8000/api/v1/admin/extract -H "Content-Type: application/json" -d '{}'
curl -X POST http://localhost:8000/api/v1/admin/enrich
curl -X POST http://localhost:8000/api/v1/admin/embeddings
```

## Example Request

```bash
curl -X POST http://localhost:8000/api/v1/smart_query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "How do I compute monthly revenue by customer segment?",
    "top_k": 5,
    "skip_llm": false
  }'
```

## Notes

- PostgreSQL metadata store is the source of truth.
- Graph and embeddings are derived runtime/index layers.
- If Gemini model access differs by key/project, model fallback is handled in the LLM client.
