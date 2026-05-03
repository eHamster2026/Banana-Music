import models
import schemas
from routers.queue import _process


def test_inactive_device_pause_does_not_pause_active_queue():
    queue = models.PlayQueue(
        user_id=1,
        is_playing=True,
        active_device="device-a",
        position_sec=10.0,
        updated_at=100,
    )
    cmd = schemas.QueueCommand(
        command="pause",
        device_id="device-b",
        position_sec=20.0,
    )

    _process(queue, cmd, db=None)

    assert queue.is_playing is True
    assert queue.active_device == "device-a"
    assert queue.position_sec == 10.0
    assert queue.updated_at == 100
