from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app_logging import logger
from config import settings
from deps import get_db, get_optional_user
import models
import schemas
from plugins.errors import PluginParseError, PluginUpstreamError
from services.artist_names import UNKNOWN_ARTIST_NAMES
from services.plugin_search import run_plugin_search_flat

router = APIRouter(prefix="/search", tags=["Search"])


def playlist_out(p):
    return schemas.PlaylistOut(
        id=p.id, name=p.name, art_color=p.art_color,
        description=p.description, is_featured=p.is_featured,
        is_system=p.is_system, track_count=len(p.playlist_tracks)
    )


@router.get("", response_model=schemas.SearchResult)
async def search(
    q: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    user: Optional[models.User] = Depends(get_optional_user),
):
    like = f"%{q}%"

    # 通过关联表搜索 featured 艺人名 → 得到对应的 track_id / album_id
    featured_track_ids = (
        db.query(models.TrackArtist.track_id)
        .join(models.Artist, models.Artist.id == models.TrackArtist.artist_id)
        .filter(models.Artist.name.ilike(like))
    )
    featured_album_ids = (
        db.query(models.AlbumArtist.album_id)
        .join(models.Artist, models.Artist.id == models.AlbumArtist.artist_id)
        .filter(models.Artist.name.ilike(like))
    )

    tracks = (
        db.query(models.Track)
        .filter(or_(models.Track.title.ilike(like), models.Track.id.in_(featured_track_ids)))
        .limit(10).all()
    )
    albums = (
        db.query(models.Album)
        .filter(or_(models.Album.title.ilike(like), models.Album.id.in_(featured_album_ids)))
        .limit(8).all()
    )
    artists = (
        db.query(models.Artist)
        .filter(models.Artist.name.ilike(like), models.Artist.name.notin_(UNKNOWN_ARTIST_NAMES))
        .limit(6)
        .all()
    )
    playlists = db.query(models.Playlist).filter(models.Playlist.name.ilike(like)).limit(6).all()

    plugin_hits: list[schemas.PluginSearchHitOut] = []
    if user is not None and not settings.banana_testing:
        try:
            raw = await run_plugin_search_flat(q, limit=10)
            plugin_hits = [schemas.PluginSearchHitOut(**d) for d in raw]
        except PluginUpstreamError as exc:
            logger.warning("聚合搜索插件上游异常: %s", exc)
        except PluginParseError as exc:
            logger.warning("聚合搜索插件解析失败: %s", exc)
        except Exception as exc:
            logger.warning("聚合搜索插件异常: %s", exc)

    return schemas.SearchResult(
        tracks=tracks,
        albums=albums,
        artists=artists,
        playlists=[playlist_out(p) for p in playlists],
        plugin_hits=plugin_hits,
    )


@router.get("/suggestions")
def suggestions(q: str = Query(..., min_length=1), db: Session = Depends(get_db)):
    like = f"%{q}%"
    tracks = db.query(models.Track.title).filter(models.Track.title.ilike(like)).limit(5).all()
    artists = (
        db.query(models.Artist.name)
        .filter(models.Artist.name.ilike(like), models.Artist.name.notin_(UNKNOWN_ARTIST_NAMES))
        .limit(3)
        .all()
    )
    results = [r[0] for r in tracks] + [r[0] for r in artists]
    return {"suggestions": list(dict.fromkeys(results))[:8]}
