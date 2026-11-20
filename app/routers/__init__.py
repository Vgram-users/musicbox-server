from fastapi.routing import APIRouter

from . import auth, playlists, system, tracks

__all__ = ["auth", "playlists", "system", "tracks", "APIRouter"]
