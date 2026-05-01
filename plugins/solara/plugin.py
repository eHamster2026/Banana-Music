"""
plugins/solara/plugin.py
Solara Music 插件 — 搜索和下载。

Solara 服务通过 /proxy?types=<TYPE>&... 代理 NetEase / Kuwo / JOOX 等源。
API 参考：reference/solara 源代码。
"""

from __future__ import annotations

import asyncio
import random
import string
import tempfile
import urllib.parse
from pathlib import Path
from typing import Optional

import httpx

from plugins.base import (
    PluginManifest,
    SearchPlugin,
    SearchResult,
    TrackMeta,
)
from plugins.errors import PluginParseError, PluginUpstreamError

MANIFEST = PluginManifest(
    id="solara",
    name="Solara Music",
    version="1.0.0",
    capabilities=["search"],
)

_SUPPORTED_SOURCES = ("netease", "kuwo", "joox")

# 支持的音频扩展名（与主程序 upload.py 保持一致）
_SUPPORTED_EXTS = {".mp3", ".flac", ".m4a", ".aac", ".ogg", ".wav"}

_CONTENT_TYPE_EXT = {
    "audio/mpeg":  ".mp3",
    "audio/mp3":   ".mp3",
    "audio/flac":  ".flac",
    "audio/x-flac": ".flac",
    "audio/mp4":   ".m4a",
    "audio/aac":   ".aac",
    "audio/ogg":   ".ogg",
    "audio/wav":   ".wav",
    "audio/x-wav": ".wav",
}


def _sig() -> str:
    """Solara 需要 s= 随机签名参数，内容无要求。"""
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=16))


def _ext_from_content_type(ct: str) -> str:
    return _CONTENT_TYPE_EXT.get(ct.split(";")[0].strip().lower(), "")


def _ext_from_url(url: str) -> str:
    path = urllib.parse.urlparse(url).path.lower()
    for ext in _SUPPORTED_EXTS:
        if path.endswith(ext):
            return ext
    return ""


def _is_kuwo_http_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False
    hostname = (parsed.hostname or "").lower()
    return parsed.scheme == "http" and (
        hostname == "kuwo.cn" or hostname.endswith(".kuwo.cn")
    )


def _unwrap_list_payload(data: dict | list) -> list:
    """
    Solara /proxy 可能直接返回 list，也可能包在 { data: [...] } 等字段里。
    顶层非 list 时若仍解析不出列表，返回 []。
    """
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    for key in ("data", "list", "result", "songs", "songList", "records"):
        v = data.get(key)
        if isinstance(v, list):
            return v
        if isinstance(v, dict):
            inner = v.get("list") or v.get("songs") or v.get("data")
            if isinstance(inner, list):
                return inner
    return []


def _song_id(item: dict) -> str:
    for k in ("id", "songid", "song_id", "mid", "track_id"):
        v = item.get(k)
        if v is None or v == "":
            continue
        return str(v)
    return ""


def _song_title(item: dict) -> str:
    return (
        item.get("name")
        or item.get("title")
        or item.get("songname")
        or item.get("songName")
        or ""
    )


