# API 参考

Banana Music 后端当前只公开 `/rest/*` API。旧的顶层路径（如 `/tracks`、`/admin`、`/auth`、`/plugins`）不再直接挂载，前端代码也应直接调用新的 `/rest` 路径。

**Base URL**：`http://localhost:8000`

**交互式文档**：启动后访问 `/docs`（Swagger UI）或 `/redoc`。

---

## API 分层

| 层 | 前缀 | 说明 |
|---|---|---|
| Subsonic-shaped JSON API | `/rest/*` | 音乐库、搜索、播放、收藏、歌单等与 Subsonic 概念相近的接口 |
| Banana 扩展 API | `/rest/x-banana/*` | 登录、上传、管理、插件、当前前端专用队列命令等非 Subsonic 能力 |

当前 `/rest/*` **不是完整 Subsonic 兼容实现**：不支持 `u+t+s` 鉴权、XML、`subsonic-response` envelope、标准 Subsonic 错误码或转码。它只是采用 Subsonic 风格命名的 JSON API。

---

## 认证

仍使用当前项目认证方式（**Bearer 优先**，同时存在时取 Bearer）：

| 方式 | Header | 说明 |
|------|--------|------|
| JWT | `Authorization: Bearer <access_token>` | 前端登录后使用 |
| API Key | `X-API-Key: am_<key>` | 适合脚本/工具 |

API Key 权限与生成该 Key 的账号一致；管理员账号可调用 `/rest/x-banana/admin/*`。

免认证只读端点主要包括：

- `GET /rest/search3?query=<关键词>`
- `GET /rest/getSongs`
- `GET /rest/getSong`
- `GET /rest/getAlbumList2`
- `GET /rest/getAlbum`
- `GET /rest/getArtists`
- `GET /rest/getArtist`

已登录调用 `search3` 时可能额外返回 `plugin_hits`。

---

## 核心 `/rest` 端点

### 系统

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/rest/ping` | 健康检查 |
| GET | `/rest/getLicense` | 返回 `{ "valid": true }` |

### 曲目

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/rest/getSongs?skip=0&limit=100&sort=default&local=false` | 分页列出曲目；`sort=recent` 按新增倒序 |
| GET | `/rest/getSongCount?local=false` | 曲目总数 |
| GET | `/rest/getSong?id=<track_id>` | 曲目详情 |
| GET | `/rest/getStreamInfo?id=<track_id>` | 返回播放 URL 信息 `{track_id, stream_url, expires_in}` |
| GET | `/rest/stream?id=<track_id>` | 返回本地音频文件，或重定向到远程 `stream_url` |
| GET | `/rest/download?id=<track_id>` | 下载本地音频文件；远程 URL 不支持下载 |
| GET | `/rest/getLyrics?id=<track_id>` | 歌词 |
| GET | `/rest/getCoverArt?id=<id>&type=track|album` | 曲目或专辑封面 |

### 专辑与艺人

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/rest/getAlbumList2?skip=0&limit=100&sort=default` | 专辑列表；`sort` 支持 `default`、`recent`、`newest`、`random` |
| GET | `/rest/getAlbumCount` | 专辑总数 |
| GET | `/rest/getAlbum?id=<album_id>` | 专辑详情，含曲目 |
| GET | `/rest/getArtists?skip=0&limit=100` | 艺人列表 |
| GET | `/rest/getArtistCount` | 艺人总数 |
| GET | `/rest/getArtist?id=<artist_id>` | 艺人详情 |
| GET | `/rest/getArtistAlbums?id=<artist_id>` | 艺人相关专辑 |
| GET | `/rest/getArtistSongs?id=<artist_id>&skip=0&limit=100` | 艺人相关曲目 |

### 搜索

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/rest/search3?query=<关键词>` | 搜索曲目、专辑、艺人、歌单；已登录时合并插件结果 |

响应结构保持当前前端所需形态：

```json
{
  "tracks": [],
  "albums": [],
  "artists": [],
  "playlists": [],
  "plugin_hits": []
}
```

