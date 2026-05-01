# 数据库设计（SQLite）

以下 **DDL 与当前 `backend/models.py` 经 SQLAlchemy 编译结果一致**（`BANANA_TESTING` 内存库 `create_all` 导出后整理格式）。运行时由 `Base.metadata.create_all()` 建表；**列/索引迁移**见文末说明。

```sql
-- =============================================================================
-- Banana Music — SQLite schema（与 SQLAlchemy models 对齐）
-- 执行前建议：PRAGMA foreign_keys = ON;（应用连接层已依赖外键语义）
-- =============================================================================

-- ── 版本历史（替代 data/schema_version 文件）─────────────────
-- version 与 backend/schema_version.py 中 SCHEMA_VERSION 整数一致
CREATE TABLE schema_migrations (
  version     INTEGER     NOT NULL PRIMARY KEY,
  applied_at  INTEGER     NOT NULL,
  description TEXT
);

CREATE TABLE artists (
  id                INTEGER      NOT NULL PRIMARY KEY,
  name              VARCHAR(100) NOT NULL,
  art_color         VARCHAR(20),
  bio               TEXT,
  monthly_listeners INTEGER
);

CREATE TABLE users (
  id              INTEGER      NOT NULL PRIMARY KEY,
  username        VARCHAR(50)  NOT NULL,
  email           VARCHAR(100) NOT NULL,
  hashed_password VARCHAR(200) NOT NULL,
  avatar_color    VARCHAR(20),
  is_admin        BOOLEAN,
  created_at      INTEGER,
  api_key         VARCHAR(100)
);

CREATE TABLE albums (
  id           INTEGER      NOT NULL PRIMARY KEY,
  title        VARCHAR(200) NOT NULL,
  artist_id    INTEGER      NOT NULL REFERENCES artists (id),
  art_color    VARCHAR(20),
  cover_path   VARCHAR(255),
  release_date VARCHAR(10),
  album_type   VARCHAR(20),
  created_at   INTEGER
);

-- ── 专辑多艺人关联（feat. / 合辑参与者等）───────────────────
-- 主艺人仍由 albums.artist_id 指向；本表仅存储额外参与艺人。
CREATE TABLE album_artists (
  album_id   INTEGER     NOT NULL REFERENCES albums  (id) ON DELETE CASCADE,
  artist_id  INTEGER     NOT NULL REFERENCES artists (id),
  role       VARCHAR(20) DEFAULT 'featured',  -- featured / remixer / …
  sort_order INTEGER     DEFAULT 0,
  PRIMARY KEY (album_id, artist_id)
);

CREATE TABLE tracks (
  id                INTEGER      NOT NULL PRIMARY KEY,
  title             VARCHAR(200) NOT NULL,
  album_id          INTEGER      REFERENCES albums  (id),
  artist_id         INTEGER      NOT NULL REFERENCES artists (id),
  duration_sec      INTEGER,
  track_number      INTEGER,   -- NULL = 曲目编号不明（标签缺失或 0）
  lyrics            TEXT,
  cover_path        VARCHAR(255),
  stream_url        VARCHAR(500),
  created_at        INTEGER,
  audio_hash        BLOB NOT NULL,  -- PCM MD5，16 字节
  audio_fingerprint BLOB
);

-- ── 曲目多艺人关联（feat. 等参与艺人）───────────────────────
-- 主艺人仍由 tracks.artist_id 指向；本表仅存储额外参与艺人。
CREATE TABLE track_artists (
  track_id   INTEGER     NOT NULL REFERENCES tracks  (id) ON DELETE CASCADE,
  artist_id  INTEGER     NOT NULL REFERENCES artists (id),
  role       VARCHAR(20) DEFAULT 'featured',
  sort_order INTEGER     DEFAULT 0,
  PRIMARY KEY (track_id, artist_id)
);

CREATE TABLE playlists (
  id          INTEGER      NOT NULL PRIMARY KEY,
  name        VARCHAR(200) NOT NULL,
  user_id     INTEGER      REFERENCES users (id),
  art_color   VARCHAR(20),
  description TEXT,
  is_featured BOOLEAN,
  is_system   BOOLEAN,
  created_at  INTEGER
);

CREATE TABLE playlist_tracks (
  id          INTEGER NOT NULL PRIMARY KEY,
  playlist_id INTEGER NOT NULL REFERENCES playlists (id),
  track_id    INTEGER NOT NULL REFERENCES tracks    (id),
  position    INTEGER
);

CREATE TABLE user_track_likes (
  user_id  INTEGER NOT NULL REFERENCES users  (id),
  track_id INTEGER NOT NULL REFERENCES tracks (id),
  liked_at INTEGER,
  PRIMARY KEY (user_id, track_id)
);

-- added_at 已于 v0.11 移除；排序改为按 album_id DESC
CREATE TABLE user_library_albums (
  user_id  INTEGER NOT NULL REFERENCES users  (id),
  album_id INTEGER NOT NULL REFERENCES albums (id),
  PRIMARY KEY (user_id, album_id)
);

-- added_at 已于 v0.11 移除；排序改为按 artist_id DESC
CREATE TABLE user_library_artists (
  user_id   INTEGER NOT NULL REFERENCES users   (id),
  artist_id INTEGER NOT NULL REFERENCES artists (id),
  PRIMARY KEY (user_id, artist_id)
);

CREATE TABLE play_history (
  id        INTEGER NOT NULL PRIMARY KEY,
  user_id   INTEGER NOT NULL REFERENCES users  (id),
  track_id  INTEGER NOT NULL REFERENCES tracks (id),
  played_at INTEGER
);

CREATE TABLE play_queues (
  id            INTEGER      NOT NULL PRIMARY KEY,
  user_id       INTEGER      NOT NULL UNIQUE REFERENCES users (id),
  cursor        INTEGER,
  is_playing    BOOLEAN,
  position_sec  FLOAT,        -- 播放进度秒数，保持 FLOAT 精度
  repeat_mode   VARCHAR(10),
  shuffle       BOOLEAN,
  active_device VARCHAR(128),
  updated_at    INTEGER       -- Unix 秒（v0.11 由 FLOAT 改为 INTEGER）
);

CREATE TABLE play_queue_items (
  id        INTEGER NOT NULL PRIMARY KEY,
  queue_id  INTEGER NOT NULL REFERENCES play_queues (id),
  track_id  INTEGER NOT NULL REFERENCES tracks      (id),
  order_idx INTEGER NOT NULL
);

CREATE TABLE fingerprint_tasks (
  id         INTEGER NOT NULL PRIMARY KEY,
  track_id   INTEGER NOT NULL UNIQUE REFERENCES tracks (id) ON DELETE CASCADE,
  created_at INTEGER
);

-- ── 上传：暂存（upload-file → create）与 parse_upload 任务队列 ───
CREATE TABLE upload_staging (
  file_key      VARCHAR NOT NULL PRIMARY KEY,
  audio_hash    BLOB NOT NULL, -- PCM MD5，16 字节
  original_name VARCHAR NOT NULL,
  duration_sec  INTEGER,
  created_at    INTEGER
);

CREATE TABLE parse_upload_tasks (
  id             INTEGER NOT NULL PRIMARY KEY,
  track_id       INTEGER NOT NULL UNIQUE REFERENCES tracks (id) ON DELETE CASCADE,
  filename_stem  VARCHAR(500) NOT NULL,
  raw_tags       TEXT,
  created_at     INTEGER
);

CREATE TABLE banners (
  id          INTEGER      NOT NULL PRIMARY KEY,
  title       VARCHAR(200) NOT NULL,
  subtitle    VARCHAR(300),
  badge       VARCHAR(100),
  art_color   VARCHAR(20),
  btn_text    VARCHAR(50),
  target_type VARCHAR(20),
  target_id   INTEGER,
  sort_order  INTEGER,
  is_active   BOOLEAN
);

-- ── 索引（与 ORM 中 index=True / unique / __table_args__ 一致）────────────

CREATE INDEX ix_artists_id ON artists (id);
CREATE INDEX ix_users_id   ON users   (id);
CREATE UNIQUE INDEX ix_users_username ON users (username);
CREATE UNIQUE INDEX ix_users_email    ON users (email);
CREATE UNIQUE INDEX ix_users_api_key  ON users (api_key);

CREATE INDEX ix_albums_id ON albums (id);

CREATE INDEX ix_tracks_id        ON tracks (id);
CREATE UNIQUE INDEX ix_tracks_audio_hash ON tracks (audio_hash);

CREATE INDEX ix_playlists_id ON playlists (id);
CREATE UNIQUE INDEX uq_playlists_user_id_lower_name
  ON playlists (user_id, lower(name))
  WHERE user_id IS NOT NULL;

CREATE INDEX ix_playlist_tracks_id ON playlist_tracks (id);

CREATE INDEX ix_play_history_id ON play_history (id);

CREATE INDEX ix_fingerprint_tasks_id ON fingerprint_tasks (id);

CREATE INDEX ix_parse_upload_tasks_id ON parse_upload_tasks (id);

CREATE INDEX ix_banners_id ON banners (id);
```

