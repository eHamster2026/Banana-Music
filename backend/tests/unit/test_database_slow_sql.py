import logging

from sqlalchemy import text

import database
from config import settings
from database import engine


def test_sql_preview_compacts_and_truncates():
    statement = "SELECT  *\nFROM tracks\nWHERE title = :title " + ("x" * 600)

    preview = database._sql_preview(statement, max_len=40)

    assert "\n" not in preview
    assert "  " not in preview
    assert preview.endswith("...")
    assert len(preview) == 40


def test_slow_sql_logs_warning(monkeypatch, caplog):
    monkeypatch.setattr(settings, "slow_sql_threshold_ms", 1000)
    ticks = iter([10.0, 11.25])
    monkeypatch.setattr(database.time, "perf_counter", lambda: next(ticks))

    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))

    messages = [record.getMessage() for record in caplog.records]
    assert any("slow SQL:" in message and "elapsed=1250.0ms" in message for message in messages)
    assert any("SELECT 1" in message for message in messages)
