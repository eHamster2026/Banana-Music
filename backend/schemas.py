from pydantic import BaseModel, EmailStr, Field
from typing import Any, Optional, List


# ── Artist ──────────────────────────────────────────
class ArtistBase(BaseModel):
    name: str
    art_color: str = "art-1"
    bio: Optional[str] = None
    monthly_listeners: int = 0
    ext: dict[str, Any] = Field(default_factory=dict)

class ArtistOut(ArtistBase):
    id: int
    model_config = {"from_attributes": True}


# ── Album ────────────────────────────────────────────
class AlbumBase(BaseModel):
    title: str
    art_color: str = "art-1"
    cover_url: Optional[str] = None
    release_date: Optional[str] = None
    album_type: str = "album"
    ext: dict[str, Any] = Field(default_factory=dict)

class AlbumOut(AlbumBase):
    id: int
    artist: ArtistOut
    created_at: Optional[int] = None
    featured_artists: List[ArtistOut] = []
    model_config = {"from_attributes": True}

class AlbumDetail(AlbumOut):
    tracks: List["TrackOut"] = []
    model_config = {"from_attributes": True}


class AlbumCoverUpdate(BaseModel):
    cover_id: str = Field(..., min_length=1)


# ── Track ────────────────────────────────────────────
class TrackBase(BaseModel):
    title: str
    duration_sec: int = 180
    track_number: Optional[int] = None
    lyrics: Optional[str] = None
    cover_url: Optional[str] = None
    stream_url: Optional[str] = None
    ext: dict[str, Any] = Field(default_factory=dict)

class TrackOut(TrackBase):
    id: int
    album: Optional[AlbumOut] = None
    artist: ArtistOut
    featured_artists: List[ArtistOut] = []
    is_liked: bool = False
    model_config = {"from_attributes": True}

class TrackDetail(TrackOut):
    model_config = {"from_attributes": True}

class TrackLikeStatus(BaseModel):
    track_id: int
    liked: bool


# ── Playlist ─────────────────────────────────────────
class PlaylistCreate(BaseModel):
    name: str
    description: Optional[str] = None
    art_color: str = "art-1"

class PlaylistUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    art_color: Optional[str] = None

class PlaylistOut(BaseModel):
    id: int
    name: str
    art_color: str
    description: Optional[str] = None
    is_featured: bool
    is_system: bool
    track_count: int = 0
    model_config = {"from_attributes": True}

class PlaylistDetail(PlaylistOut):
    tracks: List[TrackOut] = []
    model_config = {"from_attributes": True}

class AddTrackToPlaylist(BaseModel):
    track_id: int


# ── User ──────────────────────────────────────────────
class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str

class UserOut(BaseModel):
    id: int
    username: str
    email: str
    avatar_color: str
    is_admin: bool = False
    created_at: int
    model_config = {"from_attributes": True}


# ── Admin ─────────────────────────────────────────────
class TrackAdminOut(BaseModel):
    id: int
    title: str
    artist: ArtistOut
    album: Optional[AlbumOut] = None
    duration_sec: int
    track_number: Optional[int] = None
    lyrics: Optional[str] = None
    cover_url: Optional[str] = None
    stream_url: Optional[str] = None
    created_at: Optional[int] = None
    ext: dict[str, Any] = Field(default_factory=dict)
    model_config = {"from_attributes": True}

class TrackMetadataPatch(BaseModel):
    """曲目元数据部分更新；仅非 None 的字段写入。album_title 空字符串表示清除专辑。"""

    title: Optional[str] = None
    artist_name: Optional[str] = None
    album_title: Optional[str] = None
    track_number: Optional[int] = None
    duration_sec: Optional[int] = None
    lyrics: Optional[str] = None


class TrackAdminUpdate(TrackMetadataPatch):
    """管理端单首更新（与 TrackMetadataPatch 同结构）。"""

    pass


class MediaImageOut(BaseModel):
    id: int
    entity_type: str
    entity_id: int
    image_type: str
    image_url: str
    mime_type: str
    created_by_user_id: Optional[int] = None
    created_at: Optional[int] = None
    ext: dict[str, Any] = Field(default_factory=dict)


class MediaImageUpdate(BaseModel):
    image_type: Optional[str] = None
    ext: Optional[dict[str, Any]] = None


class MetadataExtPatch(BaseModel):
    ext: dict[str, Any] = Field(default_factory=dict)