### 收藏与播放记录

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/rest/getStarred2` | 当前用户收藏曲目；默认返回曲目列表以兼容前端 |
| GET | `/rest/getStarred2?includeMeta=true` | 返回 `{tracks, albums, artists}` 三类收藏 |
| POST | `/rest/toggleStar?id=<track_id>` | 切换曲目收藏；返回 `{track_id, liked}` |
| POST | `/rest/toggleStar?albumId=<album_id>` | 切换专辑收藏；返回 `{album_id, in_library}` |
| POST | `/rest/toggleStar?artistId=<artist_id>` | 切换艺人关注；返回 `{artist_id, in_library}` |
| POST | `/rest/star?id=<track_id>` | 收藏曲目 |
| POST | `/rest/star?albumId=<album_id>` | 收藏专辑 |
| POST | `/rest/star?artistId=<artist_id>` | 关注艺人 |
| POST | `/rest/unstar?id=<track_id>` | 取消收藏曲目 |
| POST | `/rest/unstar?albumId=<album_id>` | 取消收藏专辑 |
| POST | `/rest/unstar?artistId=<artist_id>` | 取消关注艺人 |
| POST | `/rest/scrobble?id=<track_id>` | 记录播放；也兼容请求体 `{ "track_id": 1 }` |

### 歌单

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/rest/getPlaylists` | 当前用户歌单 |
| GET | `/rest/getPlaylist?id=<playlist_id>` | 歌单详情，含曲目 |
| GET | `/rest/exportPlaylist?id=<playlist_id>` | 导出歌单 JSON 附件 |
| POST | `/rest/createPlaylist` | 创建歌单 |
| PUT | `/rest/updatePlaylist?id=<playlist_id>` | 更新歌单信息 |
| DELETE | `/rest/deletePlaylist?id=<playlist_id>` | 删除歌单 |
| POST | `/rest/addToPlaylist?id=<playlist_id>` | 向歌单添加曲目，请求体 `{ "track_id": 1 }` |
| DELETE | `/rest/removeFromPlaylist?id=<playlist_id>&track_id=<track_id>` | 从歌单移除曲目 |

创建/更新歌单请求体：

```json
{
  "name": "My Playlist",
  "description": "optional",
  "art_color": "art-1"
}
```

导出歌单返回 `banana-playlist.v1` JSON，不包含音频文件本体，也不包含 `stream_url` / `download_url` / `cover_url`。曲目按歌单顺序输出，使用 `audio_hash` 作为稳定音频标识；如已有 Chromaprint 指纹则包含 `audio_fingerprint`，如有封面则包含封面内容 SHA-256 `cover_hash`。

### 播放队列

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/rest/getPlayQueue` | 当前用户播放队列状态 |

完整的当前前端队列命令仍走 Banana 扩展：`POST /rest/x-banana/queue/command`。

---

## Banana 扩展 `/rest/x-banana`

### 认证

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/rest/x-banana/auth/register` | 注册新用户 |
| POST | `/rest/x-banana/auth/login` | 登录，返回 JWT `access_token` |
| GET | `/rest/x-banana/auth/me` | 当前用户信息 |
| POST | `/rest/x-banana/auth/api-key/generate` | 为当前用户生成 API Key |
| DELETE | `/rest/x-banana/auth/api-key/revoke` | 吊销 API Key |

登录请求体：

```json
{
  "username": "demo",
  "password": "demo123"
}
```

### 首页

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/rest/x-banana/home` | 当前前端首页聚合数据 |

### 上传

上传流程：

```text
1. GET  /rest/x-banana/tracks/exists-by-hash?audio_hash=<32位hex>  # 可选，客户端能计算时先查重
2. POST /rest/x-banana/plugins/llm-metadata/parse-metadata         # 前端提交解析出的 raw_tags 做 LLM 清洗
3. POST /rest/x-banana/tracks/upload-file       multipart: file
   GET  /rest/x-banana/tracks/upload-status/{job_id}
