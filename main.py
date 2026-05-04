"""PolyDB Context Graph Engine FastAPI application."""
import asyncio
import logging
from contextlib import asynccontextmanager
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from db.session import init_db, AsyncSessionLocal
from api.routes import router
from services.graph_service import graph_service
from embeddings.faiss_store import embedding_store
from workers.extraction_worker import periodic_refresh
from workers.event_worker import run_event_listener

logging.basicConfig(
    level=logging.INFO if not settings.DEBUG else logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup + shutdown lifecycle."""
    # ── Startup ──────────────────────────────────────────────────────────────
    logger.info("Initializing metadata store (PostgreSQL)...")
    await init_db()

    logger.info("Loading graph from metadata store...")
    async with AsyncSessionLocal() as session:
        await graph_service.initialize_from_db(session)

    logger.info(f"Graph loaded: {graph_service.graph_stats}")

    logger.info("Loading FAISS embedding index...")
    embedding_store.load()
    logger.info(f"Embeddings loaded: {embedding_store.total_vectors} vectors")

    # Start background refresh (non-blocking)
    refresh_interval = max(1, settings.POLL_INTERVAL_MINUTES) * 60
    refresh_task = asyncio.create_task(periodic_refresh(interval_seconds=refresh_interval))
    logger.info(
        f"Background refresh worker started ({settings.POLL_INTERVAL_MINUTES} min interval)"
    )

    event_task = None
    if settings.ENABLE_EVENT_LISTENER:
        event_task = asyncio.create_task(run_event_listener())
        logger.info("Event listener worker started")

    logger.info(f"✓ {settings.APP_NAME} ready")

    yield

    # ── Shutdown ─────────────────────────────────────────────────────────────
    refresh_task.cancel()
    if event_task:
        event_task.cancel()

    try:
        await refresh_task
    except asyncio.CancelledError:
        pass
    if event_task:
        try:
            await event_task
        except asyncio.CancelledError:
            pass

    embedding_store.save()
    logger.info("Embeddings saved. Shutdown complete.")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.API_VERSION,
    description=(
        "Production-grade multi-database context graph engine with MCP tool interface. "
        "Enables LLM agents to understand and reason about data systems."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix=f"/api/{settings.API_VERSION}")


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
        workers=1,
    )
