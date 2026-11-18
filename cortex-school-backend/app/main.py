from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse, ORJSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from core.auth import require_workos_operator
from core.admin import setup_admin
from core.config import settings
from core.db import close_db_connections
from core.operator_login import router as operator_login_router
from core.request_id import RequestIdMiddleware
from modules import api_router


infrastructure_router = APIRouter(include_in_schema=False)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    yield
    await close_db_connections()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.PROJECT_NAME,
        version="0.1.0",
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
        default_response_class=ORJSONResponse,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "WWW-Authenticate"],
    )
    app.add_middleware(RequestIdMiddleware)
    app.include_router(api_router)
    app.include_router(infrastructure_router)
    if settings.WORKOS_OPERATOR_USER_IDS and len(settings.ADMIN_SESSION_SECRET) >= 32:
        app.add_middleware(
            SessionMiddleware,
            secret_key=settings.ADMIN_SESSION_SECRET,
            session_cookie="cortex_operator",
            same_site="strict",
            https_only=settings.ENVIRONMENT != "development",
        )
        app.include_router(operator_login_router)
        setup_admin(app)
    return app


@infrastructure_router.get("/api/openapi.json", dependencies=[Depends(require_workos_operator)])
async def swagger_json(request: Request):
    app = request.app
    return JSONResponse(get_openapi(title=app.title, version=app.version, routes=app.routes))


@infrastructure_router.get("/api/docs", dependencies=[Depends(require_workos_operator)])
async def swagger_docs():
    return get_swagger_ui_html(title=f"{settings.PROJECT_NAME} Docs", openapi_url="/api/openapi.json")


@infrastructure_router.get("/api/redoc", dependencies=[Depends(require_workos_operator)])
async def swagger_redoc():
    return get_redoc_html(title=f"{settings.PROJECT_NAME} ReDoc", openapi_url="/api/openapi.json")


@infrastructure_router.get("/")
async def root():
    return RedirectResponse(url="/api/docs")


@infrastructure_router.get("/api/healthcheck")
async def healthcheck():
    return {"status": "ok"}


app = create_app()
