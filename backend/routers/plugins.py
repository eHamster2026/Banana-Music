"""
routers/plugins.py
插件系统 HTTP 端点：
  GET  /plugins                  — 列出插件及运行状态
  GET  /plugins/search           — 调用搜索插件
  POST /plugins/download         — 触发搜索插件的下载功能入库
  POST /plugins/metadata/lookup  — 调用元数据插件查询单首曲目的元数据候选
"""

import asyncio
from typing import Any, Optional

from app_logging import logger
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from deps import get_current_user, get_admin_user, get_db
import models
import plugins.loader as loader
from plugins.errors import PluginParseError, PluginUpstreamError
from services.plugin_search import execute_search_with_records

router = APIRouter(prefix="/plugins", tags=["Plugins"])


# ── Schema ────────────────────────────────────────────────────

class PluginInfo(BaseModel):
    id: str
    name: str
    version: str
    capabilities: list[str]
    enabled: bool
    loaded: bool
    error: Optional[str] = None


class PluginDetail(PluginInfo):
    config_schema: dict = Field(default_factory=dict)
    config: dict = Field(default_factory=dict)


class PluginConfigUpdate(BaseModel):
    config: dict[str, Any] = Field(default_factory=dict)


class SearchResultOut(BaseModel):
    plugin_id: str
    source_id: str
    title: str
    artist: str
    album: str
    duration_sec: float
    cover_url: Optional[str] = None
    preview_url: Optional[str] = None


class DownloadRequest(BaseModel):
    plugin_id: str
    source_id: str
    metadata_override: Optional[dict] = None


class MetadataLookupRequest(BaseModel):
    track_id: int
    plugin_id: Optional[str] = None   # None = 调用全部元数据插件


class MetadataResultOut(BaseModel):
    plugin_id: str
    title: Optional[str] = None
    artists: list[str] = Field(default_factory=list)
    album: Optional[str] = None
    track_number: Optional[int] = None
    release_date: Optional[str] = None
    lyrics: Optional[str] = None
    cover_url: Optional[str] = None
    confidence: float = 0.0


def _plugin_info(record: loader.PluginRecord) -> PluginInfo:
    return PluginInfo(
        id=record.manifest.id,
        name=record.manifest.name,
        version=record.manifest.version,
        capabilities=record.manifest.capabilities,
        enabled=record.enabled,
        loaded=record.loaded,
        error=record.error,
    )


def _plugin_detail(record: loader.PluginRecord) -> PluginDetail:
    return PluginDetail(
        **_plugin_info(record).model_dump(),
        config_schema=record.manifest.config_schema,
        config=record.config,
    )


def _require_plugin_record(plugin_id: str) -> loader.PluginRecord:
    record = loader.get_plugin(plugin_id)
    if not record:
        raise HTTPException(404, f"插件 {plugin_id!r} 不存在")
    return record


# ── 端点 ──────────────────────────────────────────────────────

@router.get("", response_model=list[PluginInfo])
def list_plugins(_user: models.User = Depends(get_admin_user)):
    return [
        _plugin_info(record)
        for record in loader.all_plugins().values()
    ]


