"""Health check endpoint."""

from fastapi import APIRouter

from issue_bot import deps

router = APIRouter()


@router.get("/health")
async def health():
    return {
        "status": "ok",
        "llm_provider": deps.CFG["llm_provider"],
        "projects": list(deps.CFG["projects"].keys()),
    }
