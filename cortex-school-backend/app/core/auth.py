import logging
from enum import StrEnum
from time import time
from typing import Annotated, Callable

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from core.config import settings

WORKOS_CLIENT_ID = "client_01KT21GY6QP06ZC02SWM7JKX20"
WORKOS_ISSUER = (
    "https://api.workos.com/user_management/client_01KNPFK6T004ZEGN2BQ6ET5XAQ"
)
WORKOS_JWKS_URL = f"https://api.workos.com/sso/jwks/{WORKOS_CLIENT_ID}"

bearer_security = HTTPBearer(auto_error=False)
workos_jwks = PyJWKClient(WORKOS_JWKS_URL)
logger = logging.getLogger("uvicorn.error").getChild(__name__)


class Permission(StrEnum):
    SCHOOL_MANAGE = "school:manage"


def _authentication_error(detail: str = "Invalid or expired access token") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def verify_workos_access_token(token: str) -> dict:
    try:
        signing_key = workos_jwks.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=WORKOS_ISSUER,
            options={"require": ["exp", "iat", "iss", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise _authentication_error() from exc
    except Exception as exc:
        raise _authentication_error("Unable to validate access token") from exc

    if claims.get("client_id") != WORKOS_CLIENT_ID:
        raise _authentication_error()

    return claims


def get_current_user(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_security),
    ],
) -> dict:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _authentication_error("Missing bearer access token")

    try:
        claims = verify_workos_access_token(credentials.credentials)
    except HTTPException as exc:
        reason = type(exc.__cause__).__name__ if exc.__cause__ else "client_id_mismatch"
        logger.info(
            "WorkOS access token rejected (%s) request_id=%s",
            reason,
            getattr(request.state, "request_id", "unknown"),
        )
        raise
    return {
        "user_id": claims["sub"],
        "organization_id": claims.get("org_id"),
        "session_id": claims.get("sid"),
        "claims": claims,
    }


def require_permission(permission: Permission) -> Callable:
    def check_permission(current_user: dict = Depends(get_current_user)) -> dict:
        permissions = current_user["claims"].get("permissions", [])
        if permission not in permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required permission: {permission}",
            )
        return current_user

    return check_permission


def is_workos_operator(user_id: str | None) -> bool:
    return user_id is not None and user_id in settings.WORKOS_OPERATOR_USER_IDS


def has_operator_session(request: Request) -> bool:
    session = request.scope.get("session", {}).get("workos_operator")
    if not isinstance(session, dict):
        return False
    expires_at = session.get("expires_at")
    return (
        isinstance(expires_at, int)
        and expires_at > time()
        and is_workos_operator(session.get("user_id"))
    )


def require_workos_operator(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_security)],
) -> None:
    if has_operator_session(request):
        return
    current_user = get_current_user(request, credentials)
    if not is_workos_operator(current_user["user_id"]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="WorkOS operator access is required",
        )
