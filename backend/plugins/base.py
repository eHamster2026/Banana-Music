"""
plugins/base.py
插件抽象接口和数据类型定义。
插件作者继承 SearchPlugin / MetadataPlugin，通过 self.ctx (PluginContext) 访问主程序能力。

生命周期：
  discover → _build_instance() → plugin.setup(ctx)
               ├─ 自检（失败则 raise PluginUpstreamError → loader 标记 error，不注册任何回调）
               └─ ctx.register_for_stage(stage, callback)  # 注册流水线回调
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Optional

if TYPE_CHECKING:
    from plugins.context import PluginContext


# ── 代码契约：TagDict ─────────────────────────────────────────

class TagDict(dict):
    """
    parse_upload() raw_tags 参数的类型约束（来自 Mutagen 解析的标签字典）。

    键（均为 optional）：
      title        : str | None
      artist       : str | None          — 主艺人（或未拆分的多艺人字符串）
      artists      : list[str]           — 已拆分的有序艺人列表
      album        : str | None
      track_number : int                 — 0 表示未知
      release_date : str | None          — "YYYY-MM-DD" 或 "YYYY"
      album_artist : str | None
      lyrics       : str | None
    """


# ── 数据结构 ──────────────────────────────────────────────────

@dataclass
class PluginManifest:
    id: str
    name: str
    version: str
    capabilities: list[Literal["search", "metadata"]]
    config_schema: dict = field(default_factory=dict)
    pipeline_stages: list[str] = field(default_factory=list)
    """
    插件支持的流水线阶段，用于生成默认 data/pipeline.json 配置。
    有效值: "parse_upload" | "fingerprint_lookup" | "info_lookup"
    管理员可在 pipeline.json 中覆盖实际参与的插件和顺序。
    """


@dataclass
class TrackMeta:
    """传给 ctx.ingest_file() 的元数据，插件提供的值优先于文件标签。"""
    title: str = ""
    artist: str = ""
    artists: list = field(default_factory=list)  # 有序；空则回退为 [artist]
    album: Optional[str] = None
    track_number: int = 0
    duration_sec: int = 0
    release_date: Optional[str] = None


@dataclass
class SearchResult:
    """外部平台的单条搜索结果。source_id 用于后续 download() 调用。"""
    source_id: str          # e.g. "netease:12345678"
    title: str
    artist: str
    album: str
    artists: list = field(default_factory=list)  # 有序多艺人；空则仅用 artist
    duration_sec: float = 0.0
    cover_url: Optional[str] = None
    preview_url: Optional[str] = None


@dataclass
class MetadataResult:
    title: Optional[str] = None
    artists: list = field(default_factory=list)   # 有序艺人列表，第一位为主艺人
    album: Optional[str] = None
    track_number: Optional[int] = None
    duration_sec: Optional[int] = None
    release_date: Optional[str] = None
    lyrics: Optional[str] = None
    cover_url: Optional[str] = None
    confidence: float = 0.0


# ── 插件基类 ──────────────────────────────────────────────────

class BasePlugin(ABC):
    manifest: PluginManifest
    ctx: "PluginContext"

    def setup(self, ctx: "PluginContext") -> None:
        """
        初始化钩子，由 loader 在加载时调用。

        子类应在此方法中：
          1. 调用 super().setup(ctx) 注入 ctx
          2. 执行自检（连通性、模型可用性等）；失败时 raise PluginUpstreamError
          3. 调用 ctx.register_for_stage(stage, callback) 注册流水线回调

        注意：只有自检通过后才应注册回调，确保流水线不会调用到不可用的插件。
        """
        self.ctx = ctx


class SearchPlugin(BasePlugin):
    @abstractmethod
    async def search(self, query: str, limit: int = 20) -> list[SearchResult]: ...

    async def download(
        self,
        source_id: str,
        metadata: Optional[dict] = None,
    ) -> dict:
        """
        下载音频并通过 self.ctx.ingest_file() 入库。
        metadata 为前端传入的元数据提示（来自搜索结果），格式与 TrackMeta 字段一致。
        返回 {"status": "added"|"duplicate", "track_id": N, "title": ...}
        插件不支持下载时抛出 NotImplementedError。
        """
        raise NotImplementedError


class MetadataPlugin(BasePlugin):
    async def lookup_by_fingerprint(
        self,
        fingerprint: bytes,
        duration_sec: int = 0,
    ) -> Optional[MetadataResult]:
        """
        通过 Chromaprint 指纹查询外部元数据库。

        fingerprint: fpcalc 默认（压缩）输出中 FINGERPRINT= 右侧的字符串，已 encode() 为 bytes
        duration_sec: 音轨时长（AcoustID 等查询必须，为 0 时建议跳过）

        对应流水线阶段: "fingerprint_lookup"
        """
        return None

    async def lookup_by_info(
        self, title: str, artist: str
    ) -> Optional[MetadataResult]:
        """
        通过标题和艺人名搜索外部元数据库。

        对应流水线阶段: "info_lookup"
        """
        return None

    async def parse_upload(
        self,
        filename_stem: str,
        raw_tags: Optional[TagDict] = None,
    ) -> Optional[MetadataResult]:
        """
        在文件写库前对元数据做清洗与修正。

        filename_stem: 原始文件名（不含扩展名）
        raw_tags:      Mutagen 解析出的标签（见 TagDict）；None 表示文件无嵌入标签

        返回清洗后的 MetadataResult；None 表示不干预，主程序使用原始值。

        对应流水线阶段: "parse_upload"
        """
        return None
