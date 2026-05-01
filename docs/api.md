# REST API 参考

Banana Music 后端提供 HTTP REST API，供前端、脚本及 LLM 工具调用。

**Base URL**：`http://localhost:8000`（生产环境按实际部署地址替换）

**交互式文档**：启动后访问 `/docs`（Swagger UI）或 `/redoc`。

---

## 认证

支持两种方式（**Bearer 优先**，同时存在时取 Bearer）：

| 方式 | Header | 说明 |
|------|--------|------|
| JWT | `Authorization: Bearer <access_token>` | 登录后前端使用 |
| API Key | `X-API-Key: am_<key>` | 设置页生成，适合脚本/工具 |

API Key 权限与生成该 Key 的账号一致；管理员账号可调用 `/admin/*`。

**免认证只读端点**：`GET /search`、`GET /search/suggestions`。

---

## 端点概览

### 认证（`/auth`）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/auth/register` | 注册新用户 |
| POST | `/auth/login` | 登录，返回 JWT `access_token` |
| GET | `/auth/me` | 当前用户信息 |
| POST | `/auth/api-key/generate` | 为当前用户生成 API Key |
| DELETE | `/auth/api-key/revoke` | 吊销 API Key |

---

### 搜索（`/search`）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/search?q=<关键词>` | 全文搜索；已登录时合并 `plugin_hits` |
| GET | `/search/suggestions?q=<前缀>` | 搜索建议 |

**`GET /search` 响应结构**：

```json
{
  "tracks":   [ { "id": 42, "title": "...", "artist": {...}, "album": {...} } ],
  "albums":   [ { "id": 3,  "title": "...", "artist": {...} } ],
  "artists":  [ { "id": 5,  "name": "..." } ],
  "playlists": [],
  "plugin_hits": []
}
```

`plugin_hits`：已登录且启用搜索插件时返回在线结果摘要（`plugin_id`、`source_id`、`title`、`artist`、`album`、`duration_sec`、`cover_url`、`preview_url`）。

---

### 曲目（`/tracks`）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/tracks` | 分页列出曲目 |
| GET | `/tracks/{id}` | 曲目详情 |
| GET | `/tracks/{id}/stream` | 音频流（302 重定向至文件） |

---

### 上传（`/tracks/upload-*`、`/tracks/create`）

三步异步上传流程：

```
1. GET  /tracks/check-hash?h=<sha256>          → 预检文件是否已在库中
2. POST /tracks/upload-file  (multipart)        → 落盘，返回 job_id
   GET  /tracks/upload-status/{job_id}          → 轮询（pending/processing/done/error）
3. POST /tracks/create  { "file_key": "...", "parse_metadata": true } → 写入曲库，返回 track_id
```

**轮询成功（state: done, status: ok）响应**：

```json
{
  "state": "done",
  "status": "ok",
  "file_key": "abc123.flac",
  "audio_hash": "...",
  "duration_sec": 269,
  "parsed_metadata": {
    "title": "晴天",
    "artist": "周杰伦",
    "artists": ["周杰伦", "杨瑞代"],
    "album": "叶惠美",
    "track_number": 1
  }
}
```

**轮询返回重复（status: duplicate）**：直接使用 `track_id`，跳过第 3 步。

`POST /tracks/create` 请求体必须包含 `{ "file_key": "..." }`，可选 `parse_metadata` 默认为 `true`。元数据由服务端从 `upload_staging` 与文件标签解析；`parse_metadata: true` 时入库后会异步执行 `parse_upload` 流水线（重启不丢任务），`false` 时跳过该清洗任务。

---

### 专辑（`/albums`）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/albums` | 专辑列表 |
| GET | `/albums/{id}` | 专辑详情（含曲目列表，按 `track_number` 升序，NULL 置后） |
| GET | `/albums/{id}/cover` | 封面图（302 重定向） |

---

### 艺人（`/artists`）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/artists` | 艺人列表 |
| GET | `/artists/{id}` | 艺人详情 |
| GET | `/artists/{id}/monthly-listeners` | 月听众数 |

---

