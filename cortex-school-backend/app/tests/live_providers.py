import os
from io import BytesIO

import httpx
import pytest
from pypdf import PdfWriter

from core.auth import WORKOS_CLIENT_ID
from core.config import settings
from main import app
from modules.reminders.agent import draft_reminder
from modules.reminders.policy import add_policy
from modules.schools.models import Country, School
from modules.tutor.import_book import store_book


@pytest.fixture(scope="session", autouse=True)
def require_live_configuration():
    if settings.ENVIRONMENT != "testing" or settings.database.POSTGRES_DB != "cortex_test":
        pytest.fail("Live tests require ENVIRONMENT=testing and a disposable cortex_test database.")
    missing = [
        name
        for name in (
            "WORKOS_API_KEY",
            "WORKOS_TEST_GUARDIAN_EMAIL",
            "WORKOS_TEST_GUARDIAN_PASSWORD",
            "WORKOS_TEST_ORGANIZATION_ID",
            "OPENROUTER_API_KEY",
        )
        if not os.environ.get(name)
    ]
    if missing:
        pytest.fail("Missing live test settings: " + ", ".join(missing))


async def sign_in_guardian(organization_id: str) -> str:
    route = "/user_management/authenticate"
    credentials = {
        "client_id": WORKOS_CLIENT_ID,
        "client_secret": settings.WORKOS_API_KEY,
    }
    async with httpx.AsyncClient(base_url="https://api.workos.com", timeout=20) as workos:
        response = await workos.post(route, json={
            **credentials,
            "grant_type": "password",
            "email": os.environ["WORKOS_TEST_GUARDIAN_EMAIL"],
            "password": os.environ["WORKOS_TEST_GUARDIAN_PASSWORD"],
        })
        data = response.json()
        if data.get("code") == "organization_selection_required":
            response = await workos.post(route, json={
                **credentials,
                "grant_type": "urn:workos:oauth:grant-type:organization-selection",
                "organization_id": organization_id,
                "pending_authentication_token": data["pending_authentication_token"],
            })
            data = response.json()
    if not response.is_success:
        pytest.fail(
            f"WorkOS sign-in returned HTTP {response.status_code}. "
            "Check the staging API key, password sign-in, test user, and organization."
        )
    if data.get("organization_id") != organization_id or not data.get("access_token"):
        pytest.fail("WorkOS did not return a session for the configured test organization.")
    return data["access_token"]


@pytest.mark.asyncio
async def test_live_guardian_sign_in_and_cited_tutor_summary(db_session):
    organization_id = os.environ["WORKOS_TEST_ORGANIZATION_ID"]
    token = await sign_in_guardian(organization_id)
    async with db_session.begin():
        db_session.add(Country(code="TN", name="Tunisia", calling_code="+216"))
        await db_session.flush()
        db_session.add(School(organization_id=organization_id, country_code="TN"))

    pdf = BytesIO()
    writer = PdfWriter()
    for _ in range(2):
        writer.add_blank_page(width=100, height=100)
    writer.write(pdf)
    passage = "مساحة المثلث تساوي نصف حاصل ضرب القاعدة في الارتفاع."
    book_id, _, _ = await store_book(
        db_session, organization_id, "كتاب الرياضيات التجريبي", pdf.getvalue(), {2: passage}
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/api/guardian/tutor/books/{book_id}/study/",
            headers={"Authorization": f"Bearer {token}"},
            json={"action": "summary", "topic": "مساحة المثلث"},
        )

    assert response.status_code == 200, (
        f"The tutor API returned HTTP {response.status_code}. "
        "Check WorkOS token validation and the guardian role in the test organization."
    )
    result = response.json()
    assert result["status"] == "ready", (
        f"The tutor returned {result['status']}. Check retrieval, Redis and the OpenRouter model."
    )
    source, = result["sources"]
    assert (source["page"], source["excerpt"]) == (2, passage)
    assert result["lesson"]["sections"]
    assert all(section["source_ids"] == [source["id"]] for section in result["lesson"]["sections"])


@pytest.mark.asyncio
async def test_live_reminder_agent_cites_school_pickup_policy(db_session):
    organization_id = "org_ci_policy_fixture"
    policy = await add_policy(db_session, organization_id, "School pickup", [
        ("Pickup gate", "Guardians collect students at the north gate during school pickup."),
    ])
    message, sources = await draft_reminder(db_session, organization_id, {
        "title": "School pickup at the north gate",
        "notice": "Guardians should acknowledge the school pickup instructions.",
        "due_at": "2026-09-15T17:00:00+00:00",
        "pending_guardian_count": 2,
    })
    assert message.strip()
    assert {source.document_id for source in sources} == {policy.id}
