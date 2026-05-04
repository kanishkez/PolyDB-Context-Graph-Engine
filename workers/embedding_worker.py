"""Dedicated embedding worker wrapper."""

from workers.extraction_worker import run_embedding_update


async def run_embedding_worker():
    """Run one embedding update cycle."""
    await run_embedding_update()
