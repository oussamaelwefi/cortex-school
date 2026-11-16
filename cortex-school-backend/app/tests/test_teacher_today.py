import os
import uuid

os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "root")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("POSTGRES_DB", "postgres")

import httpx
import pytest
from fastapi import HTTPException

from main import app
from modules.teachers.schemas import TeacherTodayDayStatus
from modules.teachers.services import _require_teacher_access, _teacher_today_day_status


def test_teacher_today_day_status_is_explicit():
    assert _teacher_today_day_status(
        has_active_year=False,
        is_instructional_day=False,
    ) == TeacherTodayDayStatus.OUTSIDE_ACTIVE_YEAR
    assert _teacher_today_day_status(
        has_active_year=True,
        is_instructional_day=False,
    ) == TeacherTodayDayStatus.NON_INSTRUCTIONAL
    assert _teacher_today_day_status(
        has_active_year=True,
        is_instructional_day=True,
    ) == TeacherTodayDayStatus.INSTRUCTIONAL


def test_teacher_access_does_not_trust_non_teacher_claims():
    with pytest.raises(HTTPException) as error:
        _require_teacher_access(
            {
                "user_id": "user_example",
                "organization_id": "org_example",
                "claims": {"role": "guardian"},
            }
        )
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_http_responses_include_request_id():
    transport = httpx.ASGITransport(app=app)
    request_id = str(uuid.uuid4())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/healthcheck",
            headers={"X-Request-ID": request_id},
        )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == request_id
