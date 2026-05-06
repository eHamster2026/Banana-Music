import pytest

from auth_utils import create_access_token
import models
from database import SessionLocal


@pytest.mark.asyncio
async def test_list_tracks_default_includes_more_than_legacy_page_size(client):
    db = SessionLocal()
    try:
        artist = models.Artist(name="Track Owner", art_color="art-1")
        db.add(artist)
        db.flush()
        for i in range(25):
            db.add(models.Track(
                title=f"Track {i}",
                artist_id=artist.id,
                duration_sec=180,
                stream_url=f"/resource/track-{i}.flac",
                is_local=True,
                audio_hash=f"track-{i}".encode("ascii").ljust(16, b"-"),
            ))
        db.commit()
    finally:
        db.close()

    r = await client.get("/rest/getSongs")
    assert r.status_code == 200
    assert len(r.json()) == 25


@pytest.mark.asyncio
async def test_get_songs_marks_liked_tracks_for_current_user(client):
    db = SessionLocal()
    try:
        user = models.User(
            username="listener",
            email="listener@example.com",
            hashed_password="x",
        )
        artist = models.Artist(name="Track Owner", art_color="art-1")
        db.add_all([user, artist])
        db.flush()
        liked_track = models.Track(
            title="Liked Track",
            artist_id=artist.id,
            duration_sec=180,
            stream_url="/resource/liked.flac",
            is_local=True,
            audio_hash=b"liked-track".ljust(16, b"-"),
        )
        other_track = models.Track(
            title="Other Track",
            artist_id=artist.id,
            duration_sec=180,
            stream_url="/resource/other.flac",
            is_local=True,
            audio_hash=b"other-track".ljust(16, b"-"),
        )
        db.add_all([liked_track, other_track])
        db.flush()
        db.add(models.UserTrackLike(user_id=user.id, track_id=liked_track.id))
        db.commit()
        token = create_access_token({"sub": str(user.id)})
    finally:
        db.close()

    r = await client.get(
        "/rest/getSongs?local=true",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    by_title = {track["title"]: track for track in r.json()}
    assert by_title["Liked Track"]["is_liked"] is True
    assert by_title["Other Track"]["is_liked"] is False

    anon = await client.get("/rest/getSongs?local=true")
    assert anon.status_code == 200
    assert all(track["is_liked"] is False for track in anon.json())


@pytest.mark.asyncio
async def test_search_marks_liked_tracks_for_current_user(client):
    db = SessionLocal()
    try:
        user = models.User(
            username="search-listener",
            email="search-listener@example.com",
            hashed_password="x",
        )
        artist = models.Artist(name="Search Artist", art_color="art-1")
        db.add_all([user, artist])
        db.flush()
        liked_track = models.Track(
            title="Needle Liked",
            artist_id=artist.id,
            duration_sec=180,
            stream_url="/resource/search-liked.flac",
            audio_hash=b"search-liked".ljust(16, b"-"),
        )
        other_track = models.Track(
            title="Needle Other",
            artist_id=artist.id,
            duration_sec=180,
            stream_url="/resource/search-other.flac",
            audio_hash=b"search-other".ljust(16, b"-"),
        )
        db.add_all([liked_track, other_track])
        db.flush()
        db.add(models.UserTrackLike(user_id=user.id, track_id=liked_track.id))
        db.commit()
        token = create_access_token({"sub": str(user.id)})
    finally:
        db.close()

    r = await client.get(
        "/rest/search3?query=Needle",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    by_title = {track["title"]: track for track in r.json()["tracks"]}
    assert by_title["Needle Liked"]["is_liked"] is True
    assert by_title["Needle Other"]["is_liked"] is False

    anon = await client.get("/rest/search3?query=Needle")
    assert anon.status_code == 200
    assert all(track["is_liked"] is False for track in anon.json()["tracks"])


@pytest.mark.asyncio
async def test_track_overview_endpoints_mark_liked_tracks(client):
    db = SessionLocal()
    try:
        user = models.User(
            username="overview-listener",
            email="overview-listener@example.com",
            hashed_password="x",
        )
        artist = models.Artist(name="Overview Artist", art_color="art-1")
        db.add_all([user, artist])
        db.flush()
        album = models.Album(title="Overview Album", artist_id=artist.id)
        db.add(album)
        db.flush()
        liked_track = models.Track(
            title="Overview Liked",
            artist_id=artist.id,
            album_id=album.id,
            duration_sec=180,
            stream_url="/resource/overview-liked.flac",
            audio_hash=b"overview-liked".ljust(16, b"-"),
        )
        other_track = models.Track(
            title="Overview Other",
            artist_id=artist.id,
            album_id=album.id,
            duration_sec=180,
            stream_url="/resource/overview-other.flac",
            audio_hash=b"overview-other".ljust(16, b"-"),
        )
        playlist = models.Playlist(name="Overview Playlist", user_id=user.id)
        db.add_all([liked_track, other_track, playlist])
        db.flush()
        db.add_all([
            models.UserTrackLike(user_id=user.id, track_id=liked_track.id),
            models.PlaylistTrack(playlist_id=playlist.id, track_id=liked_track.id, position=0),
            models.PlaylistTrack(playlist_id=playlist.id, track_id=other_track.id, position=1),
        ])
        db.commit()
        token = create_access_token({"sub": str(user.id)})
        liked_id = liked_track.id
        album_id = album.id
        artist_id = artist.id
        playlist_id = playlist.id
    finally:
        db.close()

    headers = {"Authorization": f"Bearer {token}"}

    song = await client.get(f"/rest/getSong?id={liked_id}", headers=headers)
    assert song.status_code == 200
    assert song.json()["is_liked"] is True

    album_res = await client.get(f"/rest/getAlbum?id={album_id}", headers=headers)
    assert album_res.status_code == 200
    album_tracks = {track["title"]: track for track in album_res.json()["tracks"]}
    assert album_tracks["Overview Liked"]["is_liked"] is True
    assert album_tracks["Overview Other"]["is_liked"] is False

    artist_res = await client.get(f"/rest/getArtistSongs?id={artist_id}", headers=headers)
    assert artist_res.status_code == 200
    artist_tracks = {track["title"]: track for track in artist_res.json()}
    assert artist_tracks["Overview Liked"]["is_liked"] is True
    assert artist_tracks["Overview Other"]["is_liked"] is False

    playlist_res = await client.get(f"/rest/getPlaylist?id={playlist_id}", headers=headers)
    assert playlist_res.status_code == 200
    playlist_tracks = {track["title"]: track for track in playlist_res.json()["tracks"]}
    assert playlist_tracks["Overview Liked"]["is_liked"] is True
    assert playlist_tracks["Overview Other"]["is_liked"] is False
