import pytest

from auth_utils import create_access_token
import models
from database import SessionLocal
from routers import rest, upload


def _token_for_user(username: str, *, is_admin: bool = False) -> str:
    db = SessionLocal()
    try:
        user = models.User(
            username=username,
            email=f"{username}@example.com",
            hashed_password="x",
            is_admin=is_admin,
        )
        db.add(user)
        db.commit()
        return create_access_token({"sub": str(user.id)})
    finally:
        db.close()


def _create_track() -> int:
    db = SessionLocal()
    try:
        artist = models.Artist(name="Media Artist", art_color="art-1")
        db.add(artist)
        db.flush()
        album = models.Album(title="Media Album", artist_id=artist.id, art_color="art-1")
        db.add(album)
        db.flush()
        track = models.Track(
            title="Media Track",
            artist_id=artist.id,
            album_id=album.id,
            duration_sec=1,
            track_number=2,
            stream_url="/resource/media.flac",
            is_local=True,
            audio_hash=b"media-track".ljust(16, b"-"),
            lyrics="stored lyrics",
            ext={"catalog": "BWV 2"},
        )
        db.add(track)
        db.commit()
        return track.id
    finally:
        db.close()


@pytest.mark.asyncio
async def test_media_images_create_read_admin_update_delete(client, monkeypatch, tmp_path):
    monkeypatch.setattr(upload, "COVER_DIR", tmp_path / "covers")
    token = _token_for_user("image-user")
    admin_token = _token_for_user("image-admin", is_admin=True)
    track_id = _create_track()

    png = b"\x89PNG\r\n\x1a\n" + b"\0" * 16
    created = await client.post(
        "/rest/x-banana/media-images",
        data={"entity_type": "track", "entity_id": str(track_id), "image_type": "back"},
        files={"file": ("back.png", png, "image/png")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert created.status_code == 200
    image_id = created.json()["id"]
    assert created.json()["image_type"] == "back"

    listed = await client.get(
        "/rest/x-banana/media-images",
        params={"entity_type": "track", "entity_id": track_id},
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [image_id]

    denied = await client.patch(
        f"/rest/x-banana/media-images/{image_id}",
        json={"image_type": "fanart"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert denied.status_code == 403

    updated = await client.patch(
        f"/rest/x-banana/media-images/{image_id}",
        json={"image_type": "fanart", "ext": {"source": "scan"}},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert updated.status_code == 200
    assert updated.json()["image_type"] == "fanart"
    assert updated.json()["ext"] == {"source": "scan"}

    deleted = await client.delete(
        f"/rest/x-banana/media-images/{image_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True


@pytest.mark.asyncio
async def test_metadata_ext_security_model(client):
    token = _token_for_user("ext-user")
    admin_token = _token_for_user("ext-admin", is_admin=True)
    track_id = _create_track()

    added = await client.post(
        f"/rest/x-banana/metadata-ext/track/{track_id}",
        json={"ext": {"source_label": "import"}},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert added.status_code == 200
    assert added.json()["ext"]["source_label"] == "import"

    duplicate = await client.post(
        f"/rest/x-banana/metadata-ext/track/{track_id}",
        json={"ext": {"source_label": "changed"}},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert duplicate.status_code == 409

    denied = await client.patch(
        f"/rest/x-banana/metadata-ext/track/{track_id}",
        json={"ext": {"source_label": "admin"}},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert denied.status_code == 403

    patched = await client.patch(
        f"/rest/x-banana/metadata-ext/track/{track_id}",
        json={"ext": {"source_label": "admin"}},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert patched.status_code == 200
    assert patched.json()["ext"]["source_label"] == "admin"

    deleted = await client.delete(
        f"/rest/x-banana/metadata-ext/track/{track_id}",
        params={"key": "source_label"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert deleted.status_code == 200
    assert "source_label" not in deleted.json()["ext"]


@pytest.mark.asyncio
async def test_download_writes_database_tags_and_hidden_images(client, monkeypatch, tmp_path):
    import soundfile as sf
    from mutagen.flac import FLAC

    audio_path = tmp_path / "source.flac"
    sf.write(audio_path, [0.0] * 8000, 8000, format="FLAC")
    covers = tmp_path / "covers"
    covers.mkdir()
    (covers / "cover.jpg").write_bytes(b"\xff\xd8\xffcover")
    (covers / "back.jpg").write_bytes(b"\xff\xd8\xffback")

    db = SessionLocal()
    try:
        artist = models.Artist(name="Download Artist", art_color="art-1")
        db.add(artist)
        db.flush()
        album = models.Album(
            title="Download Album",
            artist_id=artist.id,
            art_color="art-1",
            cover_path="cover.jpg",
            release_date="2026-01-02",
        )
        db.add(album)
        db.flush()
        track = models.Track(
            title="Download Track",
            artist_id=artist.id,
            album_id=album.id,
            duration_sec=1,
            track_number=3,
            lyrics="download lyrics",
            stream_url="/resource/source.flac",
            is_local=True,
            audio_hash=b"download-track".ljust(16, b"-"),
        )
        db.add(track)
        db.flush()
        db.add(models.MediaImage(
            entity_type="album",
            entity_id=album.id,
            image_type="back",
            path="back.jpg",
            mime_type="image/jpeg",
            ext={},
        ))
        db.commit()
        track_id = track.id
    finally:
        db.close()

    monkeypatch.setattr(rest, "_local_file_from_stream_url", lambda _stream_url: audio_path)
    monkeypatch.setattr(rest, "_cover_file_from_path", lambda cover_path: covers / cover_path)

    response = await client.get("/rest/download", params={"id": track_id})
    assert response.status_code == 200
    downloaded = tmp_path / "downloaded.flac"
    downloaded.write_bytes(response.content)

    tags = FLAC(str(downloaded))
    assert tags["title"] == ["Download Track"]
    assert tags["artist"] == ["Download Artist"]
    assert tags["album"] == ["Download Album"]
    assert tags["tracknumber"] == ["3"]
    assert tags["lyrics"] == ["download lyrics"]
    assert sorted(pic.type for pic in tags.pictures) == [3, 4]
