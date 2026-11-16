import uuid
from typing import Annotated

from pydantic import StringConstraints

from core.pydantic import CustomBaseModel


PersonName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]
WorkOSUserId = Annotated[
    str,
    StringConstraints(pattern=r"^user_[A-Za-z0-9]+$", max_length=255),
]


class StudentCreateRequest(CustomBaseModel):
    first_name: PersonName
    last_name: PersonName


class StudentUpdateRequest(CustomBaseModel):
    first_name: PersonName | None = None
    last_name: PersonName | None = None


class StudentResponse(CustomBaseModel):
    id: uuid.UUID
    organization_id: str
    first_name: str
    last_name: str


class GuardianCreateRequest(CustomBaseModel):
    guardian_workos_user_id: WorkOSUserId


class GuardianResponse(CustomBaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    guardian_workos_user_id: str
