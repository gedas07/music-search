from pydantic import BaseModel


class TrackResponse(BaseModel):
    artist: str
    title: str
    album: str | None = None
    quality: str
    size: str


class SourceResponse(BaseModel):
    username: str
    queue: int
    speed: str


class QueueResponse(BaseModel):
    status: str
    position: int
    track: TrackResponse
    source: SourceResponse


class DuplicateDeleteRequest(BaseModel):
    paths: list[str]


class PruneRequest(BaseModel):
    name: str
    delete_if_empty: bool = False


class PlaylistDeleteRequest(BaseModel):
    name: str