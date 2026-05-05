"""
Upload every audio file under a directory without local or server metadata cleanup.

Example:
  python scripts/upload_audio_dir.py /path/to/music --api-key am_xxx
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from bulk_import import (
    SUPPORTED_EXTS,
    _auth_headers,
    resolve_upload_token,
    upload_file_to_backend,
)


def iter_audio_files(root: Path, *, recursive: bool) -> list[Path]:
    pattern = "**/*" if recursive else "*"
    return sorted(
        path
        for path in root.glob(pattern)
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTS
    )


def add_auth_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base-url", default=os.getenv("BANANA_BASE_URL", "http://localhost:8000"), help="Banana Music 后端地址")
    parser.add_argument("--api-key", default=os.getenv("BANANA_API_KEY"), help="API Key（可用 BANANA_API_KEY）")
    parser.add_argument("--token", default=os.getenv("BANANA_TOKEN"), help="Bearer token（可用 BANANA_TOKEN；优先于 API Key）")
    parser.add_argument("--username", default=os.getenv("BANANA_USERNAME"), help="登录用户名（可用 BANANA_USERNAME）")
    parser.add_argument("--password", default=os.getenv("BANANA_PASSWORD"), help="登录密码（可用 BANANA_PASSWORD）")


async def run(args: argparse.Namespace) -> None:
    root = args.directory.expanduser()
    if not root.is_dir():
        logging.error("目录不存在: %s", root)
        sys.exit(1)

    paths = iter_audio_files(root, recursive=not args.no_recursive)
    if not paths:
        logging.error("目录下没有支持的音频文件: %s", root)
        sys.exit(1)

    token = await resolve_upload_token(args)
    headers = _auth_headers(args.api_key, token)
    if not headers:
        logging.warning("未提供认证信息；如后端要求登录，上传会返回 401")

    results: list[dict] = []
    for index, path in enumerate(paths, start=1):
        logging.info("[%d/%d] 上传: %s", index, len(paths), path)
        try:
            results.append(await upload_file_to_backend(
                path,
                base_url=args.base_url,
                api_key=args.api_key,
                token=token,
                parse_metadata=False,
                metadata=None,
                poll_interval=args.poll_interval,
                job_timeout=args.job_timeout,
                request_timeout=args.request_timeout,
            ))
        except Exception as exc:
            logging.error("[%s] 上传失败: %s", path, exc, exc_info=args.verbose)
            results.append({"file": str(path), "status": "error", "detail": str(exc)})

    added = sum(1 for item in results if item.get("status") == "added")
    duplicate = sum(1 for item in results if item.get("status") == "duplicate")
    failed = sum(1 for item in results if item.get("status") == "error")
    logging.info("完成：新增 %d  重复 %d  失败 %d", added, duplicate, failed)


def main() -> None:
    parser = argparse.ArgumentParser(description="直接上传目录下所有音频文件，不做本地或服务端元数据清洗")
    parser.add_argument("directory", type=Path, help="音频目录")
    parser.add_argument("--no-recursive", action="store_true", help="只读取目录第一层")
    parser.add_argument("--poll-interval", default=0.8, type=float, help="上传任务轮询间隔秒数")
    parser.add_argument("--job-timeout", default=120.0, type=float, help="单文件上传后台任务超时秒数")
    parser.add_argument("--request-timeout", default=120.0, type=float, help="HTTP 请求超时秒数")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细日志")
    add_auth_options(parser)
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s  %(message)s",
    )
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
