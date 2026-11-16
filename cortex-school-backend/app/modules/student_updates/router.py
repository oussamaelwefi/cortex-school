from core.router import APIRouter
from modules.student_updates.routes.admin import router as admin_router
from modules.student_updates.routes.guardian import router as guardian_router
from modules.student_updates.routes.teacher import router as teacher_router


router = APIRouter()
router.include_router(teacher_router)
router.include_router(guardian_router)
router.include_router(admin_router)
