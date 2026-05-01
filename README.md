# 🍌 Banana Music

版本 0.2 · 本地音乐管理 + 流媒体播放 Web 应用

自托管的音乐库系统：上传音频文件后自动完成格式转码、Chromaprint 指纹识别和 LLM 元数据清洗，通过 Web 界面播放、管理和搜索整个音乐库，并可通过插件扩展在线搜索与下载能力。

---

## 目录

- [功能概览](#功能概览)
- [技术栈](#技术栈)
- [目录结构](#目录结构)
- [环境配置](#环境配置)
- [快速开始](#快速开始)
- [环境变量](#环境变量)
- [插件系统](#插件系统)
- [批量导入与预处理脚本](#批量导入与预处理脚本)
- [测试](#测试)
- [文档索引](#文档索引)

---

## 功能概览

### 音乐库管理
- 支持上传 FLAC / MP3 / WAV / APE / WMA / M4A / OGG / AAC，无损格式自动转码为 FLAC 存档
- 基于 PCM 音频哈希（格式无关）自动去重——同一首歌重新编码不会重复入库
- Chromaprint 指纹识别，结合 MusicBrainz / AcoustID 自动补全曲目信息
- LLM 辅助标签清洗（本地 Ollama），从混乱的文件名和标签中提取结构化元数据
- 嵌入封面与歌词自动提取并持久化

### 播放与交互
- Web 流媒体播放器，支持进度控制、音量调节、随机 / 顺序 / 单曲循环
- 每用户独立播放队列，跨页面持久化
- 播放历史记录与曲目收藏（已赞）

### 库浏览与搜索
- 按艺人 / 专辑 / 播放列表分类浏览，支持多艺人关联（Featured）
- 全文搜索，可同时检索本地库与在线搜索插件结果
- 播放列表创建与编辑

### 管理后台
- 批量编辑曲目元数据
- 插件管理：启用 / 禁用 / 在线配置各插件
- 系统状态监控、用户管理、API Key 生成

---

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.10+, FastAPI, SQLAlchemy 2.0, Uvicorn |
| 前端 | React 18, Vite 6, i18next |
| 数据库 | SQLite（WAL 模式，默认）/ PostgreSQL |
| 认证 | JWT (python-jose, bcrypt) |
| 音频处理 | mutagen（标签）, soundfile（时长）, pydub（解码）, fpcalc（Chromaprint 指纹）|
| 包管理 | 后端 `uv`；前端 `npm` |
| 测试 | 后端 `pytest`；前端 `vitest` |
| 部署 | Docker Compose（banana-music + solara + ollama） |

---

## 目录结构

```
banana-music/
├── backend/            # FastAPI 应用
│   ├── main.py         # 启动入口、建表、schema 版本检查
│   ├── models.py       # SQLAlchemy ORM（19 张表）
│   ├── routers/        # 12 个路由模块（auth, upload, tracks, search 等）
│   ├── services/       # 业务逻辑（pipeline, enrich, artist_names 等）
│   ├── plugins/        # 插件基础设施（base, loader, context, errors）
│   └── tests/          # pytest 测试集
├── frontend/
│   └── src/            # React 组件、页面、Context、api.js、localUpload.js
├── plugins/            # 内置插件
│   ├── llm-metadata/   # LLM 文件名 / 标签清洗（Ollama）
│   ├── musicbrainz/    # 指纹查询与元数据补全
│   └── solara/         # 在线搜索与下载
├── scripts/            # 开发工具与预处理脚本
├── docs/               # 设计文档
├── data/               # 运行时数据（music.db, resource/, covers/）
├── docker-compose.yml
├── Dockerfile          # 两阶段构建（backend-base → production）
├── Makefile
└── .env.example
```

---

## 环境配置

### 本地开发环境

所需工具：

| 工具 | 版本 | 安装 |
|------|------|------|
| Python | 3.10+ | 系统包管理器或 pyenv |
| Node.js | 20+ | nvm 或系统包管理器 |
| uv | 最新 | `pip install uv` 或[官方脚本](https://github.com/astral-sh/uv) |
| 系统包 | — | `sudo apt install ffmpeg libsndfile1 libchromaprint-tools` |

不需要 Chromaprint 指纹时可在 `.env` 中设 `FINGERPRINT_ENABLED=false`，无需安装 `libchromaprint-tools`。

```bash
bash scripts/backend-sync.sh        # 安装后端依赖到 backend/venv
cd frontend && npm install           # 安装前端依赖
```

### Docker 环境

`docker-compose.yml` 包含完整容器序列：

| 服务 | 说明 | 默认端口 |
|------|------|----------|
| `banana-music` | 主应用（FastAPI + 静态前端） | 8000 |
| `solara` | 音乐代理服务（搜索/下载插件后端） | 3001 |
| `ollama` | LLM 推理服务（llm-metadata 插件后端） | 11434 |

Dockerfile 采用两阶段构建；前端须在宿主机或 CI 中先编译再打包进镜像。常用操作均封装在 `Makefile`：

```bash
make install      # 安装后端（含 dev 依赖）与前端依赖
make docker-build # 编译前端 + 构建 banana-music 镜像
make up           # 启动全部服务
make pull-model   # 首次启动后拉取 LLM 模型
make deploy       # docker-build + up 一步完成
make down         # 停止全部服务
make logs         # 跟踪主应用日志
make restart      # 重启主应用（修改插件 config.json 后）
```

**插件配置**：`./plugins` 目录以 volume 挂载到容器，可直接在宿主机编辑 `config.json`。Docker 环境中各插件默认使用服务名（`http://solara:3001`、`http://ollama:11434`）；本地非 Docker 开发时需将这两个地址改回实际 IP 或 `localhost`。

**GPU 加速**（可选）：Ollama 支持 NVIDIA GPU，取消注释 `docker-compose.yml` 中 `ollama` 服务的 `deploy` 块（需先安装 `nvidia-container-toolkit`）。

---

## 快速开始

```bash
# 1. 安装依赖
bash scripts/backend-sync.sh
cd frontend && npm install && cd ..

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，至少修改 SECRET_KEY

# 3. 启动（两个终端）
bash scripts/dev-local.sh backend    # 后端 :8000，自动重载
bash scripts/dev-local.sh frontend   # 前端 :5173，热更新，API 代理到 :8000
```

单终端：`bash scripts/dev-local.sh stack`

其他子命令：

```bash
bash scripts/dev-local.sh build      # 仅构建前端到 frontend/dist/
bash scripts/dev-local.sh serve      # uvicorn :8000，托管已构建的 dist/（接近生产）
```

启动后：
- 前端：`http://localhost:5173`
- API 文档：`http://localhost:8000/docs`
- 默认账户：`demo` / `demo123`（管理员权限）

### 上传与元数据处理

`POST /tracks/upload-file` 先落盘并返回 `job_id`，前端轮询 `GET /tracks/upload-status/{job_id}` 至 `state: done` 后获得 `file_key`；随后 `POST /tracks/create` 请求体**仅需** `{ "file_key" }`，元数据由服务端自动解析，`parse_upload` 流水线在后台异步执行（重启不丢任务）。如需手动修改元数据，使用管理端 `PUT /admin/tracks/{id}` 或批量接口。

---

## 环境变量

完整列表见 [`.env.example`](.env.example)，主要变量：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `SECRET_KEY` | `change-me-in-production` | JWT 签名密钥，**生产必改** |
| `DATABASE_URL` | `sqlite:///music.db` | 数据库连接（相对路径锚定到 `data/`） |
| `FINGERPRINT_ENABLED` | `true` | 启用 Chromaprint 指纹（需系统安装 `fpcalc`） |
| `UPLOAD_AUTO_METADATA_AFTER_FINGERPRINT` | `false` | 指纹成功后自动调用元数据插件（`dev-local.sh` 默认开启） |
| `APP_PORT` | `8000` | 后端监听端口 |
| `CORS_ORIGINS` | `["*"]` | 允许的跨域来源，生产应限制到实际域名 |
| `UPLOAD_MAX_WORKERS` | CPU 核数 | 上传处理线程池大小 |
| `BANANA_TESTING` | `false` | 测试模式，pytest 自动设置；跳过 seed、插件加载、指纹任务 |

---

## 插件系统

插件是扩展 Banana Music 能力的主要方式，分为两类：

| 类型 | 基类 | 用途 |
|---|---|---|
| `MetadataPlugin` | 元数据处理 | 标签清洗、指纹查询、信息补全 |
| `SearchPlugin` | 在线搜索 | 搜索外部平台，将结果下载入库 |

### 内置插件

| 插件 | 类型 | 说明 |
|---|---|---|
| `llm-metadata` | MetadataPlugin | 通过本地 Ollama 对文件名/标签做 LLM 清洗，提取结构化元数据 |
| `musicbrainz` | MetadataPlugin | Chromaprint 指纹 → AcoustID → MusicBrainz，自动补全曲目信息 |
| `solara` | SearchPlugin | 搜索网易云、酷我、JOOX 等来源，下载音频入库 |

### 插件结构

```
plugins/<id>/
├── manifest.json   # 声明：id, name, capabilities, pipeline_stages, config_schema
├── plugin.py       # 实现：继承 SearchPlugin 或 MetadataPlugin
├── config.json     # 运行时配置（管理员填写，如 API Key、服务地址）
└── state.json      # {"enabled": true/false}
```

插件在 `setup(ctx)` 中完成自检，通过后调用 `ctx.register_for_stage(stage, callback)` 注册到元数据流水线。自检失败时 `raise PluginUpstreamError`，服务正常启动但该插件不参与处理。

全部接口契约见 [`docs/plugin-api.md`](docs/plugin-api.md)。

---

## 批量导入与预处理脚本

`scripts/bulk_import.py` 提供批量导入预处理与上传能力。Python 依赖单独列在 `scripts/requirements-bulk-import.txt`。

### `bulk_import.py convert` — 格式转换

将 APE / WAV / WMA-lossless 转码为 FLAC，修复 ffmpeg 转码后标签丢失的问题。对已是 FLAC 的文件，根据压缩级别决定是否重编码：高级别不降级，低级别重编码提升压缩率（级别存入 `COMPRESSION_LEVEL` Vorbis 标签供下次比较）。

```bash
pip install -r scripts/requirements-bulk-import.txt

python scripts/bulk_import.py convert *.ape --output-dir ./flac/ --level 8
python scripts/bulk_import.py convert *.flac --output-dir ./flac/ --tags-only
```

`--output-dir` 必须显式指定；如需输出到当前目录，使用 `--output-dir .`。`--level 0-12`（默认 5）：0 最快/最大，8 较慢/较小，12 极限压缩。

### `bulk_import.py clean` — LLM 元数据清洗

通过 Ollama 从文件名和嵌入标签中提取结构化元数据，输出 JSON 结果供审查（不修改原文件）。

```bash
python scripts/bulk_import.py clean *.mp3 \
  --ollama-url http://localhost:11434 --model qwen3.5:latest \
  --output results.json
```

### `bulk_import.py process` — 完整入库流水线

串联格式转换与 LLM 清洗，标签只写入输出目录或临时目录中的副本（支持 FLAC / MP3 / M4A / OGG），源文件始终只读。

```bash
python scripts/bulk_import.py process /music/inbox/*.ape /music/inbox/*.mp3 \
  --output-dir ./processed/ --level 8 \
  --ollama-url http://localhost:11434

python scripts/bulk_import.py process *.ape --output-dir ./processed/ --skip-llm       # 仅转码
python scripts/bulk_import.py process *.mp3 --output-dir ./processed/ --skip-convert   # 仅 LLM 清洗

BANANA_API_KEY=am_xxx python scripts/bulk_import.py process /music/inbox/*.ape \
  --upload
```

`process --upload` 未指定 `--output-dir` 时使用临时目录并在结束后清理；需要保留处理产物时才显式传 `--output-dir`。

### `bulk_import.py upload` — 直接上传到后端

对已有文件执行与前端一致的查重、上传、轮询和建库流程。

```bash
BANANA_API_KEY=am_xxx python scripts/bulk_import.py upload ./processed/*.flac \
  --base-url http://localhost:8000
```

### 批量导入建议

大量导入时，服务端的 LLM 清洗任务会积压并与 Ollama 推理资源竞争。推荐工作流：

1. 用 `bulk_import.py process` 离线预处理所有文件（转码 + LLM 清洗 + 标签写入副本）
2. 在管理后台禁用 **LLM Metadata Parser** 插件
3. 将处理好的文件通过 `bulk_import.py upload` 或 `process --upload` 批量上传到服务
4. 上传完成后重新启用插件

详见 [`docs/bulk-import.md`](docs/bulk-import.md)。

---

## 测试

```bash
# 后端（从仓库根目录）
bash scripts/backend-sync.sh --extra dev
UV_PROJECT_ENVIRONMENT="$(pwd)/backend/venv" uv run --directory backend pytest tests/ -v

# 前端
cd frontend && npm run test
```

后端测试使用内存 SQLite，不依赖 Ollama、MusicBrainz 等外部服务。`BANANA_TESTING=true` 时自动跳过 seed、插件加载和指纹后台任务。

CI：GitHub Actions `test` workflow 在 `push` / `pull_request` 到 `main` 时运行。

---

## 文档索引

| 文档 | 内容 |
|---|---|
| [`docs/plugin-api.md`](docs/plugin-api.md) | 插件开发完整规范：接口契约、生命周期、流水线阶段、错误处理、完整骨架示例 |
| [`docs/api.md`](docs/api.md) | REST API 参考：认证方式、所有端点、请求/响应格式、错误码 |
| [`docs/database-design.md`](docs/database-design.md) | 数据库 schema：19 张表的 DDL、约束关系、版本迁移策略 |
| [`docs/bulk-import.md`](docs/bulk-import.md) | 批量导入指南：预处理脚本详解、推荐工作流、如何关闭服务端 LLM 清洗 |
| [`CLAUDE.md`](CLAUDE.md) | 开发约定：schema 版本管理、并发写库模式、上传流水线、日志级别规范 |
