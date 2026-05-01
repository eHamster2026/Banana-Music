"""
plugins/musicbrainz/plugin.py
MusicBrainz 元数据插件。

支持两种查询方式：
  1. lookup_by_fingerprint — 通过 Chromaprint 指纹查 AcoustID → 获取 MusicBrainz 元数据
  2. lookup_by_info        — 通过标题/艺术家名搜索 MusicBrainz

API 约束：
  MusicBrainz: 最多 1 req/s，必须携带有意义的 User-Agent
  AcoustID:    官方建议最多 3 req/s，本插件仅此一档限速（与是否填写 API Key 无关）

API 文档：https://musicbrainz.org/doc/MusicBrainz_API
AcoustID 文档：https://acoustid.org/webservice
"""

from __future__ import annotations

import asyncio
import time as _time
from typing import Optional

import httpx

from plugins.base import MetadataPlugin, MetadataResult, PluginManifest

MANIFEST = PluginManifest(
    id="musicbrainz",
    name="MusicBrainz",
    version="1.0.0",
    capabilities=["metadata"],
)

MB_BASE       = "https://musicbrainz.org/ws/2"
ACOUSTID_BASE = "https://api.acoustid.org/v2"

# AcoustID 要求 client 为已注册应用的 key；任意字符串会报 invalid API key。
# 官方文档示例 key（可能定期失效），仅作「零配置」兜底；稳定使用请在插件中填写 acoustid_api_key。
_ACOUSTID_DOCS_EXAMPLE_CLIENT = "71W9SJdajAI"


def _acoustid_error_detail(resp: httpx.Response) -> str:
    """解析 AcoustID 错误响应（常见 HTTP 400：code 3=指纹无效，code 4=API key 无效）。"""
    try:
        j = resp.json()
        if isinstance(j, dict):
            err = j.get("error")
            if isinstance(err, dict):
                return f"code={err.get('code')} message={err.get('message')!r}"
            if j.get("status") == "error":
                return repr(j)[:500]
        return str(j)[:500]
    except Exception:
        return (resp.text or "")[:500]


# ── 速率限制器 ────────────────────────────────────────────────

class _RateLimiter:
    """asyncio 速率限制：保证请求间隔不低于 min_interval 秒。"""

    def __init__(self, min_interval: float):
        self._lock = asyncio.Lock()
        self._last: float = 0.0
        self._interval = min_interval

    async def __aenter__(self):
        await self._lock.acquire()
        elapsed = _time.monotonic() - self._last
        wait = self._interval - elapsed
        if wait > 0:
            await asyncio.sleep(wait)

    async def __aexit__(self, *_):
        self._last = _time.monotonic()
        self._lock.release()


# ── 插件实现 ──────────────────────────────────────────────────

