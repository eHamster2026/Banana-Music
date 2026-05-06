"""
Upload every audio file under a directory without local or server metadata cleanup.

Example:
  python scripts/upload_audio_dir.py /path/to/music --api-key am_xxx
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

from bulk_import_utils import (
    _auth_headers,
    add_auth_options,
    iter_audio_files,
    read_embedded_metadata,
    resolve_upload_token,
    upload_file_with_client,
)


class UploadInterrupted(Exception):
    """Raised when the second interrupt requests immediate cancellation."""


async def upload_worker(
    *,
    worker_id: int,
    queue: asyncio.Queue[tuple[int, Path] | None],
    results: list[dict | None],
    total: int,
    client,
    args: argparse.Namespace,
    graceful_stop_event: asyncio.Event,
) -> None:
    while True:
        try:
            item = await queue.get()
        except asyncio.CancelledError:
            return
        try:
            if item is None:
                return
            index, path = item
            if graceful_stop_event.is_set():
                results[index - 1] = {"file": str(path), "status": "interrupted", "detail": "not started"}
                continue
            logging.info("[worker-%02d %d/%d] 检查标签: %s", worker_id, index, total, path)
            try:
                metadata = await asyncio.to_thread(
                    read_embedded_metadata,
                    path,
                    timeout=args.metadata_check_timeout,
                )
                if not metadata or not metadata.title or not metadata.artists:
                    logging.warning("[%s] title 或 artist 为空，跳过", path)
                    results[index - 1] = {"file": str(path), "status": "skipped", "detail": "title_or_artist_missing"}
                    continue

                logging.info(
                    "[worker-%02d %d/%d] 上传: %s title=%r artists=%r",
                    worker_id,
                    index,
                    total,
                    path,
                    metadata.title,
                    metadata.artists,
                )
                results[index - 1] = await upload_file_with_client(
                    client,
                    path,
                    base_url=args.base_url,
                    parse_metadata=False,
                    metadata=metadata,
                    poll_interval=args.poll_interval,
                    job_timeout=args.job_timeout,
                )
            except Exception as exc:
                logging.error("[%s] 上传失败: %s", path, exc, exc_info=args.verbose)
                results[index - 1] = {"file": str(path), "status": "error", "detail": str(exc)}
        finally:
            queue.task_done()


def _install_stop_handlers() -> tuple[asyncio.Event, asyncio.Event]:
    graceful_stop_event = asyncio.Event()
    force_stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def request_stop() -> None:
        if not graceful_stop_event.is_set():
            logging.warning("收到中断信号：停止启动新任务，等待当前上传结束；再次 Ctrl-C 将立即中止")
            graceful_stop_event.set()
            return
        if not force_stop_event.is_set():
            logging.warning("再次收到中断信号：立即取消所有上传")
            force_stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, request_stop)
        except (NotImplementedError, RuntimeError):
            signal.signal(sig, lambda _signum, _frame: loop.call_soon_threadsafe(request_stop))
    return graceful_stop_event, force_stop_event


def _summarize_results(results: list[dict | None]) -> None:
    compact_results = [
        item or {"status": "interrupted", "detail": "not started"}
        for item in results
    ]
    added = sum(1 for item in compact_results if item.get("status") == "added")
    duplicate = sum(1 for item in compact_results if item.get("status") == "duplicate")
    skipped = sum(1 for item in compact_results if item.get("status") == "skipped")
    failed = sum(1 for item in compact_results if item.get("status") == "error")
    interrupted = sum(1 for item in compact_results if item.get("status") == "interrupted")
    logging.info(
        "完成：新增 %d  重复 %d  跳过 %d  失败 %d  未处理 %d",
        added,
        duplicate,
        skipped,
        failed,
        interrupted,
    )


async def _enqueue_paths(
    queue: asyncio.Queue[tuple[int, Path] | None],
    paths: list[Path],
    concurrency: int,
    graceful_stop_event: asyncio.Event,
) -> None:
    try:
        for item in enumerate(paths, start=1):
            if graceful_stop_event.is_set():
                logging.warning("已停止启动新任务")
                break
            await queue.put(item)
    except asyncio.CancelledError:
        return
    for _ in range(concurrency):
        await queue.put(None)


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

    try:
        import httpx
    except ImportError:
        logging.error("请安装 httpx: pip install httpx")
        sys.exit(1)

    concurrency = max(1, args.concurrency)
    max_connections = args.max_connections or max(concurrency * 2, concurrency)
    graceful_stop_event, force_stop_event = _install_stop_handlers()
    logging.info(
        "压测上传启动：files=%d concurrency=%d max_connections=%d poll_interval=%.2fs metadata_check_timeout=%.1fs",
        len(paths),
        concurrency,
        max_connections,
        args.poll_interval,
        args.metadata_check_timeout,
    )

    queue: asyncio.Queue[tuple[int, Path] | None] = asyncio.Queue(maxsize=max(concurrency, 1))
    results: list[dict | None] = [None] * len(paths)

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
                graceful_stop_event=graceful_stop_event,
            ))
            for index in range(1, concurrency + 1)
        ]
        producer_task = asyncio.create_task(_enqueue_paths(queue, paths, concurrency, graceful_stop_event))
        join_task = asyncio.create_task(queue.join())
        force_stop_task = asyncio.create_task(force_stop_event.wait())
        try:
            done, _pending = await asyncio.wait(
                {join_task, force_stop_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if force_stop_task in done:
                for worker in workers:
                    worker.cancel()
                producer_task.cancel()
                join_task.cancel()
                await asyncio.gather(*workers, return_exceptions=True)
                await asyncio.gather(producer_task, join_task, return_exceptions=True)
                logging.warning("上传已立即中止")
            else:
                force_stop_task.cancel()
                await producer_task
                await asyncio.gather(*workers)
        finally:
            for task in (producer_task, join_task, force_stop_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(producer_task, join_task, force_stop_task, return_exceptions=True)

    _summarize_results(results)
    if force_stop_event.is_set():
        raise UploadInterrupted


def main() -> None:
    parser = argparse.ArgumentParser(description="直接上传目录下所有音频文件，不做本地或服务端元数据清洗")
    parser.add_argument("directory", type=Path, help="音频目录")
    parser.add_argument("--no-recursive", action="store_true", help="只读取目录第一层")
    parser.add_argument("--concurrency", default=64, type=int, help="并发上传 worker 数（默认 64，用于压测）")
    parser.add_argument("--max-connections", default=0, type=int, help="HTTP 连接池上限；0 表示自动按并发数放大")
    parser.add_argument("--metadata-check-timeout", default=5.0, type=float, help="单文件 title/artist 标签检查超时秒数")
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
    try:
        asyncio.run(run(args))
    except (KeyboardInterrupt, UploadInterrupted):
        logging.warning("已停止")
        sys.exit(130)


if __name__ == "__main__":
    main()
