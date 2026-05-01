import asyncio
import subprocess
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from database import engine
from config import settings
from schema_version import SCHEMA_VERSION
import models

FRONTEND_DIR = Path(__file__).parent.parent
REACT_DIST   = FRONTEND_DIR / "frontend" / "dist"
DATA_DIR     = FRONTEND_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# ── 建表（含 schema_migrations）──────────────────────────────
# create_all 是幂等的：仅建缺失的表，不删改已有表/列。
models.Base.metadata.create_all(bind=engine)

# ── Schema 版本检查 ────────────────────────────────────────────
# 版本历史存储在 schema_migrations 表，避免文件与数据库不一致。
# 开发环境：版本不匹配时自动重置并重建；生产环境：仅追加版本记录。
import os
import time as _startup_time
from sqlalchemy import inspect, text as _sql

if not settings.banana_testing:
    with engine.connect() as _conn:
        _row = _conn.execute(
            _sql("SELECT version FROM schema_migrations ORDER BY applied_at DESC LIMIT 1")
        ).first()
        _stored = _row[0] if _row else None

    if _stored != SCHEMA_VERSION:
        if os.environ.get("APP_ENV", "development").lower() != "production":
            print(f"[schema] version changed {_stored!r} -> {SCHEMA_VERSION!r}, resetting dev data...")
            _reset_script = FRONTEND_DIR / "scripts" / "reset_dev.py"
            if _reset_script.exists():
                subprocess.run([sys.executable, str(_reset_script)], check=True)
            else:
                print(f"[schema] reset script not found at {_reset_script}, skipping auto-reset")
            # reset 后重建所有表（dispose 清空连接池，确保连到新建的 DB 文件）
            engine.dispose()
            models.Base.metadata.create_all(bind=engine)

        # 写入新版本记录（OR IGNORE：同版本重复启动时跳过）
        with engine.connect() as _conn:
            _conn.execute(
                _sql(
                    "INSERT OR IGNORE INTO schema_migrations "
                    "(version, applied_at, description) VALUES (:v, :t, :d)"
                ),
                {
                    "v": SCHEMA_VERSION,
                    "t": int(_startup_time.time()),
                    "d": "schema_migrations.version 列类型 String → Integer",
                },
            )
            _conn.commit()

    # 清理遗留版本文件（已迁移至 DB 表管理）
    _legacy = DATA_DIR / "schema_version"
    if _legacy.exists():
        _legacy.unlink()
        print("[schema] removed legacy schema_version file")

# ── 列迁移（向前兼容，不破坏已有数据）────────────────────────
# create_all 只建新表，不会给已有表加/删列。
# 生产环境跳过 reset，所以每次 schema 变更都在这里做 ALTER TABLE 兜底。

def _migrate_columns():
    insp = inspect(engine)
    with engine.connect() as conn:
        # v0.7: users.api_key
        if "api_key" not in {c["name"] for c in insp.get_columns("users")}:
            conn.execute(_sql("ALTER TABLE users ADD COLUMN api_key TEXT UNIQUE"))
            conn.commit()
            print("[migrate] added column users.api_key")

        track_columns = {c["name"] for c in insp.get_columns("tracks")}
        if "cover_path" not in track_columns:
            conn.execute(_sql("ALTER TABLE tracks ADD COLUMN cover_path TEXT"))
            conn.commit()
            print("[migrate] added column tracks.cover_path")

        album_columns = {c["name"] for c in insp.get_columns("albums")}
        if "cover_path" not in album_columns:
            conn.execute(_sql("ALTER TABLE albums ADD COLUMN cover_path TEXT"))
            conn.commit()
            print("[migrate] added column albums.cover_path")

        # v0.10: 用户歌单名唯一（不区分大小写）
        if insp.has_table("playlists") and engine.dialect.name == "sqlite":
            has_uq = conn.execute(
                _sql(
                    "SELECT 1 FROM sqlite_master WHERE type='index' "
                    "AND name='uq_playlists_user_id_lower_name' LIMIT 1"
                )
            ).first()
            if has_uq is None:
                conn.execute(
                    _sql(
                        "CREATE UNIQUE INDEX uq_playlists_user_id_lower_name "
                        "ON playlists (user_id, lower(name)) WHERE user_id IS NOT NULL"
                    )
                )
                conn.commit()
                print("[migrate] added index uq_playlists_user_id_lower_name")

        # v0.11: play_queues.updated_at FLOAT → INTEGER（ROUND 保留秒精度）
        if insp.has_table("play_queues"):
            conn.execute(
                _sql(
                    "UPDATE play_queues "
                    "SET updated_at = CAST(ROUND(updated_at) AS INTEGER) "
                    "WHERE typeof(updated_at) = 'real'"
                )
            )
            conn.commit()

        # v0.11: 删除 user_library_albums.added_at 和 user_library_artists.added_at
        # SQLite ≥ 3.35.0 才支持 DROP COLUMN；旧版本保留该列（ORM 会忽略它）。
        import sqlite3 as _sqlite3
        if tuple(int(x) for x in _sqlite3.sqlite_version.split(".")) >= (3, 35, 0):
            for _tbl in ("user_library_albums", "user_library_artists"):
                if "added_at" in {c["name"] for c in insp.get_columns(_tbl)}:
                    conn.execute(_sql(f"ALTER TABLE {_tbl} DROP COLUMN added_at"))
                    conn.commit()
                    print(f"[migrate] dropped column {_tbl}.added_at")

