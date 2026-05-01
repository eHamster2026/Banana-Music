"""
Upload / ingest lifecycle hooks.

Registered coroutines run after a track's Chromaprint fingerprint is written
(see routers/upload.fingerprint batch). Hooks must not raise — errors are logged.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

if TYPE_CHECKING:
    import models

logger = logging.getLogger(__name__)

PostFingerprintHook = Callable[[Session, "models.Track"], Awaitable[None]]

_POST_FINGERPRINT: list[PostFingerprintHook] = []


def register_post_fingerprint(hook: PostFingerprintHook) -> None:
    _POST_FINGERPRINT.append(hook)


async def run_post_fingerprint_hooks(db: Session, track: "models.Track") -> None:
    for fn in _POST_FINGERPRINT:
        try:
            await fn(db, track)
        except Exception:
            logger.exception("post_fingerprint hook failed track_id=%s", getattr(track, "id", None))


def _register_default_hooks() -> None:
    async def _metadata_enrich(db: Session, track: "models.Track") -> None:
        from services.upload_metadata_enrich import try_enrich_track_from_metadata_plugins

        await try_enrich_track_from_metadata_plugins(db, track)

    register_post_fingerprint(_metadata_enrich)


_register_default_hooks()
