import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from core.pydantic import CustomBaseModel
from modules.academic_years.schemas import AcademicYearResponse
from modules.student_registration.models import StudentRegistrationStatus

ChildName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]
RejectionReason = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]


class GuardianEnrollmentResponse(CustomBaseModel):
    id: uuid.UUID
    academic_year: AcademicYearResponse
    created_at: datetime
    updated_at: datetime


class GuardianStudentResponse(CustomBaseModel):
    id: uuid.UUID
    first_name: str
    last_name: str
    enrollments: list[GuardianEnrollmentResponse]
    created_at: datetime
    updated_at: datetime


class StudentRegistrationRequestCreate(CustomBaseModel):
    child_first_name: ChildName
    child_last_name: ChildName
    academic_year_id: uuid.UUID


class StudentRegistrationRequestUpdate(CustomBaseModel):
    child_first_name: ChildName | None = None
    child_last_name: ChildName | None = None
    academic_year_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def require_at_least_one_change(self):
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        return self


class StudentRegistrationRequestResponse(CustomBaseModel):
    id: uuid.UUID
    guardian_workos_user_id: str
    organization_id: str
    child_first_name: str
    child_last_name: str
    academic_year_id: uuid.UUID
    status: StudentRegistrationStatus
    resolved_student_id: uuid.UUID | None
    rejection_reason: str | None
    created_at: datetime
    updated_at: datetime


class ApproveWithExistingStudent(CustomBaseModel):
    resolution: Literal["existing"]
    student_id: uuid.UUID


class ApproveWithNewStudent(CustomBaseModel):
    resolution: Literal["create"]


StudentRegistrationApproval = Annotated[
    ApproveWithExistingStudent | ApproveWithNewStudent,
    Field(discriminator="resolution"),
]


class StudentRegistrationRejection(CustomBaseModel):
    reason: RejectionReason

