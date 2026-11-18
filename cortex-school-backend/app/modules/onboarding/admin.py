import secrets
import uuid

from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool
from sqladmin import BaseView, expose
from sqlalchemy import or_, select
from starlette.requests import Request
from starlette.responses import RedirectResponse

from core.auth import has_operator_session
from core.db import SessionLocal
from modules.onboarding.models import SchoolRequest, SchoolRequestStatus
from modules.onboarding.services import review_school_request
from modules.onboarding.tasks import enqueue_school_provisioning


class SchoolRequestsAdmin(BaseView):
    name = "School requests"
    icon = "fa-solid fa-school-circle-check"

    @expose("/school-requests", methods=["GET", "POST"], identity="school_requests")
    async def school_requests(self, request: Request):
        # SQLAdmin's custom views do not automatically inherit our auth backend.
        if not has_operator_session(request):
            return RedirectResponse(request.url_for("admin:login"), status_code=302)
        csrf = request.session.setdefault("school_requests_csrf", secrets.token_urlsafe(32))
        error = ""
        if request.method == "POST":
            form = await request.form()
            token = form.get("csrf", "")
            if not isinstance(token, str) or not secrets.compare_digest(token.encode(), csrf.encode()):
                raise HTTPException(403, "Refresh this page before reviewing a request.")
            try:
                request_id = uuid.UUID(str(form.get("request_id", "")))
                decision = form.get("decision")
                if decision not in ("approve", "reject"):
                    raise HTTPException(422, "Choose approve or reject.")
                async with SessionLocal() as session:
                    result = await review_school_request(
                        session, request_id, request.session["workos_operator"]["user_id"],
                        approve=decision == "approve", reason=str(form.get("reason", "")),
                    )
                    if result.status == SchoolRequestStatus.PROVISIONING:
                        await run_in_threadpool(enqueue_school_provisioning, result.id)
                return RedirectResponse(
                    request.url_for("admin:school_requests").include_query_params(
                        status="all", request_id=str(result.id),
                    ),
                    status_code=303,
                )
            except ValueError:
                error = "Choose a valid school request."
            except HTTPException as exc:
                error = str(exc.detail)
        status = request.query_params.get("status", "pending")
        if status not in {value.value for value in SchoolRequestStatus} | {"all"}:
            status = "pending"
        search = request.query_params.get("search", "").strip()[:255]
        try:
            offset = max(0, int(request.query_params.get("offset", "0")))
        except ValueError:
            offset = 0
        query = select(SchoolRequest)
        reviewed_request_id = request.query_params.get("request_id")
        if reviewed_request_id:
            try:
                reviewed_request_id = uuid.UUID(reviewed_request_id)
            except ValueError:
                reviewed_request_id = None
            if reviewed_request_id:
                query = query.order_by((SchoolRequest.id == reviewed_request_id).desc())
        if status != "all":
            query = query.where(SchoolRequest.status == status)
        if search:
            query = query.where(or_(
                SchoolRequest.school_name.icontains(search, autoescape=True),
                SchoolRequest.requester_email.icontains(search, autoescape=True),
            ))
        async with SessionLocal() as session:
            requests = (await session.scalars(query.order_by(SchoolRequest.created_at.desc()).offset(offset).limit(51))).all()
        response = await self.templates.TemplateResponse(
            request,
            "sqladmin/school_requests.html",
            {
                "title": "School requests",
                "subtitle": "Review new schools and set up their first administrator.",
                "requests": requests[:50],
                "statuses": list(SchoolRequestStatus),
                "status": status,
                "search": search,
                "offset": offset,
                "has_next": len(requests) > 50,
                "csrf": csrf,
                "error": error,
            },
            status_code=400 if error else 200,
        )
        response.headers["Cache-Control"] = "no-store"
        return response
