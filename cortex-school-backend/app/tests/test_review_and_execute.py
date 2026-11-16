import asyncio
import json
import uuid
from datetime import timedelta
from io import BytesIO

import httpx
import pytest
from fastapi import HTTPException
from langchain_core.messages import AIMessage
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from sqlalchemy import delete

from core.db import SessionLocal, utcnow
from main import app
from modules.reminders import agent
from modules.reminders.models import SchoolPolicyFile, SchoolPolicyPassage
from modules.reminders.policy import add_policy, search_policy
from modules.reminders.policy_pdf import pdf_policy_passages
from modules.reminders.tasks import deliver_queued_proposal
from modules.student_updates.models import (
    StudentUpdate,
    StudentUpdateRecipient,
    StudentUpdateTargetType,
)
from modules.students.models import GuardianStudent
from test_needs_review import cleanup_organization, seed_classroom


class ReminderModel:
    def __init__(self):
        self.citation = None
        self.invalid_citation = False
        self.policy_result = ""

    def bind_tools(self, tools, **kwargs):
        assert [tool.name for tool in tools[:2]] == ["get_acknowledgement_detail", "search_school_policy"]
        return self

    async def ainvoke(self, messages):
        if len(messages) == 2:
            name, arguments = "get_acknowledgement_detail", {}
        elif len(messages) == 4:
            assert "Guardian-" not in messages[-1].content
            name, arguments = "search_school_policy", {"keywords": ["pickup"]}
        else:
            self.policy_result = messages[-1].content
            sources = json.loads(self.policy_result)
            self.citation = sources[0]["id"] if sources else None
            name = "ReminderDraft"
            if not self.citation:
                arguments = {"message": None, "source_ids": []}
            else:
                citation = str(uuid.uuid4()) if self.invalid_citation else self.citation
                arguments = {"message": "Please acknowledge the pickup notice in the school portal.", "source_ids": [citation]}
        return AIMessage(content="", tool_calls=[{"name": name, "args": arguments, "id": f"tool-{len(messages)}"}])


def policy_pdf(*, blank=False):
    writer = PdfWriter()
    writer.add_blank_page(300, 400)
    if not blank:
        page = writer.add_blank_page(300, 400)
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
        })
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 12 Tf 30 365 Td (Use the school portal for pickup acknowledgements.) Tj ET")
        page.replace_contents(stream)
    with BytesIO() as output:
        writer.write(output)
        return output.getvalue()


