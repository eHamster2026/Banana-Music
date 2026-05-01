"""
plugins/loader.py
插件发现、加载和运行时注册表。

约定：
  每个插件是 plugins/<id>/ 目录，包含：
    manifest.json  — 插件声明（id、name、version、capabilities、config_schema）
    plugin.py      — 插件实现，必须在模块级别暴露 `plugin` 变量（BasePlugin 实例）
    config.json    — 可选，运行时配置（管理员通过 UI 填写）
    state.json     — 可选，运行时状态（enabled）

  config_schema.properties 中的 default 值在 config.json 缺失对应键时自动补全。
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import json
from pathlib import Path
from typing import Optional

from app_logging import logger
from plugins.errors import PluginUpstreamError
from plugins.base import (
    BasePlugin,
    MetadataPlugin,
    PluginManifest,
    SearchPlugin,
)
from plugins.context import PluginContext


@dataclass
class PluginRecord:
    manifest: PluginManifest
    plugin_dir: Path
    config: dict
    enabled: bool
    instance: Optional[BasePlugin] = None
    error: Optional[str] = None

    @property
    def loaded(self) -> bool:
        return self.instance is not None and self.error is None


_registry: dict[str, PluginRecord] = {}
_plugin_dir: Optional[Path] = None


def init(plugin_dir: Path) -> None:
    """在应用启动时调用，扫描并加载所有插件。"""
    global _plugin_dir
    _plugin_dir = plugin_dir
    _plugin_dir.mkdir(parents=True, exist_ok=True)
    _load_all()


def _json_load(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _json_dump(path: Path, data: dict) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _iter_plugin_dirs() -> list[Path]:
    if not _plugin_dir or not _plugin_dir.exists():
        return []
    return [
        entry
        for entry in sorted(_plugin_dir.iterdir())
        if entry.is_dir() and not entry.name.startswith(".")
    ]


def _read_manifest(plugin_dir: Path) -> PluginManifest:
    data = _json_load(plugin_dir / "manifest.json", {})
    return PluginManifest(
        id=data["id"],
        name=data["name"],
        version=data["version"],
        capabilities=data.get("capabilities", []),
        config_schema=data.get("config_schema", {}),
        pipeline_stages=data.get("pipeline_stages", []),
    )


def _read_config(plugin_dir: Path, manifest: PluginManifest) -> dict:
    config = _json_load(plugin_dir / "config.json", {})
    for key, spec in manifest.config_schema.get("properties", {}).items():
        if key not in config and "default" in spec:
            config[key] = spec["default"]
    if manifest.id == "solara" and config.get("bitrate") == "999":
        config["bitrate"] = "flac"
    return config


def _read_enabled(plugin_dir: Path) -> bool:
    state_file = plugin_dir / "state.json"
    if not state_file.exists():
        # 首次发现插件时显式写入默认启用状态，避免默认值只存在于代码逻辑中。
        _json_dump(state_file, {"enabled": True})
        return True
    state = _json_load(state_file, {})
    return bool(state.get("enabled", True))


def _build_instance(
    plugin_dir: Path,
    manifest: PluginManifest,
    config: dict,
) -> BasePlugin:
    plugin_file = plugin_dir / "plugin.py"
    spec = importlib.util.spec_from_file_location(
        f"_plugin_{manifest.id}",
        plugin_file,
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载插件模块: {plugin_file}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if not hasattr(module, "plugin"):
        raise AttributeError(
            f"plugin.py in {plugin_dir.name} must expose a module-level `plugin` variable"
        )

    instance: BasePlugin = module.plugin
    ctx = PluginContext(plugin_id=manifest.id, config=config)
    instance.setup(ctx)
    return instance


def _load_entry(plugin_dir: Path) -> PluginRecord:
    manifest_file = plugin_dir / "manifest.json"
    plugin_file = plugin_dir / "plugin.py"
    if not manifest_file.exists() or not plugin_file.exists():
        raise FileNotFoundError(f"插件目录缺少 manifest.json 或 plugin.py: {plugin_dir}")

    manifest = _read_manifest(plugin_dir)

    # 重新加载前清理旧的流水线回调（reload/disable 安全）
    try:
        from services.pipeline import get_registry
        get_registry().unregister_plugin(manifest.id)
    except Exception:
        pass  # pipeline 尚未初始化时忽略
    config = _read_config(plugin_dir, manifest)
    enabled = _read_enabled(plugin_dir)
    record = PluginRecord(
        manifest=manifest,
        plugin_dir=plugin_dir,
        config=config,
        enabled=enabled,
    )

    if not enabled:
        _registry[manifest.id] = record
        logger.info("插件已禁用: %s", manifest.id)
        return record

    try:
        record.instance = _build_instance(plugin_dir, manifest, config)
        logger.info(
            "已加载插件: %s v%s [%s]",
            manifest.name,
            manifest.version,
            ", ".join(manifest.capabilities),
        )
    except PluginUpstreamError as exc:
        # 自检失败多为配置/依赖服务问题 → error；运行时连不上才是典型上游问题 → warning（见 docs/logging-and-errors.md）
        record.error = str(exc)
        logger.error("插件自检失败（请检查配置或上游依赖是否可用）: %s — %s", manifest.id, exc)
    except Exception as exc:
        record.error = str(exc)
        logger.exception("加载插件失败: %s", plugin_dir.name)

    _registry[manifest.id] = record
    return record


def _plugin_path(plugin_id: str) -> Path:
    if not _plugin_dir:
        raise KeyError(f"插件目录尚未初始化: {plugin_id}")
    plugin_dir = _plugin_dir / plugin_id
    if not plugin_dir.exists() or not plugin_dir.is_dir():
        raise KeyError(f"插件不存在: {plugin_id}")
    return plugin_dir


def _load_all() -> None:
    _registry.clear()
    for entry in _iter_plugin_dirs():
        manifest_file = entry / "manifest.json"
        plugin_file = entry / "plugin.py"
        if not manifest_file.exists() or not plugin_file.exists():
            continue
        try:
            _load_entry(entry)
        except Exception:
            logger.exception("扫描插件失败: %s", entry.name)


def reload_plugin(plugin_id: str) -> PluginRecord:
    return _load_entry(_plugin_path(plugin_id))


def save_config(plugin_id: str, config: dict) -> PluginRecord:
    plugin_dir = _plugin_path(plugin_id)
    _json_dump(plugin_dir / "config.json", config)
    return reload_plugin(plugin_id)


def set_enabled(plugin_id: str, enabled: bool) -> PluginRecord:
    plugin_dir = _plugin_path(plugin_id)
    _json_dump(plugin_dir / "state.json", {"enabled": enabled})
    return reload_plugin(plugin_id)


# ── 查询 API ──────────────────────────────────────────────────

def all_plugins() -> dict[str, PluginRecord]:
    return dict(_registry)


def get_plugin(plugin_id: str) -> Optional[PluginRecord]:
    return _registry.get(plugin_id)


def get_search_plugins() -> list[PluginRecord]:
    return [
        record
        for record in _registry.values()
        if record.enabled and isinstance(record.instance, SearchPlugin)
    ]


def get_metadata_plugins() -> list[PluginRecord]:
    return [
        record
        for record in _registry.values()
        if record.enabled and isinstance(record.instance, MetadataPlugin)
    ]