---

## 辅助说明（非 DDL）

| 主题 | 说明 |
|------|------|
| 权威源码 | `backend/models.py`；版本号 `backend/schema_version.py`（`SCHEMA_VERSION`）；启动检查 `backend/main.py`（仅空库初始化，不自动迁移）。 |
| 版本管理 | 版本历史写入 `schema_migrations` 表（v0.11 起），**`version` 为整数**（与 `SCHEMA_VERSION` 一致），替代原 `data/schema_version` 文件。版本不匹配时应用直接启动失败，必须手动迁移或手动 reset。 |
| 库文件 | 默认 `sqlite:///music.db` → 实际文件 **`data/music.db`**（相对路径相对仓库根，见 `database.py`）。 |
| WAL | 连接后由应用执行 `PRAGMA journal_mode=WAL` 等，**不在上表内**。 |
| `audio_hash` | 格式无关音频摘要 BLOB，PCM MD5（16 字节），NOT NULL，**全局唯一**；历史长度变更见 `schema_version.py` 注释。 |
| `audio_fingerprint` | Chromaprint 指纹，后台任务写入。 |
| 多艺人 | `track_artists` / `album_artists` 存储 featured 等额外参与艺人；主艺人仍由 `tracks.artist_id` / `albums.artist_id` 指向。API 响应中以 `featured_artists` 字段暴露。搜索接口同时匹配 featured 艺人名。 |
| 歌单唯一 | `uq_playlists_user_id_lower_name`：`user_id` 非空时 `(user_id, lower(name))` 唯一；`user_id IS NULL` 的系统歌单不参与；冲突 API **409**。 |
| 老库补索引 | 若缺 `uq_playlists_user_id_lower_name`，需手动执行与上表等价的 `CREATE UNIQUE INDEX ... WHERE user_id IS NOT NULL`。 |
| `play_queues.updated_at` | v0.11 由 FLOAT 改为 INTEGER Unix 秒；`position_sec` 为播放进度保持 FLOAT。老库需手动执行 `CAST(ROUND(updated_at) AS INTEGER)` 迁移。 |
| `user_library_*.added_at` | v0.11 移除；列表排序改为按主键 id 降序。旧库如仍保留该列，需手动迁移，ORM 会忽略它。 |
| 测试库 | `BANANA_TESTING=true` 时使用内存 SQLite，不写入 `schema_migrations`。 |

**维护**：改表结构时先改 `models.py`、递增 `SCHEMA_VERSION` 并准备人工迁移方案，再更新本节 SQL（可用仓库内 `uv run python` 调用 `CreateTable`/`CreateIndex` 对 `Base.metadata` 重新导出校对）。
