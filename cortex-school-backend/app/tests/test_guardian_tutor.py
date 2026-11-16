import json
from io import BytesIO

import httpx
import pytest
from fastapi import HTTPException
from pypdf import PdfWriter

from ai.llm import LLMNotConfiguredError
from main import app
from modules.tutor import services
from modules.tutor.import_book import store_book
from modules.tutor.schemas import LessonDraft, LessonSectionDraft, QuestionDraft, QuestionsDraft
from test_needs_review import seed_classroom


class StudyModel:
    def model_copy(self, **kwargs):
        return self

    def with_structured_output(self, schema, **kwargs):
        self.schema = schema
        return self

    async def ainvoke(self, messages):
        prompt = json.loads(messages[-1].content)
        citation = prompt["sources"][0]["key"]
        if prompt["topic"] == "invalid مساحة":
            citation = 999
        if self.schema is LessonDraft:
            return LessonDraft(
                title="مساحة المثلث",
                takeaway="مساحة المثلث نصف حاصل ضرب القاعدة في الارتفاع.",
                sections=[LessonSectionDraft(
                    heading="مثال", body="اضرب القاعدة في الارتفاع ثم اقسم على اثنين.",
                    calculation="6 × 4 ÷ 2 = 12", source_keys=[citation],
                )],
            )
        quiz = "four distinct options" in messages[0].content
        return QuestionsDraft(questions=[
            QuestionDraft(
                prompt=f"احسب مساحة المثلث رقم {index}.",
                options=["12", "6", "3", "4"] if quiz else [],
                answer="6", correct_option=2 if quiz else None,
                explanation="اضرب ثم اقسم على اثنين.", source_keys=[citation],
            ) for index in range(1, 4)
        ])


@pytest.mark.asyncio
async def test_guardian_tutor_retrieves_school_book_and_validates_sources(db_session, monkeypatch):
    school = "org_tutor_school"
    await seed_classroom(db_session, organization_id=school)
    await seed_classroom(db_session, organization_id="org_other")
    await db_session.commit()
    pdf = BytesIO()
    writer = PdfWriter()
    for _ in range(8):
        writer.add_blank_page(width=100, height=100)
    writer.write(pdf)
    book, count, indexed = await store_book(db_session, school, "الرياضيات", pdf.getvalue(), {
        4: '<file name="004.pdf">\nمساحة المثلث = القاعدة × الارتفاع ÷ 2\n</file>',
        7: "محيط المضلع هو مجموع أطوال أضلاعه.",
    })
    assert (count, indexed) == (8, 2)
    same_book, _, _ = await store_book(db_session, school, "الرياضيات", pdf.getvalue(), {
        4: "001-020 7/12/07 12:05 Page 4\n4\n\u200fمساحة المثلث = القاعدة × الارتفاع ÷ 2\n4",
    })
    assert same_book == book

    def claims(token):
        role, org = token.split(":")
        return {"sub": f"user_{role}", "org_id": org, "role": role, "roles": [role]}

    async def active_guardian(user_id, organization_id):
        if user_id != "user_guardian":
            raise HTTPException(422, "Active guardian membership required")

    async def rate_limit(*args, **kwargs):
        return None

    def unavailable():
        raise LLMNotConfiguredError("provider unavailable")

    monkeypatch.setattr("core.auth.verify_workos_access_token", claims)
    monkeypatch.setattr("modules.student_registration.services._require_active_guardian", active_guardian)
    monkeypatch.setattr(services, "_consume_rate_limit", rate_limit)
    monkeypatch.setattr(services, "get_chat_model", unavailable)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        path = "/api/guardian/tutor/books/"
        study = f"{path}{book}/study/"
        source_pdf = f"{path}{book}/pdf/"
        guardian = {"Authorization": f"Bearer guardian:{school}"}
        foreign = {"Authorization": "Bearer guardian:org_other"}
        teacher = {"Authorization": f"Bearer teacher:{school}"}
        metadata = (await client.get(path, headers=guardian)).json()
        assert metadata[0]["id"] == str(book)
        assert metadata[0]["indexed_page_count"] == 1
        assert (await client.get(path, headers=foreign)).json() == []
        assert (await client.get(path, headers=teacher)).status_code == 403
        assert (await client.get(path)).status_code == 401
        assert (await client.get(source_pdf, headers=foreign)).status_code == 404
        assert (await client.post(study, headers=foreign, json={"action": "search", "start_page": 4})).status_code == 404

        download = await client.get(source_pdf, headers=guardian)
        assert download.headers["content-type"] == "application/pdf"
        assert download.headers["cache-control"] == "private, no-store"
        assert download.content == pdf.getvalue()

        query = {"topic": "ما هي مَساحة المُثَلَّث؟"}
        search = await client.post(study, headers=guardian, json={"action": "search", **query})
        assert search.status_code == 200, search.text
        passages = search.json()["sources"]
        assert len(passages) == 1
        assert (passages[0]["page"], passages[0]["excerpt"]) == (4, "مساحة المثلث = القاعدة × الارتفاع ÷ 2")
        missing = await client.post(study, headers=guardian, json={"action": "search", "start_page": 7})
        assert missing.json()["status"] == "no_sources"
        invalid = await client.post(study, headers=guardian, json={"action": "search", "start_page": 9})
        assert invalid.status_code == 422
        fallback = await client.post(study, headers=guardian, json={"action": "explain", **query})
        assert fallback.json()["status"] == "generation_unavailable"
        assert fallback.json()["sources"] == passages

        monkeypatch.setattr(services, "get_chat_model", StudyModel)
        for action in ("summary", "explain", "quiz", "practice"):
            response = await client.post(study, headers=guardian, json={"action": action, **query})
            assert response.status_code == 200, response.text
            result = response.json()
            assert result["status"] == "ready"
            assert result["sources"] == passages
            if action in {"quiz", "practice"}:
                assert all(q["source_ids"] == [passages[0]["id"]] for q in result["questions"])
                assert len(result["questions"][0]["options"]) == (4 if action == "quiz" else 0)
            else:
                assert result["lesson"]["title"] == "مساحة المثلث"
                assert result["lesson"]["sections"][0]["calculation"] == "6 × 4 ÷ 2 = 12"
                assert result["lesson"]["sections"][0]["source_ids"] == [passages[0]["id"]]
        bad_citation = await client.post(study, headers=guardian, json={"action": "explain", "topic": "invalid مساحة"})
        assert bad_citation.json()["status"] == "generation_unavailable"
