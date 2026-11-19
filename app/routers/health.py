from fastapi import APIRouter

from app.core.config import settings

router = APIRouter()


@router.get("/healthz")
def healthz():
    return {"status": "ok", "app": settings.app_name, "model": "mock" if settings.mock_mode else "real"}
