"""
Aggregate calls to SearchPlugin instances (shared by /plugins/search and /search).
"""

from __future__ import annotations

import asyncio
from typing import Any

from app_logging import logger
import plugins.loader as loader
from plugins.errors import PluginParseError, PluginUpstreamError


async def execute_search_with_records(
    records: list[loader.PluginRecord],
    q: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Run search on pre-validated plugin records; returns flat dicts for API models."""
    if not records:
        return []

    plugin_ids = [r.manifest.id for r in records]
    instances = [r.instance for r in records]

    logger.info(
        "调用搜索插件 search q=%r limit=%s plugins=%s",
        q,
        limit,
        plugin_ids,
    )

    gather_results = await asyncio.gather(
        *[instance.search(q, limit) for instance in instances],
    )

    out: list[dict[str, Any]] = []
    for pid, plugin_results in zip(plugin_ids, gather_results):
        for r in plugin_results:
            out.append({
                "plugin_id": pid,
                "source_id": r.source_id,
                "title": r.title,
                "artist": r.artist,
                "album": r.album,
                "artists": list(r.artists) if r.artists else [],
                "duration_sec": r.duration_sec,
                "cover_url": r.cover_url,
                "preview_url": r.preview_url,
            })
    if not out:
        logger.info("插件搜索无结果: q=%r, plugins=%s", q, plugin_ids)
    return out


async def run_plugin_search_flat(q: str, limit: int = 20) -> list[dict[str, Any]]:
    """Search all enabled SearchPlugin instances (for /search aggregation)."""
    records = loader.get_search_plugins()
    try:
        return await execute_search_with_records(records, q, limit)
    except PluginUpstreamError:
        raise
    except PluginParseError:
        raise
