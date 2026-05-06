from pathlib import Path
import logging
import time

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.pool import StaticPool
from config import settings

logger = logging.getLogger("uvicorn.error")

if settings.banana_testing:
    # 单连接池 + 空路径 SQLite：测试进程内共享同一块内存库，且与生产文件库隔离。
    _connect_args = {"check_same_thread": False}
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args=_connect_args,
        poolclass=StaticPool,
    )
else:
    _db_url = settings.database_url

    # Anchor relative SQLite paths to <project-root>/data/ so the database lives
    # outside the source tree regardless of the working directory uvicorn runs from.
    if _db_url.startswith("sqlite:///") and not _db_url.startswith("sqlite:////"):
        _rel = _db_url[len("sqlite:///"):]
        if not Path(_rel).is_absolute():
            _data_dir = Path(__file__).parent.parent / "data"
            _data_dir.mkdir(exist_ok=True)
            _db_url = f"sqlite:///{_data_dir / Path(_rel).name}"

    _connect_args = {"check_same_thread": False} if _db_url.startswith("sqlite") else {}

    # SQLite: 等待锁最多 30 秒，避免并发写入时立即报 "database is locked"
    if _db_url.startswith("sqlite"):
        _connect_args["timeout"] = 30

    engine = create_engine(_db_url, connect_args=_connect_args)

# SQLite WAL 模式：允许读写并发，减少锁竞争
from sqlalchemy import event

if engine.dialect.name == "sqlite":
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(conn, _record):
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")


def _sql_preview(statement: str, *, max_len: int = 500) -> str:
    text = " ".join((statement or "").split())
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _slow_sql_threshold_sec() -> float:
    threshold_ms = max(0, int(settings.slow_sql_threshold_ms or 0))
    return threshold_ms / 1000.0


@event.listens_for(engine, "before_cursor_execute")
def _before_cursor_execute(conn, _cursor, _statement, _parameters, _context, _executemany):
    threshold = _slow_sql_threshold_sec()
    if threshold <= 0:
        return
    conn.info.setdefault("_banana_sql_start_time", []).append(time.perf_counter())


@event.listens_for(engine, "after_cursor_execute")
def _after_cursor_execute(conn, cursor, statement, _parameters, _context, executemany):
    stack = conn.info.get("_banana_sql_start_time")
    if not stack:
        return
    elapsed = time.perf_counter() - stack.pop()
    threshold = _slow_sql_threshold_sec()
    if threshold <= 0 or elapsed < threshold:
        return
    logger.warning(
        "slow SQL: elapsed=%.1fms threshold=%dms rowcount=%s executemany=%s sql=%s",
        elapsed * 1000,
        int(threshold * 1000),
        getattr(cursor, "rowcount", None),
        executemany,
        _sql_preview(statement),
    )


@event.listens_for(engine, "handle_error")
def _handle_sql_error(exception_context):
    conn = getattr(exception_context, "connection", None)
    if conn is None:
        return
    stack = conn.info.get("_banana_sql_start_time")
    if stack:
        stack.pop()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    pass