def _stringify_field(value: object) -> str:
    """
    Solara 搜索结果里的 artist / album 可能是：
    - str
    - list[str]
    - list[dict{name}]
    - dict{name}
    统一转成稳定的展示字符串，避免响应模型校验失败。
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        for key in ("name", "title", "text", "value", "artist", "album"):
            text = _stringify_field(value.get(key))
            if text:
                return text
        return ""
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            text = _stringify_field(item)
            if text and text not in parts:
                parts.append(text)
        return " / ".join(parts)
    return str(value)


def _song_artist(item: dict) -> str:
    for key in ("artist", "singer", "artists", "author"):
        text = _stringify_field(item.get(key))
        if text:
            return text
    return ""


def _song_album(item: dict) -> str:
    for key in ("album", "al", "albumName", "album_name"):
        text = _stringify_field(item.get(key))
        if text:
            return text
    return ""


def _upstream_business_error(raw: dict) -> bool:
    """上游用业务 code 表示失败（非空列表场景）。"""
    c = raw.get("code", raw.get("errno"))
    if c is None:
        return False
    if c in (0, 200, "200", "ok", "OK"):
        return False
    return True


def _legitimate_empty_list(raw: dict | list) -> bool:
    """可解析结构存在且列表为空（无匹配歌曲），视为正常空结果。"""
    if raw == []:
        return True
    if not isinstance(raw, dict):
        return False
    if _upstream_business_error(raw):
        return False
    for key in ("data", "list", "result", "songs", "songList", "records"):
        v = raw.get(key)
        if isinstance(v, list) and len(v) == 0:
            return True
        if isinstance(v, dict):
            inner = v.get("list") or v.get("songs") or v.get("data")
            if isinstance(inner, list) and len(inner) == 0:
                return True
    return False


class SolaraPlugin(SearchPlugin):
    manifest = MANIFEST

    # ── 配置快捷访问 ──────────────────────────────────────────

    def _base_url(self) -> str:
        return self.ctx.config.get("base_url", "http://172.24.245.77:3001").rstrip("/")

    def _source(self) -> str:
        return str(self.ctx.config.get("source", "all")).strip() or "all"

    def _sources(self) -> list[str]:
        source = self._source().lower()
        if source == "all":
            return list(_SUPPORTED_SOURCES)
        if source in _SUPPORTED_SOURCES:
            return [source]
        self.ctx.log("warning", f"Solara 配置 source={source!r} 不支持，已回退为 all")
        return list(_SUPPORTED_SOURCES)

    def _bitrate(self) -> str:
        """
        返回传给 Solara /proxy types=url 的 br 参数。
        配置里使用 flac；上游仍使用 999 表示无损（兼容旧配置中的 999）。
        """
        raw = self.ctx.config.get("bitrate", "flac")
        if raw in ("flac", "999"):
            return "999"
        return str(raw)

    def _download_url(self, audio_url: str) -> str:
        """Mirror Solara Web: Kuwo HTTP audio must be fetched through /proxy?target=..."""
        if _is_kuwo_http_url(audio_url):
            target = urllib.parse.quote(audio_url, safe="")
            return f"{self._base_url()}/proxy?target={target}"
        return audio_url

    def setup(self, ctx) -> None:
        super().setup(ctx)
        url = f"{self._base_url()}/proxy"
        sources = self._sources()
        self.ctx.log(
            "info",
            f"调用 Solara 连通性探测 GET {url} sources={sources!r}",
        )
        last_status = None
        with httpx.Client(timeout=5.0) as client:
            for source in sources:
                params = {
                    "s": _sig(),
                    "types": "search",
                    "source": source,
                    "name": "__banana_music_probe__",
                    "count": 1,
                    "pages": 1,
                }
                try:
                    resp = client.get(url, params=params)
                except httpx.RequestError as exc:
                    raise PluginUpstreamError(f"Solara 不可达: {exc}") from exc
                last_status = resp.status_code
                if resp.status_code < 500:
                    self.ctx.log(
                        "info",
                        f"Solara 服务已连接: {self._base_url()} "
                        f"(检测 source={source!r} HTTP {resp.status_code})",
                    )
                    return
        raise PluginUpstreamError(f"Solara 服务异常 HTTP {last_status}")

    # ── 内部 API 调用 ─────────────────────────────────────────

    async def _proxy_get(self, client: httpx.AsyncClient, **params) -> dict | list:
        params["s"] = _sig()
        url = f"{self._base_url()}/proxy"
        ptype = params.get("types", "?")
        if ptype == "search":
            detail = (
                f"source={params.get('source')!r} "
                f"name={params.get('name', '')[:120]!r} "
                f"count={params.get('count')}"
            )
        elif ptype == "url":
            detail = f"id={params.get('id')!r} source={params.get('source')!r} br={params.get('br')!r}"
        else:
            detail = repr({k: params[k] for k in sorted(params) if k != "s"})[:200]
        self.ctx.log("info", f"调用 Solara /proxy types={ptype!r} {detail}")
        try:
            resp = await client.get(url, params=params, timeout=15)
        except httpx.RequestError as exc:
            self.ctx.log("warning", f"Solara 请求失败: {exc}")
            raise PluginUpstreamError(f"请求 Solara 失败: {exc}") from exc

        if resp.status_code >= 400:
            snippet = (resp.text or "")[:500]
            self.ctx.log(
                "warning",
                f"Solara 非正常 HTTP 响应: {resp.status_code} {snippet[:240]!r}",
            )
            raise PluginUpstreamError(
                f"Solara 返回 HTTP {resp.status_code}: {snippet}"
            )

        try:
            return resp.json()
        except ValueError as exc:
            raise PluginParseError(
                f"Solara 响应不是合法 JSON: {exc}"
            ) from exc

    def _parse_search_results(
        self,
        raw: dict | list,
        *,
        source: str,
        query: str,
    ) -> list[SearchResult]:
        if not isinstance(raw, (dict, list)):
            raise PluginParseError(
                f"Solara 搜索响应类型异常: {type(raw).__name__!r}"
            )

        if isinstance(raw, dict) and _upstream_business_error(raw):
            msg = raw.get("message") or raw.get("msg") or raw.get("error") or str(raw)[:300]
            self.ctx.log("warning", f"Solara 业务错误: {msg}")
            raise PluginUpstreamError(f"Solara 业务错误: {msg}")

        items = _unwrap_list_payload(raw)

        if not items:
            if _legitimate_empty_list(raw):
                return []
            if isinstance(raw, dict) and not any(
                k in raw for k in ("data", "list", "result", "songs", "songList", "records")
            ):
                raise PluginParseError(
                    f"无法从响应中解析歌曲列表: keys={list(raw.keys())[:20]}"
                )
            raise PluginParseError(
                f"无法解析搜索响应结构: {type(raw).__name__}"
            )

        results = []
        for item in items:
            if not isinstance(item, dict):
                continue
            item_source = item.get("source", source)
            track_id = _song_id(item)
            if not track_id:
                continue

            results.append(SearchResult(
                source_id=f"{item_source}:{track_id}",
                title=_song_title(item),
                artist=_song_artist(item),
                album=_song_album(item),
                duration_sec=0.0,   # 各源字段不一致，搜索阶段不强行换算
                cover_url=None,     # 需单独调用 pic 端点，搜索阶段不预取
            ))
        if items and not results:
            self.ctx.log(
                "warning",
                f"搜索返回 {len(items)} 条但均缺少曲目 id: q={query!r}",
            )
            raise PluginParseError("搜索结果条目均缺少可用的曲目 id")
        return results

    # ── SearchPlugin ──────────────────────────────────────────

    async def _search_source(
        self,
        client: httpx.AsyncClient,
        *,
        source: str,
        query: str,
        limit: int,
    ) -> list[SearchResult]:
        raw = await self._proxy_get(
            client,
            types="search",
            source=source,
            name=query,
            count=limit,
            pages=1,
        )
        return self._parse_search_results(raw, source=source, query=query)

    async def search(self, query: str, limit: int = 20) -> list[SearchResult]:
        sources = self._sources()
        self.ctx.log("info", f"Solara 同时搜索 sources={sources!r} q={query!r}")

        async with httpx.AsyncClient() as client:
            gathered = await asyncio.gather(
                *[
                    self._search_source(
                        client,
                        source=source,
                        query=query,
                        limit=limit,
                    )
                    for source in sources
                ],
                return_exceptions=True,
            )

        results: list[SearchResult] = []
        errors: list[BaseException] = []
        for source, value in zip(sources, gathered):
            if isinstance(value, BaseException):
                self.ctx.log("warning", f"Solara 源 {source!r} 搜索失败: {value}")
                errors.append(value)
                continue
            results.extend(value)

        if not results and errors:
            raise errors[0]
        return results

    # ── DownloadPlugin ────────────────────────────────────────

    async def download(
        self, source_id: str, metadata: Optional[dict] = None
    ) -> dict:
        """
        下载流程：
        1. 解析 source_id → source + track_id
        2. 调用 /proxy?types=url 获取音频直链
        3. 流式下载到临时文件（支持 Kuwo 代理 URL）
        4. 在线程池中调用 ctx.ingest_file() 入库（含转码、去重）
        """
        parts = source_id.split(":", 1)
        if len(parts) != 2:
            raise ValueError(f"无效的 source_id 格式: {source_id!r}（期望 'source:id'）")
        source, track_id = parts

        # 1. 获取音频 URL
        async with httpx.AsyncClient() as client:
            url_data = await self._proxy_get(
                client,
                types="url",
                id=track_id,
                source=source,
                br=self._bitrate(),
            )

        if not isinstance(url_data, dict):
            raise ValueError(f"获取 URL 失败，服务返回: {url_data!r}")

        audio_url: Optional[str] = url_data.get("url")
        if not audio_url:
            raise ValueError(f"服务未返回可用的音频 URL（source_id={source_id!r}）")

        # Kuwo 返回的相对路径代理 URL，需拼接 base_url
        if audio_url.startswith("/"):
            audio_url = self._base_url() + audio_url

        download_url = self._download_url(audio_url)
        if download_url != audio_url:
            self.ctx.log("info", f"Solara 音频地址已切换为代理下载: {source_id}")

        self.ctx.log("info", f"下载 {source_id} → {download_url[:80]}…")

        # 2. 流式下载到临时文件
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        }
        if source == "kuwo" or _is_kuwo_http_url(audio_url):
            headers["Referer"] = "https://www.kuwo.cn/"

        tmp_path: Optional[Path] = None
        try:
            try:
                async with httpx.AsyncClient(
                    follow_redirects=True, timeout=120
                ) as client:
                    async with client.stream("GET", download_url, headers=headers) as resp:
                        resp.raise_for_status()
                        ct = resp.headers.get("content-type", "")
                        ext = (
                            _ext_from_content_type(ct)
                            or _ext_from_url(audio_url)
                            or _ext_from_url(download_url)
                            or ".mp3"
                        )
                        with tempfile.NamedTemporaryFile(
                            suffix=ext, delete=False
                        ) as tmp:
                            tmp_path = Path(tmp.name)
                            async for chunk in resp.aiter_bytes(65536):
                                tmp.write(chunk)
            except httpx.RequestError as exc:
                self.ctx.log("warning", f"Solara 音频直链下载失败: {exc}")
                raise PluginUpstreamError(f"下载音频失败: {exc}") from exc

            # 3. 构建元数据（metadata_override 由前端从搜索结果传入）
            ov_artists = metadata.get("artists") if metadata else None
            artists_list = (
                [str(x).strip() for x in ov_artists if str(x).strip()]
                if isinstance(ov_artists, list)
                else []
            )
            meta = TrackMeta(
                title=metadata.get("title", "")   if metadata else "",
                artist=metadata.get("artist", "") if metadata else "",
                artists=artists_list,
                album=metadata.get("album")       if metadata else None,
                track_number=metadata.get("track_number", 0) if metadata else 0,
                release_date=metadata.get("release_date")    if metadata else None,
            )

            # 4. ingest_file 是同步阻塞操作（含转码），跑在线程池中
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, self.ctx.ingest_file, tmp_path, meta
            )
            return result

        finally:
            if tmp_path and tmp_path.exists():
                tmp_path.unlink(missing_ok=True)


# 模块级暴露给 loader 的插件实例
plugin = SolaraPlugin()
