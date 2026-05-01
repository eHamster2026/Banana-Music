# 每次破坏性 schema 变更时递增此整数。
# main.py 将 DB 中最新版本号与 SCHEMA_VERSION 比较；
# 任何环境版本不匹配都会直接启动失败；必须手动迁移或手动 reset。
#
# History:
#    1  initial schema
#    2  tracks: audio_hash, audio_fingerprint
#    3  users: is_admin
#    4  tracks: file_hash (raw-bytes SHA-256 for client-side pre-check)
#    5  (no schema change) APE/WMA input; lossless → FLAC level-5 + ReplayGain
#    6  audio_hash changed from SHA-256 (32 B) to PCM MD5 (16 B); existing hashes incompatible
#    7  users: api_key (LLM / programmatic access)
#    8  albums.cover_path, tracks.cover_path
#    9  fingerprint_tasks（指纹任务表）
#   10  playlists：部分唯一索引 (user_id, lower(name))，用户歌单名不重复
#   11  schema_migrations 表（替代 data/schema_version 文件）；track_artists / album_artists
#       多艺人关联表；移除 user_library_{albums,artists}.added_at；
#       play_queues.updated_at FLOAT → INTEGER
#   12  upload_staging 表（替代内存 _upload_cache，持久化上传暂存数据）
#   13  tracks.track_number 语义修正：0 → NULL，default=NULL（编号不明）
#   14  parse_upload_tasks 表（parse_upload 任务持久化，替代 fire-and-forget asyncio.create_task）
#   15  schema_migrations.version 列类型 String → Integer
#   16  audio_hash ORM 定义修正为 PCM MD5（16 B），并设为 NOT NULL
#   17  tracks: 移除 file_hash；上传与去重统一使用 audio_hash

SCHEMA_VERSION = 17
