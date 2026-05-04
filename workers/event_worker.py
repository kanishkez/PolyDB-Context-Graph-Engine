"""Event-driven schema refresh for PostgreSQL sources using LISTEN/NOTIFY."""
import asyncio
import json
import logging
import time
from typing import Dict

import asyncpg

from config import settings
from workers.extraction_worker import run_extraction

logger = logging.getLogger(__name__)
_last_event_ts: Dict[str, float] = {}


async def _connect_source(cfg: dict) -> asyncpg.Connection:
    return await asyncpg.connect(
        host=cfg.get("host", "localhost"),
        port=cfg.get("port", 5432),
        user=cfg["user"],
        password=cfg.get("password", ""),
        database=cfg["database"],
    )


async def _install_pg_event_trigger(conn: asyncpg.Connection, source_name: str):
    channel = settings.EVENT_CHANNEL
    source = source_name.replace("'", "''")
    # Requires elevated DB privileges on source DB. If unavailable, polling still covers updates.
    sql = f"""
    CREATE OR REPLACE FUNCTION public.polydb_notify_schema_change()
    RETURNS event_trigger
    LANGUAGE plpgsql
    AS $$
    BEGIN
      PERFORM pg_notify('{channel}',
        json_build_object(
          'source_db', '{source}',
          'tag', tg_tag,
          'at', clock_timestamp()
        )::text
      );
    END;
    $$;

    DROP EVENT TRIGGER IF EXISTS polydb_ddl_notify;
    CREATE EVENT TRIGGER polydb_ddl_notify
      ON ddl_command_end
      EXECUTE FUNCTION public.polydb_notify_schema_change();
    """
    await conn.execute(sql)


async def _handle_event(cfg: dict, payload: str):
    source = cfg["name"]
    now = time.time()
    last = _last_event_ts.get(source, 0.0)
    if (now - last) < settings.EVENT_DEBOUNCE_SECONDS:
        logger.info(f"[event] Debounced schema event for {source}")
        return
    _last_event_ts[source] = now
    logger.info(f"[event] Triggering extraction for {source}; payload={payload}")
    await run_extraction(cfg, force=True)


async def _listen_source(cfg: dict):
    source = cfg["name"]
    channel = settings.EVENT_CHANNEL

    while True:
        conn = None
        try:
            conn = await _connect_source(cfg)

            try:
                await _install_pg_event_trigger(conn, source)
                logger.info(f"[event] Installed DDL event trigger for {source}")
            except Exception as e:
                logger.warning(
                    f"[event] Could not install trigger for {source} ({e}). "
                    "Polling scheduler will continue to keep metadata fresh."
                )

            def _listener(_conn, _pid, _channel, payload):
                asyncio.create_task(_handle_event(cfg, payload))

            await conn.add_listener(channel, _listener)
            logger.info(f"[event] Listening on channel '{channel}' for source {source}")

            while True:
                await asyncio.sleep(60)
        except asyncio.CancelledError:
            if conn:
                try:
                    await conn.close()
                except Exception:
                    pass
            raise
        except Exception as e:
            logger.error(f"[event] Listener error for {source}: {e}")
            if conn:
                try:
                    await conn.close()
                except Exception:
                    pass
            await asyncio.sleep(5)


async def run_event_listener():
    db_configs = json.loads(settings.TARGET_DATABASES)
    pg_sources = [
        cfg for cfg in db_configs
        if cfg.get("type", "").lower() in ("postgres", "postgresql")
    ]

    if not pg_sources:
        logger.info("[event] No PostgreSQL sources configured; skipping event listener")
        return

    tasks = [asyncio.create_task(_listen_source(cfg)) for cfg in pg_sources]
    try:
        await asyncio.gather(*tasks)
    finally:
        for t in tasks:
            t.cancel()
