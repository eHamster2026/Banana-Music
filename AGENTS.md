# Banana Music — AGENTS.md

音乐流媒体应用，FastAPI 后端 + React 前端 + 可扩展插件系统。

---

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.10+, FastAPI, SQLAlchemy 2.0, Uvicorn |
| 数据库 | SQLite（默认，WAL 模式）/ PostgreSQL |
| 前端 | React 18, Vite 6, i18next |
| 包管理 | 后端 `uv`；前端 `npm` |
| 测试 | 后端 `pytest`（`tests/`）；前端 `vitest` |
| 音频处理 | mutagen（标签）, soundfile + pydub（时长）, pyacoustid / fpcalc（指纹）|

---

## 目录结构

```
banana-music/
├── backend/            # FastAPI 应用
│   ├── main.py         # 启动入口、建表、schema 版本检查、列迁移
│   ├── models.py       # SQLAlchemy ORM（19 张表）
│   ├── config.py       # Pydantic Settings（读 .env）
│   ├── database.py     # 引擎 + SessionLocal + WAL/PRAGMA
│   ├── schema_version.py  # SCHEMA_VERSION 常量
│   ├── schemas.py      # Pydantic 请求/响应模型
│   ├── deps.py         # 依赖注入（get_db, get_current_user, get_admin_user）
│   ├── routers/        # 路由（12 个模块）
│   ├── services/       # 业务逻辑（pipeline, enrich, artist_names, …）
│   ├── plugins/        # 插件基础设施（base, loader, context, errors）
│   └── tests/          # pytest 测试集
├── frontend/
│   └── src/            # React 组件、页面、Context、api.js、localUpload.js
├── plugins/            # 内置插件（llm-metadata, musicbrainz, solara）
├── data/               # 运行时数据（music.db, resource/, covers/, plugins/）
├── scripts/            # 开发工具脚本
├── docs/               # 设计文档
└── .env / .env.example # 环境变量
```

---

## 常用命令

### 首次初始化

```bash
# 后端依赖（uv）
cd backend
UV_PROJECT_ENVIRONMENT=venv uv sync
cd ..

# 前端依赖
cd frontend && npm install
```

### 日常开发（两个终端）

```bash
# 终端 1 — 后端（自动重载）
bash scripts/dev-local.sh backend   # uvicorn :8000, --log-level debug

# 终端 2 — 前端（热更新，API 已代理到 :8000）
bash scripts/dev-local.sh frontend  # Vite :5173
```

其他子命令：

```bash
bash scripts/dev-local.sh stack     # 同一终端启动两者
bash scripts/dev-local.sh build     # 仅构建前端到 frontend/dist/
bash scripts/dev-local.sh serve     # uvicorn 托管已构建的 dist/（接近生产）
```

### 测试

```bash
# 后端依赖含测试工具
cd backend
UV_PROJECT_ENVIRONMENT=venv uv sync --extra dev
UV_PROJECT_ENVIRONMENT=venv uv run python -m pytest tests/ -x -q

# 前端
cd ../frontend && npm run test
```

---

## 后端关键约定

### Schema 版本管理

**每次修改数据库结构都必须：**

1. 在 `schema_version.py` 中递增 `SCHEMA_VERSION`，并在注释里记录变更内容
2. 在 `main.py` 的 `_conn.execute(INSERT OR IGNORE ...)` 处更新 description 字符串
3. 新增**表**：只需在 `models.py` 加 `class`，`create_all` 启动时自动建表
4. 新增/删除**列**：在 `main.py` 的 `_migrate_columns()` 里加 `ALTER TABLE` 语句（生产环境无法自动 reset，必须显式迁移）

开发环境版本不匹配时 `main.py` 会自动调用 `scripts/reset_dev.py` 重建数据库。

### DB Session 使用

- 路由层通过 `db: Session = Depends(get_db)` 注入 Session，请求结束自动关闭
- **后台异步任务**（如 fingerprint_worker、parse_upload 后台任务）必须用独立 `SessionLocal()`，在 `finally` 里 `db.close()`——不能跨 await 复用路由 Session
- SQLite 写入通过 `asyncio.Lock`（`_get_write_lock()`）串行化，防止 `database is locked`

### 并发写库模式

```python
async with _get_write_lock():
    # 查重 → 写入 → flush → commit
    db.flush()
    db.commit()
    db.refresh(obj)

# 锁外 fire-and-forget
asyncio.create_task(some_bg_coro(...))
```

### 上传流水线

