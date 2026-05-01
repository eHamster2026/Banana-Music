import asyncio
import time as _startup_time
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from sqlalchemy import inspect, text as _sql
from database import engine
from config import settings
from schema_version import SCHEMA_VERSION
import models

FRONTEND_DIR = Path(__file__).parent.parent
REACT_DIST   = FRONTEND_DIR / "frontend" / "dist"
DATA_DIR     = FRONTEND_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

SCHEMA_DESCRIPTION = "audio_hash ORM 定义修正为 PCM MD5（16 B），并设为 NOT NULL"

# ── Schema 版本检查 ────────────────────────────────────────────
# 版本历史存储在 schema_migrations 表，避免文件与数据库不一致。
# 所有环境：已有库版本不匹配时直接失败退出；不自动删库、不自动迁移。

def _insert_schema_version() -> None:
    with engine.connect() as conn:
        conn.execute(
            _sql(
                "INSERT OR IGNORE INTO schema_migrations "
                "(version, applied_at, description) VALUES (:v, :t, :d)"
            ),
            {
                "v": SCHEMA_VERSION,
                "t": int(_startup_time.time()),
                "d": SCHEMA_DESCRIPTION,
            },
        )
        conn.commit()


def _ensure_schema_version() -> None:
    if settings.banana_testing:
        models.Base.metadata.create_all(bind=engine)
        return

    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())

    if not existing_tables:
        models.Base.metadata.create_all(bind=engine)
        _insert_schema_version()
        return

    if "schema_migrations" not in existing_tables:
        raise RuntimeError(
            "[schema] existing database has no schema_migrations table; "
            "refusing automatic migration/reset. Run an explicit migration or reset manually."
        )

    with engine.connect() as _conn:
        _row = _conn.execute(
            _sql("SELECT version FROM schema_migrations ORDER BY applied_at DESC LIMIT 1")
        ).first()
        _stored = _row[0] if _row else None

    if _stored != SCHEMA_VERSION:
        raise RuntimeError(
            f"[schema] version mismatch: database={_stored!r}, code={SCHEMA_VERSION!r}; "
            "refusing automatic migration/reset. Run an explicit migration or reset manually."
        )

    # 清理遗留版本文件（已迁移至 DB 表管理）
    _legacy = DATA_DIR / "schema_version"
    if _legacy.exists():
        _legacy.unlink()
        print("[schema] removed legacy schema_version file")

_ensure_schema_version()

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
