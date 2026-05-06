from sqlalchemy import (
    Column,
    Integer,
    String,
    ForeignKey,
    Boolean,
    Text,
    LargeBinary,
    Float,
    Index,
    func,
    text,
)
from sqlalchemy.orm import relationship
import time
from database import Base


class SchemaMigration(Base):
    """版本历史表，替代 data/schema_version 文件，避免文件与库不一致。"""
    __tablename__ = "schema_migrations"
    version    = Column(Integer, primary_key=True)
    applied_at = Column(Integer, nullable=False)
    description = Column(Text, nullable=True)


def utcnow() -> int:
    return int(time.time())


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(100), unique=True, nullable=False, index=True)
    hashed_password = Column(String(200), nullable=False)
    avatar_color = Column(String(20), default="art-1")
    is_admin = Column(Boolean, default=False)
    created_at = Column(Integer, default=utcnow)
    api_key = Column(String(100), unique=True, nullable=True, index=True)

    playlists = relationship("Playlist", back_populates="user", cascade="all, delete-orphan")
    liked_tracks = relationship("UserTrackLike", back_populates="user", cascade="all, delete-orphan")
    library_albums = relationship("UserLibraryAlbum", back_populates="user", cascade="all, delete-orphan")
    library_artists = relationship("UserLibraryArtist", back_populates="user", cascade="all, delete-orphan")
    play_history = relationship("PlayHistory", back_populates="user", cascade="all, delete-orphan")
    play_queue = relationship("PlayQueue", back_populates="user", uselist=False, cascade="all, delete-orphan")


class Artist(Base):
    __tablename__ = "artists"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    art_color = Column(String(20), default="art-1")
    bio = Column(Text, nullable=True)
    monthly_listeners = Column(Integer, default=0)

    albums = relationship("Album", back_populates="artist")
    tracks = relationship("Track", back_populates="artist")


class Album(Base):
    __tablename__ = "albums"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    artist_id = Column(Integer, ForeignKey("artists.id"), nullable=False)
    art_color = Column(String(20), default="art-1")
    cover_path = Column(String(255), nullable=True)
    release_date = Column(String(10))
    album_type = Column(String(20), default="album")
    created_at = Column(Integer, default=utcnow)

    artist = relationship("Artist", back_populates="albums")
    tracks = relationship(
        "Track",
        back_populates="album",
        order_by=lambda: (Track.track_number.asc().nulls_last(), Track.id.asc()),
    )
    album_artists = relationship(
        "AlbumArtist", back_populates="album",
        order_by="AlbumArtist.sort_order",
        cascade="all, delete-orphan",
    )

    @property
    def cover_url(self) -> str | None:
        if not self.cover_path:
            return None
        return f"/covers/{self.cover_path}"

    @property
    def featured_artists(self) -> list:
        """参与创作的 featured 艺人列表（不含 artist_id 所指的主艺人）。"""
        return [aa.artist for aa in self.album_artists]


class Track(Base):
    __tablename__ = "tracks"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    album_id = Column(Integer, ForeignKey("albums.id"), nullable=True)
    artist_id = Column(Integer, ForeignKey("artists.id"), nullable=False)
    duration_sec = Column(Integer, default=180)
    track_number = Column(Integer, nullable=True, default=None)  # NULL = 曲目编号不明
    lyrics = Column(Text, nullable=True)
    cover_path = Column(String(255), nullable=True)
    stream_url = Column(String(500), nullable=True)
    created_at = Column(Integer, default=utcnow)
    # MD5 of decoded PCM — format-invariant, used for dedup
    audio_hash = Column(LargeBinary(16), unique=True, nullable=False, index=True)
    # Chromaprint fingerprint bytes — computed by background worker
    audio_fingerprint = Column(LargeBinary, nullable=True)

    album = relationship("Album", back_populates="tracks")
    artist = relationship("Artist", back_populates="tracks")
    liked_by = relationship("UserTrackLike", back_populates="track")
    track_artists = relationship(
        "TrackArtist", back_populates="track",
        order_by="TrackArtist.sort_order",
        cascade="all, delete-orphan",
    )

    @property
    def cover_url(self) -> str | None:
        if self.cover_path:
            return f"/covers/{self.cover_path}"
        if self.album and self.album.cover_path:
            return f"/covers/{self.album.cover_path}"
        return None

    @property
    def featured_artists(self) -> list:
        """参与创作的 featured 艺人列表（不含 artist_id 所指的主艺人）。"""
        return [ta.artist for ta in self.track_artists]


class TrackArtist(Base):
    """曲目-艺人多对多关联（feat. 等参与艺人）。主艺人仍由 tracks.artist_id 指向。"""
    __tablename__ = "track_artists"
    track_id  = Column(Integer, ForeignKey("tracks.id",  ondelete="CASCADE"), primary_key=True)
    artist_id = Column(Integer, ForeignKey("artists.id"), primary_key=True)
    role       = Column(String(20), default="featured")   # featured / remixer / …
    sort_order = Column(Integer,    default=0)

    track  = relationship("Track",  back_populates="track_artists")
    artist = relationship("Artist")


class AlbumArtist(Base):
    """专辑-艺人多对多关联（feat. / 合辑参与者等）。主艺人仍由 albums.artist_id 指向。"""
    __tablename__ = "album_artists"
    album_id  = Column(Integer, ForeignKey("albums.id",  ondelete="CASCADE"), primary_key=True)
    artist_id = Column(Integer, ForeignKey("artists.id"), primary_key=True)
    role       = Column(String(20), default="featured")
    sort_order = Column(Integer,    default=0)

    album  = relationship("Album",  back_populates="album_artists")
    artist = relationship("Artist")


