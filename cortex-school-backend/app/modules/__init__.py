import importlib
import pkgutil

from fastapi import Depends, status

from core.auth import get_current_user
from core.router import APIRouter

PACKAGE_NAME = "modules"
AUTH_DEPENDENCIES = [Depends(get_current_user)]
AUTH_RESPONSES = {
    status.HTTP_401_UNAUTHORIZED: {
        "description": "Missing, invalid, or expired bearer access token",
    }
}


def load_modules(api_router: APIRouter) -> None:
    package = importlib.import_module(PACKAGE_NAME)

    for _, module_name, ispkg in pkgutil.iter_modules([package.__path__[0]]):
        if not ispkg:
            continue

        base = f"{PACKAGE_NAME}.{module_name}"

        try:
            importlib.import_module(f"{base}.models")
        except ModuleNotFoundError:
            pass

        try:
            module = importlib.import_module(f"{base}.router")
        except ModuleNotFoundError:
            continue

        if hasattr(module, "router"):
            is_public = getattr(module, "PUBLIC", False)
            api_router.include_router(
                module.router,
                dependencies=[] if is_public else AUTH_DEPENDENCIES,
                responses={} if is_public else AUTH_RESPONSES,
            )


api_router = APIRouter(prefix="/api")

load_modules(api_router)