class MetadataExtOut(BaseModel):
    entity_type: str
    entity_id: int
    ext: dict[str, Any] = Field(default_factory=dict)

class UserAdminOut(BaseModel):
    id: int
    username: str
    email: str
    avatar_color: str
    is_admin: bool
    created_at: Optional[int] = None
    model_config = {"from_attributes": True}

class UserAdminUpdate(BaseModel):
    is_admin: Optional[bool] = None
    username: Optional[str] = None
    email: Optional[str] = None

class UserAdminCreate(BaseModel):
    username: str
    email: EmailStr
    password: str
    is_admin: bool = False


# ── Auth ──────────────────────────────────────────────
class LoginRequest(BaseModel):
    username: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ── Banner ────────────────────────────────────────────
class BannerOut(BaseModel):
    id: int
    title: str
    subtitle: Optional[str] = None
    badge: Optional[str] = None
    art_color: str
    btn_text: str
    target_type: Optional[str] = None
    target_id: Optional[int] = None
    model_config = {"from_attributes": True}


# ── Play Queue ────────────────────────────────────────
class QueueItemOut(BaseModel):
    id: int
    order_idx: int
    track: TrackOut
    model_config = {"from_attributes": True}

class QueueStateOut(BaseModel):
    cursor: int           # -1 = 空队列
    is_playing: bool
    position_sec: float
    repeat_mode: str      # none / one / all
    shuffle: bool
    active_device: Optional[str]
    updated_at: int
    items: List[QueueItemOut]
    model_config = {"from_attributes": True}

class QueueCommand(BaseModel):
    command: str          # play/pause/seek/next/prev/play_now/play_next/append/replace/remove/set_repeat/set_shuffle/activate
    device_id: str        # 发起命令的设备 ID
    track_id: Optional[int] = None
    track_ids: Optional[List[int]] = None
    start_index: Optional[int] = 0
    position_sec: Optional[float] = None
    item_id: Optional[int] = None
    repeat_mode: Optional[str] = None
    shuffle: Optional[bool] = None


# ── Home ──────────────────────────────────────────────
class HomeResponse(BaseModel):
    banners: List[BannerOut]
    recommendations: List[AlbumOut]
    featured_playlists: List[PlaylistOut]
    new_releases: List[AlbumOut]
    top_artists: List[ArtistOut]
    local_tracks: List[TrackOut] = []


# ── Search ────────────────────────────────────────────
class PluginSearchHitOut(BaseModel):
    """External search hit (Solara 等)，与 /plugins/search 单项字段一致。"""

    plugin_id: str
    source_id: str
    title: str
    artist: str
    album: str
    artists: List[str] = Field(default_factory=list)
    duration_sec: float = 0.0
    cover_url: Optional[str] = None
    preview_url: Optional[str] = None


class SearchResult(BaseModel):
    tracks: List[TrackOut]
    albums: List[AlbumOut]
    artists: List[ArtistOut]
    playlists: List[PlaylistOut]
    plugin_hits: List[PluginSearchHitOut] = Field(default_factory=list)


# ── History ───────────────────────────────────────────
class PlayEvent(BaseModel):
    track_id: int

class HistoryItem(BaseModel):
    id: int
    track: TrackOut
    played_at: int
    model_config = {"from_attributes": True}


# ── Pagination ────────────────────────────────────────
class PaginatedTracks(BaseModel):
    total: int
    items: List[TrackOut]


# ── Admin: Batch Update ───────────────────────────────
class BatchUpdateItem(TrackMetadataPatch):
    """批量更新单项：曲目 id + 与 TrackMetadataPatch 相同的可选字段。"""

    id: int

class BatchUpdateIn(BaseModel):
    updates: List[BatchUpdateItem]

class BatchUpdateFailed(BaseModel):
    id: int
    reason: str

class BatchUpdateOut(BaseModel):
    updated: int
    failed: List[BatchUpdateFailed]


# ── Admin: Library Stats ──────────────────────────────
class LibraryStats(BaseModel):
    total_tracks: int
    total_albums: int
    total_artists: int
    tracks_without_album: int
    tracks_with_unknown_artist: int
    tracks_without_stream: int


# ── Auth: API Key ─────────────────────────────────────
class ApiKeyOut(BaseModel):
    api_key: str


AlbumDetail.model_rebuild()