_migrate_columns()

from seed import seed

if not settings.banana_testing:
    seed()

from routers import auth, home, search, tracks, albums, artists, playlists, library, history, upload, admin, queue, plugins as plugins_router
import plugins.loader as plugin_loader

PLUGIN_DIR = FRONTEND_DIR / "plugins"


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.banana_testing:
        yield
        return
    # 加载插件（日志经 app_logging → uvicorn.error，与 Uvicorn 控制台一致）
    plugin_loader.init(PLUGIN_DIR)
    # 启动上传 worker（与线程池 1:1，N 个并发槽位）
    upload_tasks = [
        asyncio.create_task(upload.upload_worker())
        for _ in range(upload._upload_num_workers)
    ]
    # 启动后台指纹任务
    fp_task = asyncio.create_task(upload.fingerprint_worker())
    # 启动 parse_upload 清洗 worker（DB 持久化队列，重启后自动恢复）
    pu_task = asyncio.create_task(upload.parse_upload_worker())
    yield
    # 关闭时取消所有后台任务
    for t in upload_tasks + [fp_task, pu_task]:
        t.cancel()
    await asyncio.gather(*upload_tasks, fp_task, pu_task, return_exceptions=True)


app = FastAPI(title="Apple Music Demo API", description="Apple Music 主页 Demo 后端", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(home.router)
app.include_router(search.router)
app.include_router(upload.router)   # must come before tracks.router — /tracks/check-hash etc.
app.include_router(tracks.router)   # has /tracks/{id} wildcard — must be after upload routes
app.include_router(albums.router)
app.include_router(artists.router)
app.include_router(playlists.router)
app.include_router(library.router)
app.include_router(history.router)
app.include_router(admin.router)
app.include_router(queue.router)
app.include_router(plugins_router.router)

RESOURCE_DIR = DATA_DIR / "resource"
RESOURCE_DIR.mkdir(exist_ok=True)
COVER_DIR = DATA_DIR / "covers"
COVER_DIR.mkdir(exist_ok=True)

# Serve React build (assets)
if REACT_DIST.exists():
    app.mount("/assets", StaticFiles(directory=REACT_DIST / "assets"), name="react-assets")

# Serve uploaded audio files — all filenames are hex hashes, no encoding issues
app.mount("/resource", StaticFiles(directory=RESOURCE_DIR), name="resource")
app.mount("/covers", StaticFiles(directory=COVER_DIR), name="covers")

_DEV_HINT = {"detail": "API running. Frontend served by Vite at http://localhost:5173"}

def _serve_index():
    index = REACT_DIST / "index.html"
    if index.exists():
        return FileResponse(index)
    from fastapi.responses import JSONResponse
    return JSONResponse(_DEV_HINT, status_code=200)

@app.get("/")
def root():
    return _serve_index()

# Catch-all for SPA routing (non-API paths)
@app.get("/{full_path:path}")
def spa_fallback(full_path: str):
    api_prefixes = ("auth/", "home", "search", "tracks/", "albums/", "artists/",
                    "playlists/", "library/", "history/", "assets/", "upload", "admin/", "queue", "plugins")
    if any(full_path.startswith(p) for p in api_prefixes):
        raise HTTPException(status_code=404)
    return _serve_index()
