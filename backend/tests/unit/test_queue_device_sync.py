import models
import schemas
from routers.queue import _process, _sse_payload_for_device


def test_sse_payload_only_full_for_active_device():
    state = {
        "active_device": "device-a",
        "updated_at": 123,
        "is_playing": True,
        "items": [{"id": 1}],
    }

    active = _sse_payload_for_device(state, "device-a")
    inactive = _sse_payload_for_device(state, "device-b")

    assert active == {"type": "state", "data": state}
    assert inactive == {
        "type": "inactive",
        "data": {"active_device": "device-a", "updated_at": 123},
    }


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
