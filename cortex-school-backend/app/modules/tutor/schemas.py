import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


StudyAction = Literal["search", "explain", "summary", "quiz", "practice"]


class TutorBookResponse(BaseModel):
    id: uuid.UUID
    title: str
    page_count: int
    indexed_page_count: int


class TutorSource(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    page: int
    excerpt: str


class StudyRequest(BaseModel):
    action: StudyAction
    topic: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] = ""
    start_page: int | None = Field(default=None, ge=1)
    end_page: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def require_topic_or_range(self):
        if not self.topic and self.start_page is None:
            raise ValueError("Enter a topic or a starting page.")
        if self.end_page is not None and (
            self.start_page is None or not self.start_page <= self.end_page <= self.start_page + 5
        ):
            raise ValueError("Choose a range of up to six pages.")
        return self


class QuestionText(BaseModel):
    prompt: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=800)]
    options: list[str] = Field(max_length=4, description="Four distinct choices for a quiz; empty for a practice test.")
    answer: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=800)]
    explanation: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class StudyQuestion(QuestionText):
    source_ids: list[uuid.UUID] = Field(min_length=1, max_length=4)


class LessonSectionContent(BaseModel):
    heading: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=550)]
    calculation: str | None = Field(default=None, max_length=140, description="An optional short calculation using Unicode math operators.")


class LessonSectionDraft(LessonSectionContent):
    source_keys: list[int] = Field(min_length=1, max_length=4, description="Numeric keys of these supporting passages.")


class LessonSection(LessonSectionContent):
    source_ids: list[uuid.UUID]


class LessonDraft(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    takeaway: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=350)]
    sections: list[LessonSectionDraft] = Field(min_length=1, max_length=4)


class StudyLesson(BaseModel):
    title: str
    takeaway: str
    sections: list[LessonSection]


class QuestionDraft(QuestionText):
    correct_option: int | None = Field(ge=1, le=4, description="The correct option number, 1 to 4, or null for a practice test.")
    source_keys: list[int] = Field(min_length=1, max_length=4, description="The numeric keys of supporting passages.")


class QuestionsDraft(BaseModel):
    questions: list[QuestionDraft] = Field(max_length=5, description="Three to five questions, or an empty list if the passages are insufficient.")


class StudyResponse(BaseModel):
    action: StudyAction
    status: Literal["ready", "no_sources", "generation_unavailable"]
    text: str = ""
    lesson: StudyLesson | None = None
    source_ids: list[uuid.UUID] = Field(default_factory=list)
    questions: list[StudyQuestion] = Field(default_factory=list)
    sources: list[TutorSource] = Field(default_factory=list)
