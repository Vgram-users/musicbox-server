from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- auth ----------

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(default="", max_length=64)
    invite_code: str = Field(default="", max_length=32)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(ORMModel):
    id: str
    email: EmailStr
    display_name: str
    created_at: datetime


# ---------- tracks ----------

class TrackOut(ORMModel):
    id: str
    title: str
    artist: str
    album: str
    duration_sec: int | None
    size_bytes: int
    mime_type: str
    play_count: int
    created_at: datetime
    has_cover: bool = False
    stream_url: str = ""


class TrackList(BaseModel):
    items: list[TrackOut]
    total: int
    limit: int
    offset: int


class SearchHit(BaseModel):
    id: str
    title: str
    artist: str
    duration: int | None
    url: str
    thumbnail: str | None
    source: str


class SearchResult(BaseModel):
    items: list[SearchHit]


class AddByUrl(BaseModel):
    url: str


class TrackUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    artist: str | None = Field(default=None, max_length=255)
    album: str | None = Field(default=None, max_length=255)


# ---------- playlists ----------

class PlaylistCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    is_public: bool = True


class PlaylistOut(ORMModel):
    id: str
    name: str
    description: str
    is_public: bool
    share_slug: str
    owner_id: str
    created_at: datetime
    track_count: int = 0


class PlaylistDetail(PlaylistOut):
    tracks: list[TrackOut] = []


class PlaylistAddTrack(BaseModel):
    track_id: str