@pytest.mark.asyncio
@pytest.mark.parametrize("draft_method", ["text", "pdf", "standard", "standard_replacement"])
async def test_review_and_execute(monkeypatch, draft_method):
    use_policy = draft_method != "standard"
    organization, other_school = (f"reminder-{uuid.uuid4()}" for _ in range(2))
    confirmed, late, pending = (f"Guardian-{i}-{uuid.uuid4()}" for i in range(3))
    model = ReminderModel()

    def get_model():
        assert use_policy, "The standard reminder must not call the model"
        return model

    monkeypatch.setattr(agent, "get_chat_model", get_model)

    def claims(token):
        role, user_id, org_id = token.split(":")
        return {
            "sub": user_id,
            "org_id": org_id,
            "role": role,
            "roles": [role],
            "permissions": ["school:manage"] if role == "school_admin" else [],
        }

    monkeypatch.setattr("core.auth.verify_workos_access_token", claims)

    async def require_active_guardian(user_id, org_id):
        if (org_id == organization and user_id in {confirmed, late, pending}) or (
            org_id == other_school and user_id == "other-guardian"
        ):
            return
        raise HTTPException(422, "Active guardian membership required")

    monkeypatch.setattr(
        "modules.student_registration.services._require_active_guardian", require_active_guardian
    )

    def headers(user_id, org=organization, role="guardian"):
        return {"Authorization": f"Bearer {role}:{user_id}:{org}"}

    admin = headers("admin", role="school_admin")
    outsider = headers("other-admin", other_school, "school_admin")
    async with SessionLocal() as session:
        classroom = await seed_classroom(session, organization_id=organization)
        notice = StudentUpdate(
            organization_id=organization, classroom_id=classroom.classroom.id,
            teacher_workos_user_id=classroom.teacher_id,
            target_type=StudentUpdateTargetType.CLASSROOM, title="New pickup instructions",
            due_at=utcnow() - timedelta(days=1), requires_acknowledgement=True,
        )
        session.add(notice)
        await session.flush()
        recipient = StudentUpdateRecipient(
            student_update_id=notice.id, student_id=classroom.student.id,
            class_enrollment_id=classroom.placement.id,
        )
        session.add(recipient)
        session.add_all([
            GuardianStudent(student_id=classroom.student.id, guardian_workos_user_id=user_id)
            for user_id in (confirmed, late, pending)
        ])
        await session.commit()
        notice_id, recipient_id = notice.id, recipient.id

    review_path = f"/api/student-updates/{notice_id}/reminder"
    ack_path = f"/api/guardian/updates/{recipient_id}/acknowledge"
    policy_path = "/api/school-policies"
    notification_path = "/api/guardian/notifications"
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.post(ack_path, headers=headers(confirmed))).status_code == 200
            assert (await client.get(review_path, headers=admin)).json()["pending_guardian_count"] == 2
            assert (await client.get(review_path, headers=outsider)).status_code == 404
            assert (await client.get(policy_path, headers=headers(confirmed))).status_code == 403
            assert (await client.post(policy_path, headers=outsider, json={
                "title": "Pickup policy", "text": "Other school pickup policy."
            })).status_code == 201
            if use_policy:
                assert (await client.post(review_path, headers=admin)).status_code == 422
                if draft_method == "pdf":
                    pdf_path = f"{policy_path}/pdf"
                    uploaded_file = {"file": ("Pickup policy.pdf", policy_pdf(), "application/pdf")}
                    assert (await client.post(pdf_path, headers=headers(confirmed), files=uploaded_file)).status_code == 403
                    invalid = await client.post(pdf_path, headers=admin, files={
                        "file": ("fake.pdf", b"This is not a PDF", "application/pdf"),
                    })
                    assert invalid.status_code == 422
                    blank = await client.post(pdf_path, headers=admin, files={
                        "file": ("blank.pdf", policy_pdf(blank=True), "application/pdf"),
                    })
                    assert blank.status_code == 422
                    assert "no readable text" in blank.json()["detail"]
                    assert (await client.get(policy_path, headers=admin)).json() == []
                    guardian_path = "/api/guardian/family/policies"
                    async with SessionLocal() as session:
                        legacy = await add_policy(session, organization, "Pickup policy", pdf_policy_passages(uploaded_file["file"][1]))
                    assert (await client.get(guardian_path, headers=headers(confirmed))).json() == []

                    uploads = await asyncio.gather(*[
                        client.post(pdf_path, headers=admin, files=uploaded_file) for _ in range(2)
                    ])
                    for uploaded in uploads:
                        assert uploaded.status_code == 201, uploaded.text
                        assert uploaded.json() == {
                            "id": str(legacy.id), "title": "Pickup policy", "passage_count": 1, "has_pdf": True,
                        }
                    assert (await client.get(policy_path, headers=admin)).json() == [uploads[0].json()]

                    active_guardian = headers(confirmed)
                    other_guardian = headers("other-guardian", other_school)
                    forbidden = headers("teacher", organization, "teacher")
                    download_path = f"{guardian_path}/{legacy.id}/pdf"
                    assert (await client.get(guardian_path, headers=active_guardian)).json() == [
                        {"id": str(legacy.id), "title": "Pickup policy"},
                    ]
                    assert (await client.get(guardian_path, headers=other_guardian)).json() == []
                    assert (await client.get(download_path, headers=other_guardian)).status_code == 404
                    assert (await client.get(download_path, headers=forbidden)).status_code == 403
                    downloaded = await client.get(download_path, headers=active_guardian)
                    assert downloaded.status_code == 200
                    assert downloaded.headers["content-type"] == "application/pdf"
                    assert downloaded.headers["content-disposition"].endswith("Pickup%20policy.pdf")
                    assert downloaded.headers["cache-control"] == "private, no-store"
                    assert downloaded.content == uploaded_file["file"][1]
                else:
                    assert (await client.post(policy_path, headers=admin, json={
                        "title": "Pickup policy", "text": "# Pickup acknowledgement\nUse the school portal for pickup acknowledgements."
                    })).status_code == 201

                model.invalid_citation = True
                assert (await client.post(review_path, headers=admin)).status_code == 502
                model.invalid_citation = False
                response = await client.post(review_path, headers=admin)
            else:
                invalid = await client.post(review_path, headers=admin, json={"message": " "})
                assert invalid.status_code == 422
                standard_message = "Please review and acknowledge the pickup notice."
                response = await client.post(review_path, headers=admin, json={"message": standard_message})

            assert response.status_code == 200, response.text
            proposal = response.json()["proposal"]
            assert {row["guardian_id"] for row in proposal["recipients"]} == {late, pending}
            if use_policy:
                assert proposal["sources"][0]["id"] == model.citation
                expected_heading = "Page 2" if draft_method == "pdf" else "Pickup acknowledgement"
                assert proposal["sources"][0]["heading"] == expected_heading
                assert "Use the school portal" in proposal["sources"][0]["excerpt"]
                assert "Other school" not in model.policy_result
            else:
                assert proposal["message"] == standard_message
                assert proposal["sources"] == []
                retry = await client.post(review_path, headers=admin, json={"message": standard_message})
                assert retry.json()["proposal"]["id"] == proposal["id"]
            async with SessionLocal() as session:
                assert not await deliver_queued_proposal(session)

            approve_path = f"/api/reminder-proposals/{proposal['id']}/approve"
            approval = {"message": "Approved reminder: please confirm pickup in the school portal."}
            if draft_method == "standard_replacement":
                approval["include_policy_sources"] = False
            assert (await client.post(approve_path, headers=outsider, json=approval)).status_code == 404
            assert (await client.post(approve_path, headers=admin, json=approval)).json()["proposal"]["status"] == "queued"
            assert (await client.get(notification_path, headers=headers(pending))).json() == []
            assert (await client.post(ack_path, headers=headers(late))).status_code == 200
            async with SessionLocal() as session:
                assert await deliver_queued_proposal(session)
                assert not await deliver_queued_proposal(session)
            assert (await client.post(approve_path, headers=admin, json=approval)).status_code == 200
            assert (await client.post(approve_path, headers=admin, json={"message": "Changed"})).status_code == 409

            results = (await client.get(review_path, headers=admin)).json()["proposal"]
            assert results["status"] == "completed"
            assert {row["guardian_id"]: row["status"] for row in results["recipients"]} == {late: "skipped", pending: "sent"}
            notifications = (await client.get(notification_path, headers=headers(pending))).json()
            assert len(notifications) == 1
            assert notifications[0]["notification_type"] == "acknowledgement_reminder"
            assert notifications[0]["message"] == approval["message"]
            expected_sources = [
                {**source, "has_pdf": draft_method == "pdf"} for source in proposal["sources"]
            ] if draft_method in {"text", "pdf"} else []
            assert notifications[0]["policy_sources"] == expected_sources
            read_path = f"{notification_path}/{notifications[0]['id']}/read"
            for user_id in (confirmed, late):
                assert (await client.get(notification_path, headers=headers(user_id))).json() == []
                assert (await client.post(read_path, headers=headers(user_id))).status_code == 404
            other_guardian = headers("other-guardian", other_school)
            assert (await client.get(notification_path, headers=other_guardian)).json() == []
            assert (await client.post(read_path, headers=other_guardian)).status_code == 404
            read = await client.post(read_path, headers=headers(pending))
            assert read.status_code == 200, read.text
            assert read.json()["read_at"] is not None
            assert read.json()["policy_sources"] == expected_sources

            if draft_method == "pdf":
                source_id = notifications[0]["policy_sources"][0]["document_id"]
                downloaded = await client.get(f"{guardian_path}/{source_id}/pdf", headers=headers(pending))
                assert downloaded.status_code == 200
                assert downloaded.content == uploaded_file["file"][1]
                new_pdf = ("Family handbook.pdf", uploaded_file["file"][1], "application/pdf")
                new_upload = await client.post(pdf_path, headers=admin, files={"file": new_pdf})
                assert new_upload.status_code == 201, new_upload.text
                new_id = new_upload.json()["id"]
                assert new_upload.json()["has_pdf"] is True
                assert new_id != str(legacy.id)
                downloaded = await client.get(f"{guardian_path}/{new_id}/pdf", headers=active_guardian)
                assert downloaded.status_code == 200
                assert downloaded.content == new_pdf[1]

                admin_pdf_path = f"{policy_path}/{new_id}/pdf"
                admin_download = await client.get(admin_pdf_path, headers=admin)
                assert admin_download.status_code == 200
                assert admin_download.content == new_pdf[1]
                assert (await client.get(admin_pdf_path, headers=outsider)).status_code == 404
                assert (await client.get(admin_pdf_path, headers=active_guardian)).status_code == 403

                delete_path = f"{policy_path}/{new_id}"
                assert (await client.delete(delete_path, headers=outsider)).status_code == 404
                assert (await client.delete(delete_path, headers=active_guardian)).status_code == 403
                assert (await client.delete(delete_path, headers=admin)).status_code == 204
                assert (await client.delete(delete_path, headers=admin)).status_code == 404
                assert (await client.get(admin_pdf_path, headers=admin)).status_code == 404
                assert (await client.get(f"{guardian_path}/{new_id}/pdf", headers=active_guardian)).status_code == 404
                assert (await client.get(guardian_path, headers=active_guardian)).json() == [
                    {"id": str(legacy.id), "title": "Pickup policy"},
                ]
                async with SessionLocal() as session:
                    assert await search_policy(session, organization, ["family handbook"]) == []

            if draft_method == "text":
                source_document_id = proposal["sources"][0]["document_id"]
                assert (await client.delete(f"{policy_path}/{source_document_id}", headers=admin)).status_code == 204
                assert (await client.get(policy_path, headers=admin)).json() == []
                stored = await client.get(review_path, headers=admin)
                assert stored.json()["proposal"]["sources"] == proposal["sources"]
                notifications = (await client.get(notification_path, headers=headers(pending))).json()
                assert notifications[0]["policy_sources"] == []
    finally:
        async with SessionLocal() as session:
            await session.execute(delete(SchoolPolicyFile).where(
                SchoolPolicyFile.organization_id.in_([organization, other_school])
            ))
            await session.execute(delete(SchoolPolicyPassage).where(
                SchoolPolicyPassage.organization_id.in_([organization, other_school])
            ))
            await cleanup_organization(session, organization)
