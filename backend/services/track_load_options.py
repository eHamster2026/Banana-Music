from sqlalchemy.orm import load_only, selectinload

import models


def track_out_load_options():
    """Eager-load the relationship graph touched by TrackOut serialization."""
    artist_columns = (
        models.Artist.id,
        models.Artist.name,
        models.Artist.art_color,
        models.Artist.bio,
        models.Artist.monthly_listeners,
    )
    album_columns = (
        models.Album.id,
        models.Album.title,
        models.Album.artist_id,
        models.Album.art_color,
        models.Album.cover_path,
        models.Album.release_date,
        models.Album.album_type,
        models.Album.created_at,
    )

    return (
        load_only(
            models.Track.id,
            models.Track.title,
            models.Track.album_id,
            models.Track.artist_id,
            models.Track.duration_sec,
            models.Track.track_number,
            models.Track.lyrics,
            models.Track.cover_path,
            models.Track.stream_url,
            models.Track.created_at,
        ),
        selectinload(models.Track.artist).load_only(*artist_columns),
        selectinload(models.Track.track_artists).load_only(
            models.TrackArtist.track_id,
            models.TrackArtist.artist_id,
            models.TrackArtist.role,
            models.TrackArtist.sort_order,
        ),
        selectinload(models.Track.track_artists)
        .selectinload(models.TrackArtist.artist)
        .load_only(*artist_columns),
        selectinload(models.Track.album).load_only(*album_columns),
        selectinload(models.Track.album)
        .selectinload(models.Album.artist)
        .load_only(*artist_columns),
        selectinload(models.Track.album)
        .selectinload(models.Album.album_artists)
        .load_only(
            models.AlbumArtist.album_id,
            models.AlbumArtist.artist_id,
            models.AlbumArtist.role,
            models.AlbumArtist.sort_order,
        ),
        selectinload(models.Track.album)
        .selectinload(models.Album.album_artists)
        .selectinload(models.AlbumArtist.artist)
        .load_only(*artist_columns),
    )