class MusicBrainzPlugin(MetadataPlugin):
    manifest = MANIFEST

    # MusicBrainz 1 req/s；AcoustID 官方 ≤3 req/s → 间隔 ≥1/3 秒
    _mb_limiter = _RateLimiter(1.0)
    _acoustid_limiter = _RateLimiter(0.34)

    def setup(self, ctx) -> None:
        super().setup(ctx)
        # MusicBrainz 无需启动时自检（公开 API，按需访问）；直接注册流水线回调
        ctx.register_for_stage("fingerprint_lookup", self.lookup_by_fingerprint)
        ctx.register_for_stage("info_lookup", self.lookup_by_info)

    # ── 配置快捷访问 ──────────────────────────────────────────

    def _user_agent(self) -> str:
        return self.ctx.config.get("user_agent", "BananaMusic/1.0 (banana-music-musicbrainz-plugin)")

    def _acoustid_key(self) -> str:
        return self.ctx.config.get("acoustid_api_key", "")

    def _acoustid_client(self) -> str:
        """POST 的 client 参数：用户 key 优先，否则用文档示例 key（服务端不接受空或任意字符串）。"""
        k = self._acoustid_key().strip()
        return k if k else _ACOUSTID_DOCS_EXAMPLE_CLIENT

    def _min_score_mb(self) -> float:
        return float(self.ctx.config.get("min_score_mb", 70))

    def _min_score_acoustid(self) -> float:
        return float(self.ctx.config.get("min_score_acoustid", 0.6))

    # ── 内部 HTTP 工具 ────────────────────────────────────────

    async def _mb_get(self, path: str, **params) -> dict:
        """向 MusicBrainz API 发起 GET 请求，自动限速并附加必要头部。"""
        params["fmt"] = "json"
        self.ctx.log("info", f"调用 MusicBrainz API GET {path!r}")
        async with self._mb_limiter:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{MB_BASE}/{path}",
                    params=params,
                    headers={"User-Agent": self._user_agent()},
                )
                resp.raise_for_status()
                return resp.json()

    async def _acoustid_lookup(self, fingerprint_str: str, duration_sec: int) -> dict:
        """向 AcoustID 发起指纹查询，自动限速（≤3 req/s）。"""
        self.ctx.log(
            "info",
            f"调用 AcoustID lookup duration_sec={duration_sec} "
            f"fingerprint_chars={len(fingerprint_str)}",
        )
        async with self._acoustid_limiter:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{ACOUSTID_BASE}/lookup",
                    data={
                        "client":      self._acoustid_client(),
                        "fingerprint": fingerprint_str,
                        "duration":    str(duration_sec),
                        "meta":        "recordings+releasegroups",
                    },
                    headers={"User-Agent": self._user_agent()},
                )
                resp.raise_for_status()
                return resp.json()

    # ── MetadataPlugin 实现 ───────────────────────────────────

    async def lookup_by_fingerprint(
        self,
        fingerprint: bytes,
        duration_sec: int = 0,
    ) -> Optional[MetadataResult]:
        """
        通过 Chromaprint 指纹查询 AcoustID，返回最佳匹配的元数据。

        fingerprint: fpcalc 默认（压缩）输出中 FINGERPRINT= 右侧的字符串，已 encode() 为 bytes
        duration_sec: 必须 > 0，否则 AcoustID 无法匹配
        """
        if not fingerprint or duration_sec <= 0:
            self.ctx.log(
                "warning",
                f"指纹或时长无效，跳过 AcoustID（duration_sec={duration_sec} len={len(fingerprint) if fingerprint else 0}）",
            )
            return None

        fp_str = fingerprint.decode("utf-8").strip()

        try:
            data = await self._acoustid_lookup(fp_str, duration_sec)
        except httpx.HTTPStatusError as exc:
            detail = _acoustid_error_detail(exc.response)
            self.ctx.log(
                "warning",
                f"AcoustID HTTP {exc.response.status_code}: {detail}",
            )
            return None
        except Exception as exc:
            self.ctx.log("warning", f"AcoustID 请求异常: {exc}")
            return None

        if data.get("status") != "ok":
            self.ctx.log("warning", f"AcoustID 返回非 ok 状态: {data.get('status')}")
            return None

        results = data.get("results", [])
        if not results:
            self.ctx.log(
                "info",
                f"AcoustID 无匹配：库中无该指纹或时长偏差过大（duration_sec={duration_sec}）。"
                "指纹格式应为 fpcalc 默认压缩输出（勿用 -raw）。",
            )
            return None

        # 取置信度最高的结果
        best = max(results, key=lambda r: r.get("score", 0))
        score: float = best.get("score", 0)

        if score < self._min_score_acoustid():
            self.ctx.log(
                "info",
                f"AcoustID 有候选但置信度过低：score={score:.3f} < min_score_acoustid="
                f"{self._min_score_acoustid():.3f}，可在插件配置中调低阈值",
            )
            return None

        recordings = best.get("recordings", [])
        if not recordings:
            self.ctx.log(
                "info",
                "AcoustID 返回结果中无 recordings 字段，无法解析元数据",
            )
            return None

        rec = recordings[0]

        # 提取艺术家
        artists = rec.get("artists", [])
        artist_name = artists[0]["name"] if artists else ""

        # 提取专辑（来自 releasegroups）
        rgs = rec.get("releasegroups", [])
        album_title = rgs[0]["title"] if rgs else None

        # 提取发行年份（releasegroup 可能包含 releases）
        release_date: Optional[str] = None
        if rgs and rgs[0].get("releases"):
            d = rgs[0]["releases"][0].get("date", {})
            if isinstance(d, dict) and d.get("year"):
                parts = [str(d["year"])]
                if d.get("month"):
                    parts.append(f"{d['month']:02d}")
                if d.get("day"):
                    parts.append(f"{d['day']:02d}")
                release_date = "-".join(parts)

        duration = rec.get("duration", 0)

        self.ctx.log(
            "info",
            f"AcoustID 匹配: {rec.get('title')!r} — {artist_name!r} "
            f"(score={score:.2f}, mbid={rec.get('id')})"
        )

        return MetadataResult(
            title=rec.get("title"),
            artists=[artist_name] if artist_name else [],
            album=album_title,
            release_date=release_date,
            duration_sec=duration if duration > 0 else None,
            confidence=score,
        )

    async def lookup_by_info(
        self, title: str, artist: str
    ) -> Optional[MetadataResult]:
        """
        通过标题和艺术家名搜索 MusicBrainz Recording，返回最佳匹配。

        搜索响应中已包含 artist-credit 和 releases，无需二次请求。
        """
        if not title:
            return None

        # 构造 Lucene 查询，特殊字符转义
        def _esc(s: str) -> str:
            for ch in r'+-&|!(){}[]^"~*?:\\/':
                s = s.replace(ch, f"\\{ch}")
            return s

        if artist:
            query = f'recording:"{_esc(title)}" AND artist:"{_esc(artist)}"'
        else:
            query = f'recording:"{_esc(title)}"'

        try:
            data = await self._mb_get("recording", query=query, limit=5)
        except httpx.HTTPStatusError as exc:
            self.ctx.log("warning", f"MusicBrainz 搜索失败: {exc.response.status_code}")
            return None
        except Exception as exc:
            self.ctx.log("warning", f"MusicBrainz 搜索异常: {exc}")
            return None

        recordings = data.get("recordings", [])
        if not recordings:
            return None

        best = recordings[0]
        score: float = float(best.get("score", 0))

        if score < self._min_score_mb():
            self.ctx.log("debug", f"MusicBrainz 匹配分 {score} 低于阈值，跳过")
            return None

        # ── 提取字段 ──────────────────────────────────────────

        rec_title: Optional[str] = best.get("title")

        # 艺术家：取第一个 artist-credit
        artist_name: Optional[str] = None
        credits = best.get("artist-credit", [])
        if credits:
            ac = credits[0]
            # artist-credit 可能是字符串（joinphrase）或对象
            if isinstance(ac, dict):
                artist_name = ac.get("name") or ac.get("artist", {}).get("name")

        # 专辑、发行日期、曲目编号：来自第一个 Official 发行，找不到则用第一个
        album_title:  Optional[str] = None
        release_date: Optional[str] = None
        track_number: Optional[int] = None
        lyrics:       Optional[str] = None

        releases = best.get("releases", [])
        if releases:
            # 优先取状态为 Official 的发行
            official = [r for r in releases if r.get("status") == "Official"]
            rel = official[0] if official else releases[0]

            album_title  = rel.get("title")
            release_date = rel.get("date") or best.get("first-release-date")

            # 曲目编号：从 media[].track-offset + 1 推算（如有）
            for medium in rel.get("media", []):
                for track in medium.get("tracks", []):
                    if track.get("id") == best.get("id") or \
                       track.get("recording", {}).get("id") == best.get("id"):
                        try:
                            track_number = int(track.get("position", track.get("number", 0)))
                        except (TypeError, ValueError):
                            pass
                        break

        # 时长（ms → s）
        length_ms = best.get("length", 0)
        duration = int(length_ms / 1000) if length_ms else None

        self.ctx.log(
            "info",
            f"MusicBrainz 匹配: {rec_title!r} — {artist_name!r} "
            f"(score={score}, mbid={best.get('id')})"
        )

        return MetadataResult(
            title=rec_title,
            artists=[artist_name] if artist_name else [],
            album=album_title,
            track_number=track_number,
            release_date=release_date,
            lyrics=lyrics,
            confidence=score / 100.0,
        )


# loader 约定：模块级 `plugin` 变量
plugin = MusicBrainzPlugin()
