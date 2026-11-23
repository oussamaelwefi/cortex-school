import json
from datetime import date, datetime, timezone
from io import BytesIO
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from sqlalchemy import select

from main import app
from modules.attendance import services as attendance_services
from modules.classrooms.models import ClassEnrollment
from modules.students.models import GuardianStudent
from modules.tutor import services
from modules.tutor.models import TutorClassBook
from modules.tutor.schemas import QuestionDraft, QuestionsDraft
from test_needs_review import seed_classroom


def lesson_pdf(include_text=True):
    writer = PdfWriter()
    page = writer.add_blank_page(width=250, height=200)
    if include_text:
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({
            NameObject("/F1"): DictionaryObject({
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }),
        })})
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 12 Tf 20 150 Td (Fractions represent equal parts of a whole.) Tj ET")
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


class QuizModel:
    def model_copy(self, **kwargs):
        return self

    def with_structured_output(self, schema, **kwargs):
        assert schema is QuestionsDraft
        return self

    async def ainvoke(self, messages):
        assert "Grade 4" in messages[0].content
        assert "Respond in French" in messages[0].content
        source = json.loads(messages[-1].content)["sources"][0]
        assert source["page"] == 1
        assert "Fractions represent equal parts" in source["excerpt"]
        return QuestionsDraft(questions=[QuestionDraft(
            prompt=f"Exercice {number} sur les fractions",
            options=["1/2", "1/3", "1/4", "1/5"],
            answer="1/2", explanation="Une moitié représente une partie sur deux.",
            correct_option=1, source_keys=[source["key"]],
        ) for number in range(1, 6)])


@pytest.mark.asyncio
async def test_teacher_publish_and_guardian_study_respect_classroom_scope(db_session, monkeypatch):
    school = "org_class_tutor"
    foreign_school = "org_class_tutor_foreign"
    first = await seed_classroom(db_session, organization_id=school, classroom_name="Grade 4A")
    second = await seed_classroom(db_session, organization_id=school, classroom_name="Grade 4B")
    third = await seed_classroom(db_session, organization_id=school, classroom_name="Grade 4C", teacher_id="user_other")
    foreign = await seed_classroom(db_session, organization_id=foreign_school)
    db_session.add_all([
        GuardianStudent(guardian_workos_user_id="user_guardian", student_id=seed.student.id)
        for seed in (first, third, foreign)
    ])
    await db_session.commit()

    def claims(token):
        role, user, organization = token.split(":")
        return {"sub": user, "org_id": organization, "role": role, "roles": [role]}

    async def active_guardian(user_id, organization_id):
        if user_id != "user_guardian":
            raise HTTPException(422, "Active guardian membership required")

    def auth(role, user, org=school):
        return {"Authorization": f"Bearer {role}:{user}:{org}"}

    def teacher_path(seed):
        return f"/api/teacher/classrooms/{seed.classroom.id}/study-materials/"

    def guardian_path(seed):
        return f"/api/guardian/tutor/children/{seed.student.id}/materials/"

    def upload(pdf, targets):
        return {"file": ("lesson.pdf", pdf, "application/pdf")}, {"metadata": json.dumps({
            "title": "Equivalent fractions", "subject": "Math", "grade_level": 4,
            "additional_classroom_ids": [str(seed.classroom.id) for seed in targets],
        })}

    monkeypatch.setattr("core.auth.verify_workos_access_token", claims)
    monkeypatch.setattr("modules.student_registration.services._require_active_guardian", active_guardian)
    monkeypatch.setattr(attendance_services, "utcnow", lambda: datetime(2026, 11, 23, tzinfo=timezone.utc))
    monkeypatch.setattr(services, "_consume_rate_limit", AsyncMock())
    monkeypatch.setattr(services, "get_chat_model", QuizModel)
    teacher = auth("teacher", "user_teacher")
    guardian = auth("guardian", "user_guardian")
    pdf = lesson_pdf()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        children = await client.get("/api/guardian/tutor/children/", headers=guardian)
        assert {item["id"]: item["classroom_name"] for item in children.json()} == {
            str(first.student.id): "Grade 4A", str(third.student.id): "Grade 4C",
        }
        assert (await client.get(teacher_path(third), headers=teacher)).status_code == 404
        for forbidden in (third, foreign):
            files, data = upload(pdf, [second, forbidden])
            assert (await client.post(teacher_path(first), headers=teacher, files=files, data=data)).status_code == 404
        assert (await client.get(teacher_path(first), headers=teacher)).json() == []
        files, data = upload(lesson_pdf(False), [])
        assert (await client.post(teacher_path(first), headers=teacher, files=files, data=data)).status_code == 422

        files, data = upload(pdf, [second])
        publication = await client.post(teacher_path(first), headers=teacher, files=files, data=data)
        assert publication.status_code == 200, publication.text
        material = publication.json()
        assert material["subject"] == "Math"
        assert material["indexed_page_count"] == material["page_count"] == 1
        assert (await client.post(teacher_path(first), headers=teacher, files=files, data=data)).json() == material
        second_materials = (await client.get(teacher_path(second), headers=teacher)).json()
        assert len(second_materials) == 1
        raw_book_id = (await db_session.execute(
            select(TutorClassBook.id).where(TutorClassBook.organization_id == school),
        )).scalar_one()

        assert (await client.get(guardian_path(first), headers=guardian)).json() == [material]
        assert (await client.get(guardian_path(second), headers=guardian)).status_code == 404
        assert (await client.get(guardian_path(third), headers=guardian)).json() == []
        scoped_path = guardian_path(first) + material["id"]
        scoped_pdf = await client.get(scoped_path + "/pdf/", headers=guardian)
        assert scoped_pdf.content == pdf
        assert scoped_pdf.headers["cache-control"] == "private, no-store"

        study = {"action": "quiz", "topic": "fractions", "language": "fr"}
        quiz = await client.post(scoped_path + "/study/", headers=guardian, json=study)
        assert quiz.status_code == 200, quiz.text
        result = quiz.json()
        assert result["status"] == "ready"
        assert len(result["questions"]) == 5
        assert all(question["source_ids"] == [result["sources"][0]["id"]] for question in result["questions"])

        legacy = f"/api/guardian/tutor/books/{raw_book_id}"
        assert (await client.get("/api/guardian/tutor/books/", headers=guardian)).json() == []
        assert (await client.get(legacy + "/pdf/", headers=guardian)).status_code == 404
        assert (await client.post(legacy + "/study/", headers=guardian, json=study)).status_code == 404
        wrong_class = guardian_path(third) + material["id"]
        assert (await client.get(wrong_class + "/pdf/", headers=guardian)).status_code == 404
        assert (await client.post(wrong_class + "/study/", headers=guardian, json=study)).status_code == 404

        first.placement.effective_until = date(2026, 11, 23)
        await db_session.flush()
        db_session.add(ClassEnrollment(
            classroom_id=third.classroom.id, enrollment_id=first.placement.enrollment_id,
            effective_from=date(2026, 11, 23),
        ))
        await db_session.commit()
        assert (await client.get(guardian_path(first), headers=guardian)).json() == []
        assert (await client.get(scoped_path + "/pdf/", headers=guardian)).status_code == 404
        assert (await client.post(scoped_path + "/study/", headers=guardian, json=study)).status_code == 404

        assert (await client.delete(teacher_path(first) + material["id"], headers=teacher)).status_code == 204
        assert (await client.get(teacher_path(first), headers=teacher)).json() == []
        assert (await client.get(teacher_path(second), headers=teacher)).json() == second_materials
