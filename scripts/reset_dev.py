"""
scripts/reset_dev.py

Clears all dev data: SQLite database + uploaded audio resources + cover images.
Run manually only; main.py never calls this automatically.

Production guard: exits immediately if APP_ENV=production.
"""

import os
import sys
from pathlib import Path

ROOT     = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"


def reset(verbose: bool = True) -> None:
    if os.environ.get("APP_ENV", "development").lower() == "production":
        print("[reset_dev] Refused: APP_ENV=production.", file=sys.stderr)
        sys.exit(1)

    log = print if verbose else (lambda *a, **k: None)

    # Delete database files
    db_files = (
        list(DATA_DIR.glob("*.db")) +
        list(DATA_DIR.glob("*.db-shm")) +
        list(DATA_DIR.glob("*.db-wal"))
    )
    for f in db_files:
        f.unlink(missing_ok=True)
        log(f"  [reset] Deleted database: {f.name}")

    # Clear uploaded audio files
    resource_dir = DATA_DIR / "resource"
    if resource_dir.exists():
        files = [f for f in resource_dir.iterdir() if f.is_file()]
        for f in files:
            f.unlink(missing_ok=True)
        if files:
            log(f"  [reset] Cleared {len(files)} audio file(s) from resource/")

    # Clear persisted album/track cover files (same tree as main.py /covers mount)
    cover_dir = DATA_DIR / "covers"
    if cover_dir.exists():
        cover_files = [f for f in cover_dir.iterdir() if f.is_file()]
        for f in cover_files:
            f.unlink(missing_ok=True)
        if cover_files:
            log(f"  [reset] Cleared {len(cover_files)} cover file(s) from covers/")

    # 遗留的 data/schema_version 文件（v0.11 前）；main 启动时也会删，此处双保险
    (DATA_DIR / "schema_version").unlink(missing_ok=True)

    log("[reset] Dev data cleared.")


if __name__ == "__main__":
    print("=== Banana Music dev reset ===")
    reset(verbose=True)
