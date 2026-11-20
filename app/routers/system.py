from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})