```
POST /tracks/upload-file
  → 存文件到磁盘
  → 线程池（_executor）：PCM hash + 时长（soundfile）+ Mutagen 标签
  → PCM hash 格式无关去重
  → 写 UploadStaging（DB）
  → 响应 {status, file_key}

POST /tracks/create
  → 读 UploadStaging（audio_hash, duration, original_name）
  → 线程池：_parse_tags(file)（Mutagen 重解析，< 50 ms）
  → asyncio.Lock 串行写 Track
  → 删 UploadStaging
  → fire-and-forget：指纹任务 + parse_upload LLM 清洗
  → 立即返回 {track_id, ...}

后台任务：
  fingerprint_worker — 每秒轮询 fingerprint_tasks，计算 Chromaprint 指纹
    → 指纹写入后：run_fingerprint_lookup（MusicBrainz 等，若启用）
  _bg_parse_upload_enrich — run_parse_upload（LLM 清洗），保守合并回 Track
```

### 元数据流水线（`services/pipeline.py`）

- `run_parse_upload(filename_stem, raw_tags)` — mode=first，顺序调用，取第一个非 None
- `run_fingerprint_lookup(fingerprint, duration_sec)` — mode=best，并行调用，取最高置信度
- 配置文件：`data/pipeline.json`（管理员可编辑；不存在时由 manifest.pipeline_stages 自动生成）
- 插件注册：`ctx.register_for_stage(stage, callback)` 在 `setup()` 自检通过后调用

### 插件开发快速参考

```
plugins/<id>/
├── manifest.json   # id, name, version, capabilities, pipeline_stages, config_schema
├── plugin.py       # 模块级 `plugin = MyPlugin()`
├── config.json     # 运行时配置（管理员填写）
└── state.json      # {"enabled": true/false}
```

- 继承 `SearchPlugin`（搜索+下载）或 `MetadataPlugin`（标签清洗/指纹查询）
- `setup(ctx)` 中先自检，失败 `raise PluginUpstreamError`；通过后 `ctx.register_for_stage(...)`
- 详细规范见 `docs/plugin-api.md`

### 日志级别约定

| 场景 | 级别 |
|---|---|
| 代码缺陷、配置/环境错误（本仓库应改） | `ERROR`（`logger.exception` 若有未预期堆栈）|
| 上游服务失败、超时、返回非预期内容 | `WARNING`（无堆栈）|
| 插件 `setup()` 自检失败（`PluginUpstreamError`） | `ERROR`（无堆栈，提示查配置/依赖）|
| 插件运行时上游问题 | `WARNING` |

详见 `docs/plugin-api.md` 第 11 节。

### 脚本与批量工具日志规范（新增）

- 对于未显式处理的异常，必须记录完整上下文和堆栈，不要只打印 `str(exc)`。
- 优先使用 `logging.error(..., exc_info=True)`，并补充 `__cause__/__context__` 的原因链，避免出现只显示 `All connection attempts failed` 这类不充分提示。
- 涉及上传/LLM 清洗/网络请求的关键流程，建议在 `except Exception` 分支统一调用同一日志函数，确保能定位是连接、认证、DNS 还是代理层失败。

---

## 前端关键约定

- API 请求统一通过 `src/api.js` 的封装函数（`apiFetch`、`uploadSingleFile`、`createTrack` 等）
- 本地文件上传逻辑在 `src/localUpload.js`：`computeFileHash` → `checkHash` → `uploadSingleFile` → `createTrack`（只传 `file_key`，元数据由后端解析）
- `displayTrackTitle(track)` — 无标题时显示 `#<id>` 占位
- 国际化：`src/i18n.js` + `src/locales/`（主要为中文）

---

## LLM/API 助手契约

`Agent.md` 中的 Banana Music LLM Skill 约定已合并到这里，后续面向自动化工具或 AI 助手的接口说明以本节为准。

### 认证

- Base URL 示例：`http://localhost:8000`
- 写操作、管理接口和插件相关接口通常需要认证
- 支持 `Authorization: Bearer <access_token>` 与 `X-API-Key: am_<your_key>` 两种认证方式；与后端 `deps` 一致，Bearer 优先
- API Key 权限与生成该 Key 的账号一致；管理员账号可调用 `/admin/*`
- 无需认证的只读端点：`GET /search`、`GET /search/suggestions`
- `GET /search` 未登录时仅返回本地库结果；已登录且启用搜索插件时，响应可能额外包含 `plugin_hits`

### 常用工具端点

