import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import (
    Field,
    NonNegativeInt,
    StringConstraints,
    field_validator,
    model_validator,
)
from typing_extensions import Annotated

from ai.chat.schemas import ChatSource
from core.pydantic import CustomBaseModel
from modules.student_updates.schemas import UpdateTarget, UpdateText, UpdateTitle


class TeacherDraftLanguage(StrEnum):
    AUTO = "auto"
    ENGLISH = "en"
    FRENCH = "fr"
    ARABIC = "ar"


class TeacherDraftTone(StrEnum):
    WARM = "warm"
    CONCISE = "concise"
    FORMAL = "formal"


TeacherDraftObservation = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=3000),
]
TeacherDraftQuestion = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]

GuardianExplanationTextValue = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]
GuardianExplanationSourceKey = Annotated[
    str,
    StringConstraints(pattern=r"^s[1-9][0-9]*$", min_length=2, max_length=4),
]


class TeacherUpdateDraftRequest(CustomBaseModel):
    classroom_id: uuid.UUID
    target: UpdateTarget
    observations: TeacherDraftObservation
    tone: TeacherDraftTone = TeacherDraftTone.WARM
    output_language: TeacherDraftLanguage | None = None


class TeacherUpdateDraftResult(CustomBaseModel):
    outcome: Literal["draft", "needs_more_information"]
    title: UpdateTitle | None = None
    body: UpdateText | None = None
    questions: list[TeacherDraftQuestion] = Field(
        default_factory=list,
        max_length=3,
    )

    @model_validator(mode="after")
    def validate_outcome_fields(self):
        if self.outcome == "draft":
            if self.title is None or self.body is None or self.questions:
                raise ValueError(
                    "draft outcomes require title and body without questions"
                )
        elif self.title is not None or self.body is not None or not self.questions:
            raise ValueError(
                "needs_more_information outcomes require questions without a draft"
            )
        return self


class GuardianWeeklyExplanationRequest(CustomBaseModel):
    output_language: TeacherDraftLanguage | None = None


class GuardianWeeklyExplanationText(CustomBaseModel):
    text: GuardianExplanationTextValue
    source_keys: list[GuardianExplanationSourceKey] = Field(
        min_length=1,
        max_length=27,
    )

    @field_validator("source_keys")
    @classmethod
    def source_keys_must_be_unique(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("source_keys must be unique")
        return value


class GuardianWeeklyExplanationModelResult(CustomBaseModel):
    overview: list[GuardianWeeklyExplanationText] = Field(
        min_length=1,
        max_length=3,
    )
    attendance_summary: GuardianWeeklyExplanationText | None = None
    school_updates: list[GuardianWeeklyExplanationText] = Field(
        default_factory=list,
        max_length=20,
    )
    follow_up: GuardianWeeklyExplanationText | None = None


class GuardianWeeklyAttendanceCounts(CustomBaseModel):
    present: NonNegativeInt = 0
    absent: NonNegativeInt = 0
    late: NonNegativeInt = 0
    excused: NonNegativeInt = 0


class GuardianWeeklyAttendance(CustomBaseModel):
    counts: GuardianWeeklyAttendanceCounts
    submitted_dates: list[date] = Field(default_factory=list)
    missing_dates: list[date] = Field(default_factory=list)
    source_keys: list[GuardianExplanationSourceKey] = Field(
        default_factory=list,
        max_length=7,
    )
    summary: GuardianWeeklyExplanationText | None = None


class GuardianWeeklyExplanationSource(CustomBaseModel):
    key: GuardianExplanationSourceKey
    kind: Literal["attendance", "update"]
    label: str
    school_date: date | None = None
    href: str


class GuardianWeeklyExplanationResponse(CustomBaseModel):
    status: Literal["generated", "empty", "fallback"]
    ai_generated: bool
    retryable: bool
    student_id: uuid.UUID
    date_from: date
    date_to: date
    school_timezone: str
    output_language: TeacherDraftLanguage
    generated_at: datetime
    overview: list[GuardianWeeklyExplanationText] = Field(default_factory=list)
    attendance: GuardianWeeklyAttendance
    school_updates: list[GuardianWeeklyExplanationText] = Field(
        default_factory=list,
        max_length=20,
    )
    follow_up: GuardianWeeklyExplanationText | None = None
    limitations: list[str] = Field(default_factory=list, max_length=5)
    sources: list[GuardianWeeklyExplanationSource] = Field(
        default_factory=list,
        max_length=27,
    )


class ChatDataPreferenceRequest(CustomBaseModel):
    enabled: bool


class ChatDataAccessResponse(CustomBaseModel):
    school_data_enabled: bool
    personal_data_enabled: bool
    effective_data_enabled: bool
    can_manage_school: bool
    can_manage_personal: bool
    revision: int


class ChatRequest(CustomBaseModel):
    message: str = Field(min_length=1, max_length=30000)
    role: Literal["admin", "teacher", "guardian"] | None = None
    language: Literal["fr", "en"] = "fr"
    conversation_id: uuid.UUID | None = None
    client_message_id: uuid.UUID | None = None


class ChatResponse(CustomBaseModel):
    reply: str
    sources: list[ChatSource] = Field(default_factory=list)
    conversation_id: uuid.UUID | None = None
    message_id: uuid.UUID | None = None
    created_at: datetime | None = None
    hidden: bool = False


class ChatConversationSummary(CustomBaseModel):
    id: uuid.UUID
    title: str
    updated_at: datetime


class ChatConversationList(CustomBaseModel):
    conversations: list[ChatConversationSummary]
    next_offset: int | None


class ChatHistoryMessage(CustomBaseModel):
    id: uuid.UUID
    sender: Literal["user", "assistant"]
    text: str | None
    sources: list[ChatSource]
    created_at: datetime


class ChatConversationDetail(ChatConversationSummary):
    messages: list[ChatHistoryMessage]
    before_turn: int | None