class Playlist(Base):
    __tablename__ = "playlists"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    art_color = Column(String(20), default="art-1")
    description = Column(Text, nullable=True)
    is_featured = Column(Boolean, default=False)
    is_system = Column(Boolean, default=False)
    created_at = Column(Integer, default=utcnow)

    # 同一用户下歌单名不区分大小写唯一；系统/精选歌单 user_id 为 NULL，不受此索引约束（SQLite 中 NULL 互不冲突）
    __table_args__ = (
        Index(
            "uq_playlists_user_id_lower_name",
            "user_id",
            func.lower(name),
            unique=True,
            sqlite_where=text("user_id IS NOT NULL"),
            postgresql_where=text("user_id IS NOT NULL"),
        ),
    )

    user = relationship("User", back_populates="playlists")
    playlist_tracks = relationship(
        "PlaylistTrack", back_populates="playlist",
        order_by="PlaylistTrack.position", cascade="all, delete-orphan"
    )


class PlaylistTrack(Base):
    __tablename__ = "playlist_tracks"
    id = Column(Integer, primary_key=True, index=True)
    playlist_id = Column(Integer, ForeignKey("playlists.id"), nullable=False)
    track_id = Column(Integer, ForeignKey("tracks.id"), nullable=False)
    position = Column(Integer, default=0)

    playlist = relationship("Playlist", back_populates="playlist_tracks")
    track = relationship("Track")


class UserTrackLike(Base):
    __tablename__ = "user_track_likes"
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    track_id = Column(Integer, ForeignKey("tracks.id"), primary_key=True)
    liked_at = Column(Integer, default=utcnow)

    user = relationship("User", back_populates="liked_tracks")
    track = relationship("Track", back_populates="liked_by")


class UserLibraryAlbum(Base):
    __tablename__ = "user_library_albums"
    user_id  = Column(Integer, ForeignKey("users.id"),   primary_key=True)
    album_id = Column(Integer, ForeignKey("albums.id"),  primary_key=True)

    user  = relationship("User",  back_populates="library_albums")
    album = relationship("Album")


class UserLibraryArtist(Base):
    __tablename__ = "user_library_artists"
    user_id   = Column(Integer, ForeignKey("users.id"),   primary_key=True)
    artist_id = Column(Integer, ForeignKey("artists.id"), primary_key=True)

    user   = relationship("User",   back_populates="library_artists")
    artist = relationship("Artist")


class PlayHistory(Base):
    __tablename__ = "play_history"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    track_id = Column(Integer, ForeignKey("tracks.id"), nullable=False)
    played_at = Column(Integer, default=utcnow)

    user = relationship("User", back_populates="play_history")
    track = relationship("Track")


class PlayQueue(Base):
    """每个用户一条队列记录，cursor 指向当前曲目的 order_idx。"""
    __tablename__ = "play_queues"
    id            = Column(Integer, primary_key=True)
    user_id       = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    cursor        = Column(Integer, default=-1)       # -1 = 无当前曲目
    is_playing    = Column(Boolean, default=False)
    position_sec  = Column(Float,   default=0.0)
    repeat_mode   = Column(String(10), default="none")  # none / one / all
    shuffle       = Column(Boolean, default=False)
    active_device = Column(String(128), nullable=True)  # 当前控制设备 ID
    updated_at    = Column(Integer, default=utcnow)

    user  = relationship("User", back_populates="play_queue")
    items = relationship("PlayQueueItem", back_populates="queue",
                         order_by="PlayQueueItem.order_idx",
                         cascade="all, delete-orphan")


class PlayQueueItem(Base):
    __tablename__ = "play_queue_items"
    id        = Column(Integer, primary_key=True)
    queue_id  = Column(Integer, ForeignKey("play_queues.id"), nullable=False)
    track_id  = Column(Integer, ForeignKey("tracks.id"),    nullable=False)
    order_idx = Column(Integer, nullable=False)

    queue = relationship("PlayQueue", back_populates="items")
    track = relationship("Track")


class FingerprintTask(Base):
    """Chromaprint 指纹计算队列：仅在上传入库时写入，由 fingerprint_worker 消费。"""
    __tablename__ = "fingerprint_tasks"

    id = Column(Integer, primary_key=True, index=True)
    track_id = Column(Integer, ForeignKey("tracks.id", ondelete="CASCADE"), unique=True, nullable=False)
    created_at = Column(Integer, default=utcnow)

    track = relationship("Track")


class UploadStaging(Base):
    """
    上传暂存表：在 upload-file 和 create 之间持久化中间计算结果。

    upload-file 写入，create 读取后删除。
    audio_hash 用于格式无关去重（PCM MD5），original_name 用于提取文件名茎。
    created_at 超过 TTL（默认 1 小时）的孤立记录由后台任务清理。
    """
    __tablename__ = "upload_staging"

    file_key      = Column(String,       primary_key=True)  # hash_hex + extension
    audio_hash    = Column(LargeBinary(16), nullable=False)  # PCM MD5，16 字节
    original_name = Column(String,       nullable=False)     # 原始文件名（含扩展名）
    duration_sec  = Column(Integer,      default=0)
    created_at    = Column(Integer,      default=utcnow)


class Banner(Base):
    __tablename__ = "banners"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    subtitle = Column(String(300), nullable=True)
    badge = Column(String(100), nullable=True)
    art_color = Column(String(20), default="art-1")
    btn_text = Column(String(50), default="立即播放")
    target_type = Column(String(20), nullable=True)
    target_id = Column(Integer, nullable=True)
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