| 工具 | 端点 | 权限 | 用途 |
|---|---|---|---|
| `search_tracks` | `GET /search?q={query}` | 可匿名 | 搜索本地曲目、专辑、艺术家；已登录时可合并 `plugin_hits` |
| `list_tracks` | `GET /admin/tracks?skip={skip}&limit={limit}&q={query}&missing_metadata={bool}` | 管理员 | 分页列出全库曲目，支持元数据缺失过滤 |
| `get_library_stats` | `GET /admin/stats` | 管理员 | 查看曲库统计和元数据缺失数量 |
| `update_metadata` | `PUT /admin/tracks/{track_id}` | 管理员 | 更新单曲标题、艺人、专辑、音轨号、时长 |
| `batch_update_metadata` | `POST /admin/tracks/batch-update` | 管理员 | 批量更新元数据，单次最多 50 条 |
| `check_duplicate` | `GET /tracks/check-hash?h={sha256_hex}` | 认证 | 上传前按原始文件 SHA-256 查重 |
| `upload_file` | `POST /tracks/upload-file` | 认证 | 上传音频文件，返回后台任务 `job_id` |
| `upload_status` | `GET /tracks/upload-status/{job_id}` | 认证 | 轮询上传任务状态 |
| `create_track` | `POST /tracks/create` | 认证 | 用 `file_key` 将已上传文件正式写入曲库 |

### 上传工作流

```
1. 计算文件 SHA-256 → file_hash

2. GET /tracks/check-hash?h={file_hash}
   → exists=true  → 记录 track_id，结束
   → exists=false → 继续

3. POST /tracks/upload-file，表单字段 file + file_hash
   → 返回 job_id

4. GET /tracks/upload-status/{job_id} 轮询至 state=done 或 error
   → status=duplicate → 记录 track_id，结束
   → status=ok        → 记录 file_key，可展示 parsed_metadata

5. POST /tracks/create，请求体仅传 { "file_key": "..." }
   → status=added     → 记录 track_id
   → status=duplicate → 记录 track_id
```

`parsed_metadata` 在 `upload-status` 的 `done/ok` 返回中提供给前端或自动化展示；`create_track` 不再接收这些字段。入库初值由服务端 Mutagen 解析，后续可由 `parse_upload` 流水线补全或拆分多艺人；人工修正走 `PUT /admin/tracks/{id}`。

### 元数据整理工作流

- 批量修复“未知艺人”：先 `GET /admin/stats` 查看缺失数量，再用 `GET /admin/tracks?missing_metadata=true&limit=200` 翻页收集曲目，最后按每批不超过 50 条调用 `POST /admin/tracks/batch-update`
- 整理专辑：先 `GET /search?q=<专辑关键词>` 找到相关曲目，再批量设置 `album_title` 和 `track_number`
- `artist_name` 和 `album_title` 若不存在会自动创建；`album_title: ""` 表示移除专辑关联

### API 错误处理

| 状态码 | 含义 | 处理建议 |
|---|---|---|
| 400 | 参数错误 | 检查请求体格式和必填字段 |
| 401 | API Key / Bearer 无效或缺失 | 检查认证头 |
| 403 | 权限不足 | 使用管理员账号生成的 API Key 或管理员 Bearer |
| 404 | 资源不存在 | 确认 track_id、job_id 等资源仍存在 |
| 500 | 服务端错误 | 稍后重试并检查后端日志 |

批量接口的部分失败不会触发 HTTP 错误码，而是通过 `failed` 字段返回。上传流程中 `file_key`、`audio_hash`、`file_hash` 必须对应同一个文件，不可混用。

---

## 环境变量

主要变量（完整列表见 `.env.example`）：

```bash
SECRET_KEY=change-me-in-production  # JWT 签名密钥
DATABASE_URL=sqlite:///music.db     # 相对路径自动锚定到 data/
FINGERPRINT_ENABLED=true            # 需系统安装 fpcalc
UPLOAD_AUTO_METADATA_AFTER_FINGERPRINT=false  # 指纹后自动调 MusicBrainz
BANANA_TESTING=false                # pytest 设为 true，跳过 seed/插件/指纹
```

本地开发时 `scripts/dev-local.sh` 自动设置 `UPLOAD_AUTO_METADATA_AFTER_FINGERPRINT=true`。

---

## 数据库核心表速查

| 表 | 用途 |
|---|---|
| `tracks` | 曲目（含 file_hash、audio_hash、audio_fingerprint）|
| `artists` / `albums` | 艺人/专辑 |
| `track_artists` / `album_artists` | 多艺人关联（featured，有序）|
| `fingerprint_tasks` | Chromaprint 任务队列 |
| `upload_staging` | 上传暂存（audio_hash + duration + original_name，TTL 1h）|
| `schema_migrations` | 版本历史（替代文件）|
| `play_queues` / `play_queue_items` | 每用户播放队列 |

---

## 测试说明

- `BANANA_TESTING=true`（`tests/conftest.py` 自动设置）：使用内存 SQLite，跳过 seed、插件加载、指纹后台任务
- 后端测试不依赖外部服务（Ollama、MusicBrainz 等）
- `tests/test_skill_openapi_contract.py` 验证 OpenAPI schema 契约
