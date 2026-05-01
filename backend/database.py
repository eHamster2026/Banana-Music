from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.pool import StaticPool
from config import settings

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
if engine.dialect.name == "sqlite":
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(conn, _record):
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    pass
