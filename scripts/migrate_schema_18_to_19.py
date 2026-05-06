"""
Manual SQLite migration from schema 18 to 19.

Run from the repository root after backing up data/music.db:
  python scripts/migrate_schema_18_to_19.py
"""

from __future__ import annotations

import argparse
import sqlite3
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "music.db"


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in rows)


def migrate(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        current = conn.execute(
            "SELECT version FROM schema_migrations ORDER BY applied_at DESC LIMIT 1"
        ).fetchone()
        if not current or current[0] != 18:
            raise RuntimeError(f"expected schema version 18, found {current[0] if current else None!r}")

        with conn:
            if not _has_column(conn, "tracks", "is_local"):
                conn.execute("ALTER TABLE tracks ADD COLUMN is_local BOOLEAN NOT NULL DEFAULT 0")
                conn.execute("UPDATE tracks SET is_local = 1 WHERE stream_url LIKE '/resource/%'")
                conn.execute("CREATE INDEX IF NOT EXISTS ix_tracks_is_local ON tracks (is_local)")

            for table in ("tracks", "albums", "artists"):
                if not _has_column(conn, table, "ext"):
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN ext JSON NOT NULL DEFAULT '{{}}'")

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS media_images (
                  id INTEGER NOT NULL PRIMARY KEY,
                  entity_type VARCHAR(20) NOT NULL,
                  entity_id INTEGER NOT NULL,
                  image_type VARCHAR(20) NOT NULL,
                  path VARCHAR(255) NOT NULL,
                  mime_type VARCHAR(100) NOT NULL,
                  created_by_user_id INTEGER REFERENCES users (id),
                  created_at INTEGER,
                  ext JSON NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS ix_media_images_id ON media_images (id)")
            conn.execute("CREATE INDEX IF NOT EXISTS ix_media_images_entity_type ON media_images (entity_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS ix_media_images_entity_id ON media_images (entity_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS ix_media_images_image_type ON media_images (image_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS ix_media_images_entity ON media_images (entity_type, entity_id)")
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations (version, applied_at, description) VALUES (?, ?, ?)",
                (19, int(time.time()), "新增 is_local/ext 字段与 media_images 隐藏图片表"),
            )
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate Banana Music SQLite schema 18 to 19")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite database path")
    args = parser.parse_args()
    migrate(args.db)
    print(f"migrated {args.db} to schema 19")


if __name__ == "__main__":
    main()
