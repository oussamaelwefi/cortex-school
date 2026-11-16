from core.config import settings
from core.router import APIRouter

router = APIRouter(prefix="/example", tags=["Example"])


@router.get("/")
async def example():
    return {"message": "It works", "service": settings.PROJECT_NAME}