4. POST /rest/x-banana/tracks/covers/upload     multipart: file      # 可选，先上传封面
5. POST /rest/x-banana/tracks/create            { "file_key": "...", "metadata": {...}, "cover_id": "..." }
```

轮询成功（`state: done, status: ok`）响应：

```json
{
  "state": "done",
  "status": "ok",
  "file_key": "abc123.flac"
}
```

重复内容会在上传处理阶段按 `audio_hash` 识别，并返回 `{ "state": "done", "status": "duplicate", "track_id": 123, "title": "..." }`。`POST /rest/x-banana/tracks/create` 请求体必须包含 `{ "file_key": "..." }`，元数据由客户端解析/清洗后通过 `metadata` 提交；后端不再解析音频标签，也不再入队 `parse_upload` 后台任务。

批量导入工具可在调用 LLM 前先用 `GET /rest/x-banana/tracks/exists-by-hash?audio_hash=<32位hex>` 查询是否重复。该接口匿名可用，命中返回 `{ "exists": true, "track_id": 123, "title": "..." }`，未命中返回 `{ "exists": false, "track_id": null, "title": null }`。

### 元数据扩展与隐藏图片

安全模型：任意登录用户可以增加库信息；修改或删除已有信息需要管理员权限。

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/rest/x-banana/media-images` | 登录用户新增隐藏图片，表单字段：`file, entity_type, entity_id, image_type` |
| GET | `/rest/x-banana/media-images?entity_type=<track|album|artist>&entity_id=<id>` | 列出实体隐藏图片 |
| PATCH/DELETE | `/rest/x-banana/media-images/{id}` | 管理员修改或删除图片记录 |
| POST | `/rest/x-banana/metadata-ext/{entity_type}/{id}` | 登录用户新增不存在的 `ext` 顶层 key |
| PUT/PATCH/DELETE | `/rest/x-banana/metadata-ext/{entity_type}/{id}` | 管理员覆盖、修改或删除 `ext` |

隐藏图片默认不参与页面展示；下载本地曲目时会把 Track + Album 的隐藏图片写入临时下载副本。格式无法标准表达多类型图片时仅写入 cover，并跳过其它隐藏图片。

### 播放队列扩展

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/rest/x-banana/queue/command` | 当前前端完整队列命令；返回队列状态 |

`/rest/x-banana/queue/command` 支持的命令见 `schemas.QueueCommand`：`play`、`pause`、`seek`、`next`、`prev`、`play_now`、`play_next`、`append`、`replace`、`remove`、`set_repeat`、`set_shuffle`、`activate`、`sync_position`。

### 插件

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | `/rest/x-banana/plugins` | 列出所有插件及状态 | 管理员 |
| GET | `/rest/x-banana/plugins/{id}` | 插件详情 + config schema | 管理员 |
| PUT | `/rest/x-banana/plugins/{id}/config` | 保存插件配置 | 管理员 |
| POST | `/rest/x-banana/plugins/{id}/enable` | 启用插件 | 管理员 |
| POST | `/rest/x-banana/plugins/{id}/disable` | 禁用插件 | 管理员 |
| POST | `/rest/x-banana/plugins/{id}/reload` | 重载插件 | 管理员 |
| GET | `/rest/x-banana/plugins/search?q=<关键词>` | 调用搜索插件 | 登录 |
| POST | `/rest/x-banana/plugins/download` | 调用下载插件入库 | 登录 |
| POST | `/rest/x-banana/plugins/metadata/lookup` | 元数据候选查询 | 管理员 |

### 管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/rest/x-banana/admin/stats` | 曲库统计 |
| GET | `/rest/x-banana/admin/tracks` | 曲目列表；支持 `skip`、`limit`、`q`、`missing_metadata` |
| PUT | `/rest/x-banana/admin/tracks/{track_id}` | 更新单曲元数据 |
| POST | `/rest/x-banana/admin/tracks/batch-update` | 批量更新（最多 50 条/次） |
| DELETE | `/rest/x-banana/admin/tracks/{track_id}` | 删除曲目记录、文件及关联数据 |
| GET | `/rest/x-banana/admin/users` | 用户列表 |
| POST | `/rest/x-banana/admin/users` | 创建用户 |
| PUT | `/rest/x-banana/admin/users/{user_id}` | 更新用户 |
| DELETE | `/rest/x-banana/admin/users/{user_id}` | 删除用户 |

`PUT /rest/x-banana/admin/tracks/{track_id}` 请求体（所有字段可选）：

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

`album_title: ""` 表示移除专辑关联；不存在的艺人/专辑会自动创建。元数据变更会追加审计日志 `data/logs/metadata_changes.jsonl`。

## 通用错误码

| 状态码 | 含义 |
|--------|------|
| 400 | 参数错误 |
| 401 | 未认证 |
| 403 | 权限不足 |
| 404 | 资源不存在 |
| 409 | 冲突 |
| 422 | 请求体校验失败 |
| 500 | 服务端错误 |
