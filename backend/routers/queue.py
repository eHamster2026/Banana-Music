"""
routers/queue.py
播放队列管理：持久化、POST 命令裁决、完整队列语义。

队列语义
  items[0 .. cursor-1]  = 历史 (History)
  items[cursor]         = 当前 (Current)
  items[cursor+1 ..]    = 未来 (Upcoming)

命令列表
  activate    — 将当前设备标记为活跃控制设备
  play        — 播放（is_playing=True）
  pause       — 暂停
  seek        — 拖动进度
  next        — 下一首
  prev        — 上一首（若进度 >3s 则归零，否则真正上一首）
  play_now    — 立即播放（替换队列 + 跳到 start_index）
  play_next   — 插队（当前曲目之后）
  append      — 添加到队列末尾
  remove      — 从队列移除某条目
  replace     — 全量替换队列内容
  set_repeat  — 设置循环模式 (none/one/all)
  set_shuffle — 切换随机
"""

import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, object_session

from deps import get_db, get_current_user
import models, schemas
from services.track_likes import mark_track_likes

router = APIRouter(prefix="/queue", tags=["Queue"])


# ── 工具函数 ──────────────────────────────────────────────────

def _get_or_create_queue(db: Session, user_id: int) -> models.PlayQueue:
    q = db.query(models.PlayQueue).filter(models.PlayQueue.user_id == user_id).first()
    if not q:
        q = models.PlayQueue(user_id=user_id)
        db.add(q)
        db.flush()
    return q


def _compact(items: list[models.PlayQueueItem]):
    """重新编号 order_idx，保持相对顺序。"""
    for i, item in enumerate(sorted(items, key=lambda x: x.order_idx)):
        item.order_idx = i


def _repair_cursor_after_removals(
    queue: models.PlayQueue,
    removed_order_idxs: set[int],
    remaining_count: int,
):
    old_cursor = queue.cursor
    if not removed_order_idxs:
        return

    removed_before = sum(1 for idx in removed_order_idxs if idx < old_cursor)
    current_removed = old_cursor in removed_order_idxs
    queue.cursor = old_cursor - removed_before

    if remaining_count == 0:
        queue.cursor = -1
        queue.is_playing = False
        queue.position_sec = 0.0
        return

    if queue.cursor >= remaining_count:
        queue.cursor = remaining_count - 1
        queue.is_playing = False
        queue.position_sec = 0.0
    elif current_removed:
        queue.is_playing = False
        queue.position_sec = 0.0


def _drop_items_from_queue(
    queue: models.PlayQueue,
    removed_items: list[models.PlayQueueItem],
    db: Session | None = None,
) -> list[models.PlayQueueItem]:
    if not removed_items:
        return sorted(queue.items, key=lambda x: x.order_idx)

    removed_ids = {item.id for item in removed_items}
    removed_order_idxs = {item.order_idx for item in removed_items}
    remaining = [
        item
        for item in sorted(queue.items, key=lambda x: x.order_idx)
        if item.id not in removed_ids
    ]

    _compact(remaining)
    _repair_cursor_after_removals(queue, removed_order_idxs, len(remaining))

    session = db or object_session(queue)
    if session is not None:
        for item in removed_items:
            session.delete(item)

    return remaining


def remove_track_from_queues(db: Session, track_id: int):
    """删除曲目时同步移除所有播放队列中的引用。"""
    items = (
        db.query(models.PlayQueueItem)
        .filter(models.PlayQueueItem.track_id == track_id)
        .all()
    )
    by_queue: dict[int, tuple[models.PlayQueue, list[models.PlayQueueItem]]] = {}
    for item in items:
        queue_items = by_queue.setdefault(item.queue_id, (item.queue, []))[1]
        queue_items.append(item)

    for queue, removed_items in by_queue.values():
        _drop_items_from_queue(queue, removed_items, db)


def _live_items(queue: models.PlayQueue) -> list[models.PlayQueueItem]:
    items = sorted(queue.items, key=lambda x: x.order_idx)
    stale = [item for item in items if item.track is None]
    if not stale:
        return items

    session = object_session(queue)
    live = _drop_items_from_queue(queue, stale, session)
    if session is not None:
        session.commit()
    return live


def _serialize(queue: models.PlayQueue) -> dict:
    items = _live_items(queue)
    session = object_session(queue)
    if session is not None:
        mark_track_likes(session, [item.track for item in items if item.track is not None], queue.user)
    return {
        "cursor":        queue.cursor,
        "is_playing":    queue.is_playing,
        "position_sec":  queue.position_sec,
        "repeat_mode":   queue.repeat_mode,
        "shuffle":       queue.shuffle,
        "active_device": queue.active_device,
        "updated_at":    queue.updated_at,
        "items": [
            {
                "id":        it.id,
                "order_idx": it.order_idx,
                "track": {
                    "id":           it.track.id,
                    "title":        it.track.title,
                    "duration_sec": it.track.duration_sec,
                    "track_number": it.track.track_number,
                    "stream_url":   it.track.stream_url,
                    "cover_url":    it.track.cover_url,
                    "is_liked":     bool(getattr(it.track, "is_liked", False)),
                    "artist": {
                        "id":   it.track.artist.id,
                        "name": it.track.artist.name,
                        "art_color": it.track.artist.art_color,
                    } if it.track.artist else None,
                    "album": {
                        "id":        it.track.album.id,
                        "title":     it.track.album.title,
                        "art_color": it.track.album.art_color,
                        "artist": {
                            "id":        it.track.album.artist.id,
                            "name":      it.track.album.artist.name,
                            "art_color": it.track.album.artist.art_color,
                        } if it.track.album.artist else {
                            "id": 0, "name": "未知艺术家", "art_color": "art-1"
                        },
                    } if it.track.album else None,
                }
            }
            for it in items
        ],
    }


