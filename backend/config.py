import os

from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    # ── 测试（pytest 等）────────────────────────────────────────────────────────
    # 设为 true 时使用独立内存库、跳过 seed 与插件/指纹后台任务，不写 schema_migrations。
    banana_testing: bool = False

    # ── JWT ────────────────────────────────────────────────────────────────────
    secret_key: str = "change-me-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7  # 7 days

    # ── Database ───────────────────────────────────────────────────────────────
    database_url: str = "sqlite:///music.db"

    # ── CORS ───────────────────────────────────────────────────────────────────
    # Comma-separated origins, e.g. "http://localhost:5173,https://example.com"
    # Use "*" to allow all (not recommended in production)
    cors_origins: List[str] = ["*"]

    # ── Seed / demo account ────────────────────────────────────────────────────
    demo_username: str = "demo"
    demo_email: str = "demo@example.com"
    demo_password: str = "demo123"

    # ── Server ────────────────────────────────────────────────────────────────
    app_port: int = 8000

    # ── Upload ────────────────────────────────────────────────────────────────
    # Max threads used for upload processing. Default keeps at least one CPU core free.
    upload_max_workers: int = max(1, (os.cpu_count() or 4) - 1)
    # Chromaprint 指纹队列与后台 worker；未装 fpcalc 时设为 false 可避免相关日志与任务
    fingerprint_enabled: bool = True
    # 指纹写入后自动调用元数据插件补全（仅填补未知艺人/无专辑等；默认关闭）
    upload_auto_metadata_after_fingerprint: bool = False

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
