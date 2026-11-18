import base64
import hashlib
import secrets
from html import escape
from time import time

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from itsdangerous import BadSignature, URLSafeTimedSerializer
from starlette.responses import HTMLResponse, RedirectResponse, Response
from workos import AsyncWorkOSClient, WorkOSError

from core.auth import WORKOS_CLIENT_ID, is_workos_operator, verify_workos_access_token
from core.config import settings


router = APIRouter(include_in_schema=False)
LOGIN_MAX_AGE_SECONDS = 600
LOGIN_COOKIE = "cortex_operator_login"
LOGIN_COOKIE_PATH = "/admin/auth"


def _login_signer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.ADMIN_SESSION_SECRET, salt="cortex-operator-login")


def _clear_login_cookie(response: Response) -> Response:
    response.delete_cookie(
        LOGIN_COOKIE,
        path=LOGIN_COOKIE_PATH,
        secure=settings.ENVIRONMENT != "development",
        httponly=True,
        samesite="lax",
    )
    return response


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(
        url,
        status_code=302,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


def _login_error(request: Request, error: str) -> RedirectResponse:
    response = _redirect(str(request.url_for("admin:login").include_query_params(error=error)))
    _clear_login_cookie(response)
    return response


@router.get("/admin/auth/login", name="operator_login_start")
async def operator_login_start(request: Request):
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    attempt = {
        "state": state,
        "verifier": verifier,
        "started_at": int(time()),
    }
    redirect_uri = settings.ADMIN_AUTH_REDIRECT_URI or str(request.url_for("operator_login_callback"))
    async with AsyncWorkOSClient(client_id=WORKOS_CLIENT_ID, is_public=True) as client:
        url = client.user_management.get_authorization_url(
            provider="authkit",
            screen_hint="sign-in",
            redirect_uri=redirect_uri,
            state=state,
            code_challenge=challenge,
            code_challenge_method="S256",
        )
    response = _redirect(url)
    # Only this short-lived cookie must accompany the cross-site WorkOS callback.
    response.set_cookie(
        LOGIN_COOKIE,
        _login_signer().dumps(attempt),
        max_age=LOGIN_MAX_AGE_SECONDS,
        path=LOGIN_COOKIE_PATH,
        secure=settings.ENVIRONMENT != "development",
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/admin/auth/callback", name="operator_login_callback")
async def operator_login_callback(request: Request):
    try:
        attempt = _login_signer().loads(
            request.cookies.get(LOGIN_COOKIE, ""), max_age=LOGIN_MAX_AGE_SECONDS
        )
    except BadSignature:
        return _login_error(request, "expired")
    state = request.query_params.get("state", "")
    if (
        not isinstance(attempt, dict)
        or not isinstance(attempt.get("state"), str)
        or not secrets.compare_digest(state.encode(), attempt["state"].encode())
        or not isinstance(attempt.get("started_at"), int)
        or not 0 <= time() - attempt["started_at"] <= LOGIN_MAX_AGE_SECONDS
        or not isinstance(attempt.get("verifier"), str)
    ):
        return _login_error(request, "expired")

    code = request.query_params.get("code")
    if request.query_params.get("error") or not code:
        return _login_error(request, "failed")

    try:
        async with AsyncWorkOSClient(
            client_id=WORKOS_CLIENT_ID,
            is_public=True,
            request_timeout=15,
            max_retries=0,
        ) as client:
            result = await client.user_management.authenticate_with_code(
                code=code,
                code_verifier=attempt["verifier"],
            )
        claims = await run_in_threadpool(verify_workos_access_token, result.access_token)
    except (WorkOSError, httpx.HTTPError, HTTPException):
        return _login_error(request, "failed")

    if not is_workos_operator(claims["sub"]):
        request.session.clear()
        return _login_error(request, "forbidden")

    request.session.clear()
    request.session["workos_operator"] = {
        "user_id": claims["sub"],
        "expires_at": int(claims["exp"]),
    }
    index_url = escape(str(request.url_for("admin:index")), quote=True)
    # Finish the cross-site navigation before opening the console, so browsers
    # send the Strict operator cookie on the next, same-site navigation.
    response = HTMLResponse(
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<meta http-equiv="refresh" content="0;url={index_url}">'
        '<title>Signed in to Cortex</title></head><body>'
        f'<p>Signed in. <a href="{index_url}">Open the operator console</a>.</p>'
        '</body></html>',
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )
    _clear_login_cookie(response)
    return response