# ── 命令处理 ──────────────────────────────────────────────────

def _process(queue: models.PlayQueue, cmd: schemas.QueueCommand, db: Session):
    now = int(time.time())
    c = cmd.command

    if c == "activate":
        queue.active_device = cmd.device_id

    elif c == "play":
        queue.is_playing = True
        queue.active_device = cmd.device_id

    elif c == "pause":
        if queue.active_device != cmd.device_id:
            return
        queue.is_playing = False
        if cmd.position_sec is not None:
            queue.position_sec = cmd.position_sec

    elif c == "seek":
        queue.active_device = cmd.device_id
        if cmd.position_sec is not None:
            queue.position_sec = cmd.position_sec

    elif c == "next":
        queue.active_device = cmd.device_id
        items = sorted(queue.items, key=lambda x: x.order_idx)
        next_cursor = queue.cursor + 1
        if next_cursor < len(items):
            queue.cursor = next_cursor
            queue.position_sec = 0.0
        elif queue.repeat_mode == "all" and items:
            queue.cursor = 0
            queue.position_sec = 0.0
        else:
            queue.is_playing = False

    elif c == "prev":
        queue.active_device = cmd.device_id
        if queue.position_sec and queue.position_sec > 3:
            queue.position_sec = 0.0
        elif queue.cursor > 0:
            queue.cursor -= 1
            queue.position_sec = 0.0

    elif c in ("play_now", "replace"):
        track_ids = cmd.track_ids or ([] if cmd.track_id is None else [cmd.track_id])
        if not track_ids:
            raise HTTPException(400, "需要提供 track_ids 或 track_id")
        # 验证曲目存在
        tracks = db.query(models.Track).filter(models.Track.id.in_(track_ids)).all()
        track_map = {t.id: t for t in tracks}
        # 清空旧条目
        for item in queue.items:
            db.delete(item)
        db.flush()
        # 写入新条目
        for i, tid in enumerate(track_ids):
            if tid in track_map:
                db.add(models.PlayQueueItem(
                    queue_id=queue.id, track_id=tid, order_idx=i))
        db.flush()
        # 刷新关系
        db.refresh(queue)
        start = cmd.start_index or 0
        queue.cursor = min(start, len(track_ids) - 1)
        queue.position_sec = 0.0
        queue.is_playing = True
        queue.active_device = cmd.device_id

    elif c == "play_next":
        if cmd.track_id is None:
            raise HTTPException(400, "需要 track_id")
        track = db.query(models.Track).filter(models.Track.id == cmd.track_id).first()
        if not track:
            raise HTTPException(404, "曲目不存在")
        insert_at = queue.cursor + 1
        # 后移已有条目
        for item in queue.items:
            if item.order_idx >= insert_at:
                item.order_idx += 1
        db.add(models.PlayQueueItem(
            queue_id=queue.id, track_id=cmd.track_id, order_idx=insert_at))
        db.flush()
        db.refresh(queue)

    elif c == "append":
        if cmd.track_id is None:
            raise HTTPException(400, "需要 track_id")
        track = db.query(models.Track).filter(models.Track.id == cmd.track_id).first()
        if not track:
            raise HTTPException(404, "曲目不存在")
        max_idx = max((it.order_idx for it in queue.items), default=-1)
        db.add(models.PlayQueueItem(
            queue_id=queue.id, track_id=cmd.track_id, order_idx=max_idx + 1))
        db.flush()
        db.refresh(queue)

    elif c == "remove":
        if cmd.item_id is None:
            raise HTTPException(400, "需要 item_id")
        item = db.query(models.PlayQueueItem).filter(
            models.PlayQueueItem.id == cmd.item_id,
            models.PlayQueueItem.queue_id == queue.id,
        ).first()
        if not item:
            raise HTTPException(404, "条目不存在")
        removed_idx = item.order_idx
        db.delete(item)
        db.flush()
        db.refresh(queue)
        _compact(queue.items)
        # 调整 cursor
        if removed_idx < queue.cursor:
            queue.cursor -= 1
        elif removed_idx == queue.cursor:
            # 当前曲目被删，暂停
            queue.is_playing = False
            if queue.cursor >= len(queue.items):
                queue.cursor = len(queue.items) - 1

    elif c == "set_repeat":
        if cmd.repeat_mode not in ("none", "one", "all"):
            raise HTTPException(400, "repeat_mode 须为 none/one/all")
        queue.active_device = cmd.device_id
        queue.repeat_mode = cmd.repeat_mode

    elif c == "set_shuffle":
        if cmd.shuffle is None:
            raise HTTPException(400, "需要 shuffle")
        queue.active_device = cmd.device_id
        queue.shuffle = cmd.shuffle

    elif c == "sync_position":
        # 仅同步进度，不触发其他变化（定时心跳用）
        if queue.active_device == cmd.device_id and cmd.position_sec is not None:
            queue.position_sec = cmd.position_sec
        # 不更新 updated_at，避免触发其他设备 seek
        db.commit()
        return

    else:
        raise HTTPException(400, f"未知命令: {c}")

    queue.updated_at = now
    db.commit()


@router.post("/command", response_model=schemas.QueueStateOut)
def queue_command(
    cmd: schemas.QueueCommand,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    queue = _get_or_create_queue(db, user.id)
    _process(queue, cmd, db)
    return _serialize(queue)
