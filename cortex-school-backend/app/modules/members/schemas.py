import uuid
from pydantic import Field

from core.pydantic import CustomBaseModel


class MemberSummaryResponse(CustomBaseModel):
    id: str
    name: str
    email: str


class MemberClassResponse(CustomBaseModel):
    id: uuid.UUID
    name: str
    academic_year_id: uuid.UUID
    academic_year_name: str
    assignment_role: str


class MemberChildResponse(CustomBaseModel):
    id: uuid.UUID
    name: str


class SchoolMemberResponse(MemberSummaryResponse):
    membership_id: str
    roles: list[str]
    status: str
    classrooms: list[MemberClassResponse] = Field(default_factory=list)
    children: list[MemberChildResponse] = Field(default_factory=list)
