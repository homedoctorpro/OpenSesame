from fastapi import APIRouter

from app.config import settings

router = APIRouter()


@router.get("/api/health")
async def health():
    return {
        "status": "ok",
        "openai_configured": bool(settings.openai_api_key),
    }
