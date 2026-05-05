"""
Upload every audio file under a directory without local or server metadata cleanup.

Example:
  python scripts/upload_audio_dir.py /path/to/music --api-key am_xxx
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from bulk_import_utils import (
    _auth_headers,
    add_auth_options,
    has_title_and_artist_tags,
    iter_audio_files,
    resolve_upload_token,
    upload_file_with_client,
)


async def upload_worker(
    *,
    worker_id: int,
    queue: asyncio.Queue[tuple[int, Path] | None],
    results: list[dict | None],
    total: int,
    client,
    args: argparse.Namespace,
) -> None:
    while True:
        item = await queue.get()
        try:
            if item is None:
                return
            index, path = item
            logging.info("[worker-%02d %d/%d] 上传: %s", worker_id, index, total, path)
            try:
                results[index - 1] = await upload_file_with_client(
                    client,
                    path,
                    base_url=args.base_url,
                    parse_metadata=False,
                    metadata=None,
                    poll_interval=args.poll_interval,
                    job_timeout=args.job_timeout,
                )
            except Exception as exc:
                logging.error("[%s] 上传失败: %s", path, exc, exc_info=args.verbose)
                results[index - 1] = {"file": str(path), "status": "error", "detail": str(exc)}
        finally:
            queue.task_done()


async def run(args: argparse.Namespace) -> None:
    root = args.directory.expanduser()
    if not root.is_dir():
        logging.error("目录不存在: %s", root)
        sys.exit(1)

    paths = iter_audio_files(root, recursive=not args.no_recursive)
    if not paths:
        logging.error("目录下没有支持的音频文件: %s", root)
        sys.exit(1)
    upload_paths: list[Path] = []
    skipped_metadata = 0
    for path in paths:
        if has_title_and_artist_tags(path):
            upload_paths.append(path)
        else:
            skipped_metadata += 1
            logging.warning("[%s] title 或 artist 为空，跳过", path)
    if not upload_paths:
        logging.error("没有 title 和 artist 都完整的音频文件: %s", root)
        sys.exit(1)
    paths = upload_paths

    token = await resolve_upload_token(args)
    headers = _auth_headers(args.api_key, token)
    if not headers:
        logging.warning("未提供认证信息；如后端要求登录，上传会返回 401")

    try:
        import httpx
    except ImportError:
        logging.error("请安装 httpx: pip install httpx")
        sys.exit(1)

    concurrency = max(1, args.concurrency)
    max_connections = args.max_connections or max(concurrency * 2, concurrency)
    logging.info(
        "压测上传启动：files=%d skipped_metadata=%d concurrency=%d max_connections=%d poll_interval=%.2fs",
        len(paths),
        skipped_metadata,
        concurrency,
        max_connections,
        args.poll_interval,
    )

    queue: asyncio.Queue[tuple[int, Path] | None] = asyncio.Queue()
    results: list[dict | None] = [None] * len(paths)
    for item in enumerate(paths, start=1):
        queue.put_nowait(item)
    for _ in range(concurrency):
        queue.put_nowait(None)

    limits = httpx.Limits(max_connections=max_connections, max_keepalive_connections=max_connections)
    timeout = httpx.Timeout(args.request_timeout)
    async with httpx.AsyncClient(timeout=timeout, headers=headers, limits=limits) as client:
        workers = [
            asyncio.create_task(upload_worker(
                worker_id=index,
                queue=queue,
                results=results,
                total=len(paths),
                client=client,
                args=args,
            ))
            for index in range(1, concurrency + 1)
        ]
        await queue.join()
        await asyncio.gather(*workers)

    compact_results = [item or {"status": "error", "detail": "missing worker result"} for item in results]

    added = sum(1 for item in compact_results if item.get("status") == "added")
    duplicate = sum(1 for item in compact_results if item.get("status") == "duplicate")
    failed = sum(1 for item in compact_results if item.get("status") == "error")
    logging.info("完成：新增 %d  重复 %d  跳过元数据不完整 %d  失败 %d", added, duplicate, skipped_metadata, failed)


def main() -> None:
    parser = argparse.ArgumentParser(description="直接上传目录下所有音频文件，不做本地或服务端元数据清洗")
    parser.add_argument("directory", type=Path, help="音频目录")
    parser.add_argument("--no-recursive", action="store_true", help="只读取目录第一层")
    parser.add_argument("--concurrency", default=64, type=int, help="并发上传 worker 数（默认 64，用于压测）")
    parser.add_argument("--max-connections", default=0, type=int, help="HTTP 连接池上限；0 表示自动按并发数放大")
    parser.add_argument("--poll-interval", default=0.2, type=float, help="上传任务轮询间隔秒数")
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