@router.get("/search", response_model=list[SearchResultOut])
async def search_plugins(
    q: str,
    plugin: Optional[str] = None,
    limit: int = 20,
    _user: models.User = Depends(get_current_user),
):
    """
    调用搜索插件。plugin 参数指定插件 id；省略时调用所有搜索插件并聚合结果。
    """
    from plugins.base import SearchPlugin

    if plugin:
        record = _require_plugin_record(plugin)
        if not record.enabled:
            raise HTTPException(409, f"插件 {plugin!r} 当前已禁用")
        if record.error:
            raise HTTPException(409, f"插件 {plugin!r} 加载失败: {record.error}")
        if not isinstance(record.instance, SearchPlugin):
            raise HTTPException(400, f"插件 {plugin!r} 不支持搜索")
        plugin_records = [record]
    else:
        plugin_records = loader.get_search_plugins()

    if not plugin_records:
        return []

    try:
        flat = await execute_search_with_records(plugin_records, q, limit)
    except PluginUpstreamError as exc:
        logger.warning("插件搜索上游异常: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    except PluginParseError as exc:
        logger.warning("插件搜索解析失败: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    return [SearchResultOut(**d) for d in flat]


@router.post("/download", response_model=dict)
async def download_track(
    body: DownloadRequest,
    _user: models.User = Depends(get_current_user),
):
    """
    调用搜索插件的下载功能将外部曲目入库。
    metadata_override 可覆盖插件解析到的元数据（通常来自前一步搜索结果）。
    """
    from plugins.base import SearchPlugin

    record = _require_plugin_record(body.plugin_id)
    if not record.enabled:
        raise HTTPException(409, f"插件 {body.plugin_id!r} 当前已禁用")
    if record.error:
        raise HTTPException(409, f"插件 {body.plugin_id!r} 加载失败: {record.error}")
    if not isinstance(record.instance, SearchPlugin):
        raise HTTPException(400, f"插件 {body.plugin_id!r} 不支持搜索/下载")

    try:
        logger.info(
            "调用搜索插件下载 plugin_id=%s source_id=%r",
            body.plugin_id,
            body.source_id,
        )
        result = await record.instance.download(body.source_id, body.metadata_override)
    except NotImplementedError:
        raise HTTPException(400, f"插件 {body.plugin_id!r} 未实现下载功能")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except PluginUpstreamError as exc:
        logger.warning("插件下载上游异常: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    except PluginParseError as exc:
        logger.warning("插件下载解析失败: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.warning("插件下载失败: %s", exc)
        raise HTTPException(502, f"插件下载失败: {exc}")

    return result


@router.post("/metadata/lookup", response_model=list[MetadataResultOut])
async def lookup_metadata(
    body: MetadataLookupRequest,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(get_admin_user),
):
    """
    对指定曲目调用元数据插件，返回候选元数据列表供用户选择后确认。
    确认后由前端调用 PUT /admin/tracks/{id} 将结果写入库。

    查询顺序：优先使用 Chromaprint 指纹（更精确），指纹缺失或匹配失败时
    回退到标题+艺术家名搜索。
    """
    from plugins.base import MetadataPlugin

    track = db.query(models.Track).filter(models.Track.id == body.track_id).first()
    if not track:
        raise HTTPException(404, "曲目不存在")

    # 确定要调用的元数据插件列表
    if body.plugin_id:
        record = _require_plugin_record(body.plugin_id)
        if not record.enabled:
            raise HTTPException(409, f"插件 {body.plugin_id!r} 当前已禁用")
        if record.error:
            raise HTTPException(409, f"插件 {body.plugin_id!r} 加载失败: {record.error}")
        if not isinstance(record.instance, MetadataPlugin):
            raise HTTPException(400, f"插件 {body.plugin_id!r} 不支持元数据查询")
        plugins_to_query = [(body.plugin_id, record.instance)]
    else:
        plugins_to_query = [
            (plugin_id, record.instance)
            for plugin_id, record in loader.all_plugins().items()
            if record.enabled and isinstance(record.instance, MetadataPlugin)
        ]

    if not plugins_to_query:
        return []

    artist_name = track.artist.name if track.artist else ""

    async def _query_one(plugin_id: str, p: MetadataPlugin):
        # 优先指纹查询
        if track.audio_fingerprint and track.duration_sec > 0:
            logger.info(
                "调用元数据插件(管理) lookup_by_fingerprint plugin=%s track_id=%s",
                plugin_id,
                track.id,
            )
            result = await p.lookup_by_fingerprint(
                track.audio_fingerprint, duration_sec=track.duration_sec
            )
            if result:
                return plugin_id, result
        # 回退到标题+艺术家搜索
        logger.info(
            "调用元数据插件(管理) lookup_by_info plugin=%s track_id=%s",
            plugin_id,
            track.id,
        )
        result = await p.lookup_by_info(track.title, artist_name)
        return plugin_id, result

    outcomes = await asyncio.gather(
        *[_query_one(pid, p) for pid, p in plugins_to_query],
        return_exceptions=True,
    )

    out = []
    for item in outcomes:
        if isinstance(item, Exception):
            continue
        plugin_id, result = item
        if result is None:
            continue
        out.append(MetadataResultOut(
            plugin_id=plugin_id,
            title=result.title,
            artists=result.artists,
            album=result.album,
            track_number=result.track_number,
            release_date=result.release_date,
            lyrics=result.lyrics,
            cover_url=result.cover_url,
            confidence=result.confidence,
        ))

    # 置信度从高到低排序
    out.sort(key=lambda r: r.confidence, reverse=True)
    return out


@router.get("/{plugin_id}", response_model=PluginDetail)
def get_plugin_detail(
    plugin_id: str,
    _admin: models.User = Depends(get_admin_user),
):
    return _plugin_detail(_require_plugin_record(plugin_id))


@router.put("/{plugin_id}/config", response_model=PluginDetail)
def update_plugin_config(
    plugin_id: str,
    body: PluginConfigUpdate,
    _admin: models.User = Depends(get_admin_user),
):
    try:
        record = loader.save_config(plugin_id, body.config)
    except KeyError:
        raise HTTPException(404, f"插件 {plugin_id!r} 不存在")
    return _plugin_detail(record)


@router.post("/{plugin_id}/enable", response_model=PluginDetail)
def enable_plugin(
    plugin_id: str,
    _admin: models.User = Depends(get_admin_user),
):
    try:
        record = loader.set_enabled(plugin_id, True)
    except KeyError:
        raise HTTPException(404, f"插件 {plugin_id!r} 不存在")
    return _plugin_detail(record)


@router.post("/{plugin_id}/disable", response_model=PluginDetail)
def disable_plugin(
    plugin_id: str,
    _admin: models.User = Depends(get_admin_user),
):
    try:
        record = loader.set_enabled(plugin_id, False)
    except KeyError:
        raise HTTPException(404, f"插件 {plugin_id!r} 不存在")
    return _plugin_detail(record)


@router.post("/{plugin_id}/reload", response_model=PluginDetail)
def reload_plugin(
    plugin_id: str,
    _admin: models.User = Depends(get_admin_user),
):
    try:
        record = loader.reload_plugin(plugin_id)
    except KeyError:
        raise HTTPException(404, f"插件 {plugin_id!r} 不存在")
    return _plugin_detail(record)
