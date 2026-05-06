# 插件系统 API 规范

本文档面向插件作者，描述 Banana Music 插件系统的完整接口契约。

---

## 目录

1. [插件类型](#1-插件类型)
2. [插件目录结构](#2-插件目录结构)
3. [manifest.json 格式](#3-manifestjson-格式)
4. [plugin.py 约定](#4-pluginpy-约定)
5. [生命周期](#5-生命周期)
6. [PluginContext API](#6-plugincontext-api)
7. [流水线阶段](#7-流水线阶段)
8. [错误处理](#8-错误处理)
9. [config_schema 约定](#9-config_schema-约定)
10. [完整骨架示例](#10-完整骨架示例)
11. [日志与错误分类约定](#11-日志与错误分类约定)

---

## 1. 插件类型

| 基类 | 能力 | 典型用途 |
|------|------|----------|
| `SearchPlugin` | `"search"` | 搜索外部音乐平台，下载音频入库 |
| `MetadataPlugin` | `"metadata"` | 元数据清洗、指纹查询、信息补全 |

引入路径：`from plugins.base import SearchPlugin, MetadataPlugin`

---

## 2. 插件目录结构

```
plugins/
└── <plugin-id>/
    ├── manifest.json   # 必须：插件声明
    ├── plugin.py       # 必须：实现，模块级暴露 `plugin` 变量
    ├── config.json     # 可选：运行时配置（管理员填写，自动从 schema default 补全）
    └── state.json      # 可选：运行时状态（{"enabled": true/false}，首次发现时自动创建）
```

插件数据目录（运行时读写）：`data/plugins/<plugin-id>/`，通过 `self.ctx.data_dir` 访问。

---

## 3. manifest.json 格式

```json
{
  "id": "my-plugin",
  "name": "My Plugin",
  "version": "1.0.0",
  "capabilities": ["metadata"],
  "pipeline_stages": ["parse_upload"],
  "config_schema": {
    "type": "object",
    "properties": {
      "api_key": {
        "type": "string",
        "title": "API Key",
        "description": "从官网申请的 API Key",
        "default": ""
      }
    }
  }
}
```

### 字段说明

| 字段 | 类型 | 必须 | 说明 |
|------|------|------|------|
| `id` | string | ✓ | 全局唯一，与目录名一致，只含小写字母/数字/连字符 |
| `name` | string | ✓ | 人类可读名称，显示于管理界面 |
| `version` | string | ✓ | 语义版本（`"1.0.0"`） |
| `capabilities` | array | ✓ | `["search"]` 或 `["metadata"]` |
| `pipeline_stages` | array | — | 声明支持的流水线阶段（见第 7 节），用于生成默认 `data/pipeline.json` |
| `config_schema` | object | — | JSON Schema 子集，描述可配置项（见第 9 节） |

---

## 4. plugin.py 约定

模块必须在最顶层暴露一个名为 `plugin` 的变量，其值为插件实例：

```python
# 文件末尾
plugin = MyPlugin()
```

Loader 在加载时对该模块调用 `importlib.util.module_from_spec` + `exec_module`，然后读取 `module.plugin`。

---

## 5. 生命周期

```
1. 主程序启动 → loader.init(plugin_dir)
2. 扫描 plugins/<id>/manifest.json + plugin.py
3. _build_instance(plugin_dir, manifest, config)
     a. 动态 import plugin.py
     b. 创建 PluginContext(plugin_id, config)
     c. 调用 plugin.setup(ctx)
          ├─ 自检（可选）
          │    └─ 失败 → raise PluginUpstreamError
          │         → loader 标记 record.error，不注册任何回调
          └─ 注册流水线回调（可选）
               └─ ctx.register_for_stage(stage, callback)
4. 运行时
     · SearchPlugin：管理员/用户通过 API 触发搜索/下载
     · MetadataPlugin：主程序按 pipeline.json 配置触发对应阶段回调
5. reload_plugin() / set_enabled(False)
     → 清理旧回调 → 重新执行步骤 3
```

---

## 6. PluginContext API

通过 `self.ctx` 访问（在 `setup()` 调用 `super().setup(ctx)` 后可用）。

### `ctx.log(level, msg)`

```python
self.ctx.log("info", "已连接到外部服务")
self.ctx.log("warning", f"查询超时: {e}")
self.ctx.log("error", "自检失败")  # 自检阶段使用
```

日志自动添加 `[plugin:<id>]` 前缀，写入主程序统一日志流。

### `ctx.register_for_stage(stage, callback)`

```python
# 在 setup() 自检通过后调用
ctx.register_for_stage("parse_upload", self.parse_upload)
ctx.register_for_stage("fingerprint_lookup", self.lookup_by_fingerprint)
```

同一 `plugin+stage` 重复注册时覆盖旧条目（reload 安全）。

### `ctx.ingest_file(file_path, meta)`

将本地音频文件导入曲库（SearchPlugin.download() 使用）：

```python
result = self.ctx.ingest_file(
    file_path=Path("/tmp/audio.flac"),
    meta=TrackMeta(
        title="Song Title",
        artists=["Artist A", "Artist B"],
        album="Album Name",
        track_number=3,
        release_date="2024-01-15",
    ),
)
# 返回 {"status": "added"|"duplicate", "track_id": N, "title": "..."}
```

`ingest_file` 是同步阻塞操作，在 `download()` 中需用 `asyncio.get_event_loop().run_in_executor(None, self.ctx.ingest_file, ...)` 包装。

### `ctx.data_dir`

```python
cache_file = self.ctx.data_dir / "cache.json"
```

插件专属的持久化数据目录，路径为 `data/plugins/<plugin-id>/`，自动创建。

### `ctx.config`

```python
api_key = self.ctx.config.get("api_key", "")
timeout = float(self.ctx.config.get("timeout_sec", 30))
```

来自 `config.json`，已用 `config_schema.properties[*].default` 自动补全缺失键。

---

## 7. 流水线阶段

元数据插件通过注册回调参与主程序的清洗流水线。流水线配置在 `data/pipeline.json`，管理员可直接编辑（修改后重启或调用 `reload_plugin()` 生效）。

### 阶段总览

| stage_id | 触发时机 | 默认策略 | 典型插件 |
|----------|----------|----------|----------|
| `parse_upload` | 前端上传入库前通过 `/rest/x-banana/plugins/{plugin_id}/parse-metadata` 同步调用 | first — 取第一个非 None 结果 | llm-metadata |
| `fingerprint_lookup` | Chromaprint 指纹写入后 | best — 并行查询，取最高置信度 | musicbrainz |
| `info_lookup` | 同上（默认 disabled） | best | musicbrainz |

### parse_upload

```python
async def parse_upload(
    self,
    filename_stem: str,          # 文件名（不含扩展名），如 "01 - Artist - Song"
    raw_tags: Optional[TagDict], # 客户端解析出的标签，可为 None（无嵌入标签）
) -> Optional[MetadataResult]:
    ...
    return MetadataResult(title="Song", artists=["Artist"], confidence=0.9)
    # 返回 None 表示不干预，主程序使用原始值
```

`TagDict` 可能包含的键：`title`, `artist`, `artists`, `album`, `track_number`, `release_date`, `album_artist`, `lyrics`。

### fingerprint_lookup / info_lookup

```python
async def lookup_by_fingerprint(
    self,
    fingerprint: bytes,  # fpcalc 默认压缩输出，已 encode() 为 bytes
    duration_sec: int,   # 音轨时长，必须 > 0
) -> Optional[MetadataResult]:
    ...

async def lookup_by_info(
    self,
    title: str,
    artist: str,
) -> Optional[MetadataResult]:
    ...
```

`best` 模式下流水线并行调用所有注册插件，选取 `MetadataResult.confidence` 最高的结果（低于 `min_confidence` 则不写库）。

### 在 manifest 中声明支持的阶段

```json
{
  "pipeline_stages": ["fingerprint_lookup", "info_lookup"]
}
```

主程序首次启动时若 `data/pipeline.json` 不存在，将根据所有插件的 `pipeline_stages` 自动生成默认配置。

---

## 8. 错误处理

### 自检阶段（setup）

```python
def setup(self, ctx) -> None:
    super().setup(ctx)
    try:
        resp = httpx.get(f"{self._base_url()}/health", timeout=5)
    except httpx.RequestError as e:
        raise PluginUpstreamError(f"服务不可达: {e}") from e
    if resp.status_code >= 500:
        raise PluginUpstreamError(f"服务异常 HTTP {resp.status_code}")
    # 自检通过 → 注册回调
    ctx.register_for_stage("parse_upload", self.parse_upload)
```

`PluginUpstreamError` 被 loader 捕获，记录 ERROR 日志，插件标记为 `record.error`，**不注册任何回调**。

### 运行时（回调执行期间）

| 异常类型 | 含义 | HTTP 映射 |
|----------|------|-----------|
| `PluginUpstreamError` | 网络/HTTP/业务错误（运行时连不上） | 502 |
| `PluginParseError` | 响应结构解析失败 | 500 |

运行时异常应记录 WARNING（非 ERROR），不应中断主程序：

```python
try:
    resp = await client.get(url)
    resp.raise_for_status()
except httpx.HTTPStatusError as e:
    self.ctx.log("warning", f"API 返回 HTTP {e.response.status_code}")
    return None
```

---

## 9. config_schema 约定

使用 JSON Schema 子集（`type`, `title`, `description`, `default`, `enum`）：

```json
{
  "type": "object",
  "properties": {
    "api_key": {
      "type": "string",
      "title": "API Key",
      "description": "在 https://example.com/keys 申请",
      "default": ""
    },
    "quality": {
      "type": "string",
      "title": "音质",
      "enum": ["128", "320", "lossless"],
      "default": "320"
    },
    "timeout_sec": {
      "type": "number",
      "title": "超时（秒）",
      "default": 30
    },
    "enabled_feature": {
      "type": "boolean",
      "title": "启用某功能",
      "default": false
    }
  }
}
```

`default` 值在 `config.json` 缺少对应键时自动补全，插件始终可通过 `self.ctx.config.get(key)` 安全读取。

---

## 10. 完整骨架示例

### manifest.json

```json
{
  "id": "my-metadata",
  "name": "My Metadata Service",
  "version": "1.0.0",
  "capabilities": ["metadata"],
  "pipeline_stages": ["parse_upload", "fingerprint_lookup"],
  "config_schema": {
    "type": "object",
    "properties": {
      "base_url": {
        "type": "string",
        "title": "服务地址",
        "default": "http://localhost:8080"
      },
      "timeout_sec": {
        "type": "number",
        "title": "超时（秒）",
        "default": 10
      }
    }
  }
}
```

### plugin.py

```python
"""
plugins/my-metadata/plugin.py
My Metadata Service 插件。
"""
from __future__ import annotations

from typing import Optional

import httpx

from plugins.base import MetadataPlugin, MetadataResult, PluginManifest, TagDict
from plugins.errors import PluginUpstreamError, PluginParseError

MANIFEST = PluginManifest(
    id="my-metadata",
    name="My Metadata Service",
    version="1.0.0",
    capabilities=["metadata"],
    pipeline_stages=["parse_upload", "fingerprint_lookup"],
)


class MyMetadataPlugin(MetadataPlugin):
    manifest = MANIFEST

    def _base_url(self) -> str:
        return self.ctx.config.get("base_url", "http://localhost:8080").rstrip("/")

    def _timeout(self) -> float:
        return float(self.ctx.config.get("timeout_sec", 10))

    def setup(self, ctx) -> None:
        super().setup(ctx)

        # 1. 自检
        url = f"{self._base_url()}/health"
        self.ctx.log("info", f"自检: GET {url}")
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(url)
        except httpx.RequestError as e:
            raise PluginUpstreamError(f"服务不可达 ({url}): {e}") from e

        if resp.status_code >= 400:
            raise PluginUpstreamError(f"服务返回 HTTP {resp.status_code}")

        self.ctx.log("info", f"已连接: {self._base_url()}")

        # 2. 自检通过 → 注册流水线回调
        ctx.register_for_stage("parse_upload", self.parse_upload)
        ctx.register_for_stage("fingerprint_lookup", self.lookup_by_fingerprint)

    async def parse_upload(
        self,
        filename_stem: str,
        raw_tags: Optional[TagDict] = None,
    ) -> Optional[MetadataResult]:
        """上传时清洗元数据。"""
        if not filename_stem:
            return None
        try:
            async with httpx.AsyncClient(timeout=self._timeout()) as client:
                resp = await client.post(
                    f"{self._base_url()}/parse",
                    json={"filename": filename_stem, "tags": raw_tags or {}},
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as e:
            self.ctx.log("warning", f"parse_upload HTTP {e.response.status_code}")
            return None
        except Exception as e:
            self.ctx.log("warning", f"parse_upload 异常: {e}")
            return None

        return MetadataResult(
            title=data.get("title"),
            artists=data.get("artists", []),
            album=data.get("album"),
            confidence=float(data.get("confidence", 0.8)),
        )

    async def lookup_by_fingerprint(
        self,
        fingerprint: bytes,
        duration_sec: int = 0,
    ) -> Optional[MetadataResult]:
        """通过指纹查询元数据。"""
        if not fingerprint or duration_sec <= 0:
            return None
        try:
            async with httpx.AsyncClient(timeout=self._timeout()) as client:
                resp = await client.post(
                    f"{self._base_url()}/lookup",
                    json={
                        "fingerprint": fingerprint.decode(),
                        "duration": duration_sec,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as e:
            self.ctx.log("warning", f"lookup_by_fingerprint HTTP {e.response.status_code}")
            return None
        except Exception as e:
            self.ctx.log("warning", f"lookup_by_fingerprint 异常: {e}")
            return None

        return MetadataResult(
            title=data.get("title"),
            artists=data.get("artists", []),
            album=data.get("album"),
            confidence=float(data.get("score", 0)),
        )


# loader 约定：模块级 `plugin` 变量
plugin = MyMetadataPlugin()
```

---

## 11. 日志与错误分类约定

### 总原则

| 判断 | 日志级别 |
|------|----------|
| **代码缺陷**或**配置/环境错误**（本仓库应改代码或配置） | **ERROR** |
| **上游服务**失败、超时、非预期响应，或调用参数不当 | **WARNING** |

**堆栈**：仅当异常表示**未预期的代码路径**（import 失败、未捕获 bug）时使用 `logger.exception`；语义明确的业务异常（如 `PluginUpstreamError`）只记一行说明，不打整段 traceback。

### 插件子系统

**语义对应**：

- **`setup()` 自检失败**（`PluginUpstreamError`）：大概率是配置写错了（URL、端口、未启动的依赖）→ 算**本侧配置问题** → **ERROR**（无堆栈）
- **自检通过之后**再出现的连不上/超时/非预期响应：典型**上游/网络问题** → **WARNING**（无堆栈）

| 场景 | 级别 | 堆栈 |
|------|------|------|
| `setup()` 自检失败（`PluginUpstreamError`） | **ERROR** | 否 |
| 运行时网络/超时/HTTP 错误（`PluginUpstreamError`） | **WARNING** | 否 |
| 运行时响应解析失败（`PluginParseError`） | **WARNING** | 否 |
| 加载时非 `PluginUpstreamError`（import 错误、属性错误） | **ERROR** | **是** |

**实现对照**：

| 文件 | 行为 |
|------|------|
| `backend/plugins/loader.py` | 自检 `PluginUpstreamError` → error（无堆栈）；其它 → exception |
| `backend/routers/plugins.py` | 运行时 `PluginUpstreamError` / `PluginParseError` → warning |
| `plugins/solara/plugin.py` | 运行时上游/解析异常 → warning |
| `plugins/musicbrainz/plugin.py` | 运行时上游 → warning |

插件内部**不要**在 `setup()` 自检失败前再重复打一条 ERROR——加载器统一记录。

### 上传与本地子进程

| 场景 | 级别 |
|------|------|
| 缺少 `fpcalc` / `ffprobe` 等（环境/部署选择） | WARNING |
| 上传管道未捕获异常 | ERROR（`logger.exception`）|
