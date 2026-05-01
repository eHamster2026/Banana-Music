"""
services/pipeline.py

元数据清洗流水线：回调注册表 + 配置加载 + 阶段执行。

设计原则：
  - 插件在 setup() 自检通过后通过 ctx.register_for_stage() 注册回调
  - 主程序流水线只管按配置触发回调，不关心插件的内部类型
  - 配置从 data/pipeline.json 读取；文件不存在时按 manifest.pipeline_stages 自动生成

流水线阶段（stage_id）：
  parse_upload       — 上传时清洗文件名/标签（mode=first，取第一个非 None 结果）
  fingerprint_lookup — 指纹写入后查外部元数据库（mode=best，并行取最高置信度）
  info_lookup        — 通过标题/艺人名查外部元数据库（mode=best，默认 disabled）
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from plugins.base import MetadataResult, TagDict

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent.parent / "data"
_PIPELINE_CONFIG_PATH = _DATA_DIR / "pipeline.json"

# ── 配置数据结构 ──────────────────────────────────────────────

@dataclass
class StageConfig:
    id: str
    enabled: bool = True
    plugins: list[str] = field(default_factory=list)   # 有序插件 ID 列表
    mode: Literal["first", "best"] = "first"
    min_confidence: float = 0.55
    max_concurrent: int = 0   # 0 = 不限并发；parse_upload 建议设为 1（Ollama 顺序处理）


@dataclass
class PipelineConfig:
    version: int = 1
    stages: list[StageConfig] = field(default_factory=list)

    def get_stage(self, stage_id: str) -> Optional[StageConfig]:
        for s in self.stages:
            if s.id == stage_id:
                return s
        return None


# ── 全局回调注册表 ────────────────────────────────────────────

class PipelineRegistry:
    """
    存储各流水线阶段的已注册回调。
    每条记录为 (plugin_id, callback)；同一 plugin+stage 覆盖旧条目（reload 安全）。
    """

    def __init__(self) -> None:
        # stage_id -> [(plugin_id, callback), ...]
        self._callbacks: dict[str, list[tuple[str, Callable]]] = {}

    def register(self, plugin_id: str, stage: str, callback: Callable) -> None:
        """覆盖式注册：同一 plugin+stage 替换旧条目。"""
        if stage not in self._callbacks:
            self._callbacks[stage] = []
        self._callbacks[stage] = [
            (pid, cb) for pid, cb in self._callbacks[stage] if pid != plugin_id
        ]
        self._callbacks[stage].append((plugin_id, callback))
        logger.info("流水线回调已注册: plugin=%s stage=%s", plugin_id, stage)

    def unregister_plugin(self, plugin_id: str) -> None:
        """在插件重新加载或禁用时清理其所有注册。"""
        for stage_list in self._callbacks.values():
            stage_list[:] = [(pid, cb) for pid, cb in stage_list if pid != plugin_id]

    def get_stage_callbacks(
        self, stage_id: str, ordered_plugins: list[str]
    ) -> list[tuple[str, Callable]]:
        """
        返回该阶段有效的 (plugin_id, callback) 列表，
        按 ordered_plugins 指定的顺序排列；未注册的插件跳过。
        """
        registered = dict(self._callbacks.get(stage_id, []))
        return [(pid, registered[pid]) for pid in ordered_plugins if pid in registered]

    def registered_stages(self) -> dict[str, list[str]]:
        """返回 {stage_id: [plugin_id, ...]} 的快照，用于调试/日志。"""
        return {s: [pid for pid, _ in cbs] for s, cbs in self._callbacks.items() if cbs}


_registry = PipelineRegistry()
_config: Optional[PipelineConfig] = None   # 惰性加载缓存

# ── 每阶段并发信号量（infer lazily，事件循环安全）────────────────
_stage_semaphores: dict[str, asyncio.Semaphore] = {}


def _get_semaphore(stage_id: str, max_concurrent: int) -> Optional[asyncio.Semaphore]:
    """
    返回该阶段的 Semaphore；max_concurrent <= 0 表示不限并发，返回 None。
    首次调用时惰性创建，同一进程复用同一对象（事件循环不变则安全）。
    """
    if max_concurrent <= 0:
        return None
    if stage_id not in _stage_semaphores:
        _stage_semaphores[stage_id] = asyncio.Semaphore(max_concurrent)
    return _stage_semaphores[stage_id]


def get_registry() -> PipelineRegistry:
    return _registry


# ── 配置管理 ──────────────────────────────────────────────────

_STAGE_DEFAULTS: dict[str, dict] = {
    # parse_upload：LLM 推理（Ollama 顺序处理），默认限制 1 个并发避免积压超时
    "parse_upload":       {"mode": "first", "min_confidence": 0.0, "enabled": True,  "max_concurrent": 1},
    # fingerprint_lookup：网络 I/O，并行无害，Ollama 不参与此阶段
    "fingerprint_lookup": {"mode": "best",  "min_confidence": 0.55, "enabled": True,  "max_concurrent": 0},
    "info_lookup":        {"mode": "best",  "min_confidence": 0.7,  "enabled": False, "max_concurrent": 0},
}


def _max_concurrent_for_stage(stage_id: str, raw: dict) -> int:
    """
    未写 max_concurrent 时的阶段缺省：
    parse_upload 默认为 1（Ollama 等 LLM 多为单路排队；曾误为 0=无限并发会导致
    批量上传时大量并行请求、排队超过 timeout_sec 而全部超时）。
    其它阶段缺省 0（不限制）。若 JSON 显式写了 max_concurrent（含 0），以文件为准。
    """
    if "max_concurrent" in raw:
        return int(raw["max_concurrent"])
    if stage_id == "parse_upload":
        return 1
    return 0


def load_config() -> PipelineConfig:
    """读取 data/pipeline.json；不存在时由 manifest 自动生成并写入。"""
    global _config
    if _config is not None:
        return _config
    if _PIPELINE_CONFIG_PATH.exists():
        try:
            data = json.loads(_PIPELINE_CONFIG_PATH.read_text(encoding="utf-8"))
            stages = [
                StageConfig(
                    id=s["id"],
                    enabled=s.get("enabled", True),
                    plugins=s.get("plugins", []),
                    mode=s.get("mode", "first"),
                    min_confidence=float(s.get("min_confidence", 0.55)),
                    max_concurrent=_max_concurrent_for_stage(s["id"], s),
                )
                for s in data.get("stages", [])
            ]
            _config = PipelineConfig(version=data.get("version", 1), stages=stages)
            logger.info(
                "已加载流水线配置: %s (%d 阶段)",
                _PIPELINE_CONFIG_PATH, len(stages),
            )
            return _config
        except Exception as exc:
            logger.warning("流水线配置加载失败，使用默认值: %s", exc)
    _config = _default_config()
    return _config


def invalidate_config() -> None:
    """清除配置缓存，下次调用 load_config() 时重新从文件读取。"""
    global _config
    _config = None


def _default_config() -> PipelineConfig:
    """
    从当前已加载插件的 manifest.pipeline_stages 生成默认配置，并写入磁盘。
    """
    import plugins.loader as loader

    # 按阶段收集插件（按 loader 的加载顺序）
    stage_plugins: dict[str, list[str]] = {}
    for pid, record in loader.all_plugins().items():
        if not record.enabled or record.error:
            continue
        for stage in (record.manifest.pipeline_stages or []):
            stage_plugins.setdefault(stage, []).append(pid)

    stages: list[StageConfig] = []
    seen: set[str] = set()

    # 按预定义顺序生成各阶段配置
    for stage_id, defaults in _STAGE_DEFAULTS.items():
        stages.append(StageConfig(
            id=stage_id,
            enabled=defaults["enabled"],
            plugins=stage_plugins.get(stage_id, []),
            mode=defaults["mode"],
            min_confidence=defaults["min_confidence"],
            max_concurrent=defaults.get("max_concurrent", 0),
        ))
        seen.add(stage_id)

    # 附加 manifest 中声明了但不在预定义列表里的自定义阶段
    for stage_id, pids in stage_plugins.items():
        if stage_id not in seen:
            stages.append(StageConfig(id=stage_id, plugins=pids))

    cfg = PipelineConfig(stages=stages)

    # 写入磁盘供管理员查看和修改
    try:
        _DATA_DIR.mkdir(exist_ok=True)
        serialized = {
            "version": 1,
            "stages": [
                {
                    "id": s.id,
                    "enabled": s.enabled,
                    "plugins": s.plugins,
                    "mode": s.mode,
                    **({"min_confidence": s.min_confidence} if s.min_confidence > 0 else {}),
                    **({"max_concurrent": s.max_concurrent} if s.max_concurrent > 0 else {}),
                }
                for s in stages
            ],
        }
        _PIPELINE_CONFIG_PATH.write_text(
            json.dumps(serialized, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        logger.info("已生成默认流水线配置: %s", _PIPELINE_CONFIG_PATH)
    except Exception as exc:
        logger.warning("默认流水线配置写入失败: %s", exc)

    return cfg


# ── 流水线执行 ────────────────────────────────────────────────

async def run_parse_upload(
    filename_stem: str,
    raw_tags: Optional["TagDict"],
    timeout: Optional[float] = None,
) -> Optional["MetadataResult"]:
    """
    执行 parse_upload 阶段（mode=first）。

    按配置顺序调用各插件回调，取第一个非 None 结果。
    各插件 timeout 优先使用 timeout 参数，否则从插件 config.timeout_sec 读取（llm-metadata 默认 120s）。
    """
    import plugins.loader as loader

    cfg = load_config()
    stage = cfg.get_stage("parse_upload")
    if stage is None or not stage.enabled:
        return None

    callbacks = _registry.get_stage_callbacks("parse_upload", stage.plugins)
    if not callbacks:
        return None

    sem = _get_semaphore("parse_upload", stage.max_concurrent)

    for plugin_id, callback in callbacks:
        rec = loader.get_plugin(plugin_id)
        wait_sec: float = 120.0
        if timeout is not None:
            wait_sec = timeout
        elif rec is not None:
            try:
                wait_sec = float(rec.config.get("timeout_sec", 120.0))
            except (TypeError, ValueError):
                wait_sec = 120.0

        async def _invoke(pid: str = plugin_id, cb=callback, ws: float = wait_sec):
            try:
                result = await asyncio.wait_for(cb(filename_stem, raw_tags), timeout=ws)
                if result is not None:
                    logger.info(
                        "流水线 parse_upload 命中: plugin=%s stem=%r title=%r artists=%r",
                        pid, filename_stem, result.title, result.artists,
                    )
                return result
            except asyncio.TimeoutError:
                logger.warning(
                    "流水线 parse_upload 超时: plugin=%s stem=%r (%.0fs)", pid, filename_stem, ws,
                )
                return None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "流水线 parse_upload 异常: plugin=%s stem=%r: %s", pid, filename_stem, exc,
                )
                return None

        try:
            if sem is not None:
                async with sem:
                    result = await _invoke()
            else:
                result = await _invoke()
        except asyncio.CancelledError:
            raise

        if result is not None:
            return result

    return None


async def run_fingerprint_lookup(
    fingerprint: bytes,
    duration_sec: int,
) -> Optional[tuple["MetadataResult", float]]:
    """
    执行 fingerprint_lookup 阶段（mode=best）。

    并行调用所有配置中的插件回调，返回 (MetadataResult, confidence) 对。
    若所有结果置信度均低于 stage.min_confidence，返回 None。
    """
    cfg = load_config()
    stage = cfg.get_stage("fingerprint_lookup")
    if stage is None or not stage.enabled:
        return None

    callbacks = _registry.get_stage_callbacks("fingerprint_lookup", stage.plugins)
    if not callbacks:
        return None

    async def _one(plugin_id: str, callback: Callable):
        try:
            logger.info(
                "流水线 fingerprint_lookup: plugin=%s duration_sec=%s",
                plugin_id, duration_sec,
            )
            result = await callback(fingerprint, duration_sec=duration_sec)
            return plugin_id, result
        except Exception as exc:
            logger.warning(
                "流水线 fingerprint_lookup 异常: plugin=%s: %s", plugin_id, exc,
            )
            return plugin_id, None

    outcomes = await asyncio.gather(
        *[_one(pid, cb) for pid, cb in callbacks],
        return_exceptions=True,
    )

    best = None
    best_conf = 0.0
    best_pid = None
    for item in outcomes:
        if isinstance(item, Exception):
            continue
        pid, result = item
        if result is None:
            logger.info("流水线 fingerprint_lookup 无匹配: plugin=%s", pid)
            continue
        logger.info(
            "流水线 fingerprint_lookup 候选: plugin=%s title=%r artists=%r confidence=%.3f",
            pid, result.title, result.artists, result.confidence,
        )
        if result.confidence > best_conf:
            best = result
            best_conf = result.confidence
            best_pid = pid

    if best is None:
        return None

    if best_conf < stage.min_confidence:
        logger.info(
            "流水线 fingerprint_lookup 置信度不足: best_conf=%.3f < min=%.2f plugin=%s",
            best_conf, stage.min_confidence, best_pid,
        )
        return None

    logger.info(
        "流水线 fingerprint_lookup 选用: plugin=%s confidence=%.3f title=%r artists=%r",
        best_pid, best_conf, best.title, best.artists,
    )
    return best, best_conf