### 歌单（`/playlists`）

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| GET | `/playlists` | 歌单列表（含公共和当前用户） | 可选 |
| POST | `/playlists` | 创建歌单 | 登录 |
| GET | `/playlists/{id}` | 歌单详情（含曲目） | 可选 |
| PUT | `/playlists/{id}` | 更新歌单信息 | 登录（本人/管理员）|
| DELETE | `/playlists/{id}` | 删除歌单 | 登录（本人/管理员）|
| POST | `/playlists/{id}/tracks` | 向歌单添加曲目 | 登录 |
| DELETE | `/playlists/{id}/tracks/{pos}` | 从歌单移除曲目 | 登录 |

同一用户下歌单名**不区分大小写**唯一，冲突返回 **409**。

---

### 播放队列（`/queue`）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/queue` | 当前用户队列状态 |
| POST | `/queue/command` | 更新队列状态；返回值用于裁决当前设备是否仍可继续播放 |
| GET | `/queue/events` | 兼容端点；前端播放同步不再依赖 SSE |

---

### 用户资料库（`/library`）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/library/tracks` | 已收藏曲目 |
| POST/DELETE | `/library/tracks/{id}` | 收藏/取消收藏曲目 |
| GET | `/library/albums` | 已收藏专辑 |
| POST/DELETE | `/library/albums/{id}` | 收藏/取消收藏专辑 |
| GET | `/library/artists` | 已关注艺人 |
| POST/DELETE | `/library/artists/{id}` | 关注/取消关注艺人 |

---

### 播放历史（`/history`）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/history` | 记录一次播放 |
| GET | `/history` | 当前用户播放历史（分页）|

---

### 首页（`/home`）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/home` | 聚合首页数据（新歌、近期专辑、精选艺人）|

---

### 插件（`/plugins`）

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| GET | `/plugins` | 列出所有插件及状态 | 管理员 |
| GET | `/plugins/{id}` | 插件详情 + config schema | 管理员 |
| PUT | `/plugins/{id}/config` | 保存插件配置 | 管理员 |
| POST | `/plugins/{id}/enable` | 启用插件 | 管理员 |
| POST | `/plugins/{id}/disable` | 禁用插件 | 管理员 |
| POST | `/plugins/{id}/reload` | 重载插件（不重启服务）| 管理员 |
| GET | `/plugins/search?q=<关键词>` | 调用搜索插件 | 登录 |
| POST | `/plugins/download` | 调用下载插件入库 | 登录 |
| POST | `/plugins/metadata/lookup` | 元数据候选查询 | 管理员 |

---

### 管理（`/admin`）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/admin/tracks` | 曲目列表（可过滤 `missing_metadata=true`） |
| PUT | `/admin/tracks/{id}` | 更新单条曲目元数据 |
| POST | `/admin/tracks/batch-update` | 批量更新（最多 50 条/次） |
| DELETE | `/admin/tracks/{id}` | 删除曲目及文件 |
| GET | `/admin/stats` | 库统计（总曲目/专辑/艺人数，元数据缺失数）|
| GET | `/admin/users` | 用户列表 |
| DELETE | `/admin/users/{id}` | 删除用户 |

**`PUT /admin/tracks/{id}` 请求体**（所有字段可选）：

```json
{
  "title": "晴天",
  "artist_name": "周杰伦",
  "album_title": "叶惠美",
  "track_number": 1,
  "duration_sec": 269,
  "lyrics": "..."
}
```

`album_title` 传 `""` 移除专辑关联；不存在的艺人/专辑自动创建。

**`POST /admin/tracks/batch-update` 请求体**：

```json
{
  "updates": [
    { "id": 42, "artist_name": "周杰伦" },
    { "id": 43, "album_title": "" }
  ]
}
```

**返回**：`{ "updated": N, "failed": [{ "id": M, "reason": "..." }] }`

元数据变更自动追加审计日志 `data/logs/metadata_changes.jsonl`。

---

## 通用错误码

| 状态码 | 含义 |
|--------|------|
| 400 | 参数错误 |
| 401 | 未认证 |
| 403 | 权限不足 |
| 404 | 资源不存在 |
| 409 | 冲突（如歌单重名）|
| 422 | 请求体校验失败 |
| 502 | 插件上游服务不可达（`PluginUpstreamError`）|
| 500 | 服务端错误 |

---

## LLM / Agent 工具调用

以 LLM 工具方式调用本 API（含完整工作流与请求示例）见根目录 [`Agent.md`](../Agent.md)。
