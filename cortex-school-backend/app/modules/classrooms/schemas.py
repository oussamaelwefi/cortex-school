import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from core.pydantic import CustomBaseModel
from modules.classrooms.models import TeacherAssignmentRole


ClassroomName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
]
WorkOSUserId = Annotated[
    str,
    StringConstraints(pattern=r"^user_[A-Za-z0-9]+$", max_length=255),
]


class ClassroomRequest(CustomBaseModel):
    name: ClassroomName


class ClassroomResponse(CustomBaseModel):
    id: uuid.UUID
    academic_year_id: uuid.UUID
    name: str
    created_at: datetime
    updated_at: datetime


class ClassEnrollmentCreateRequest(CustomBaseModel):
    enrollment_id: uuid.UUID
    effective_from: date
    effective_until: date | None = None

    @model_validator(mode="after")
    def validate_dates(self):
        if (
            self.effective_until is not None
            and self.effective_until <= self.effective_from
        ):
            raise ValueError("effective_until must be after effective_from")
        return self


class ClassEnrollmentResponse(CustomBaseModel):
    id: uuid.UUID
    classroom_id: uuid.UUID
    enrollment_id: uuid.UUID
    effective_from: date
    effective_until: date | None
    created_at: datetime
    updated_at: datetime


class ClassTransferRequest(CustomBaseModel):
    classroom_id: uuid.UUID
    effective_from: date


class TeacherAssignmentCreateRequest(CustomBaseModel):
    teacher_workos_user_id: WorkOSUserId
    role: TeacherAssignmentRole
    effective_from: date
    effective_until: date | None = None

    @model_validator(mode="after")
    def validate_dates(self):
        if (
            self.effective_until is not None
            and self.effective_until <= self.effective_from
        ):
            raise ValueError("effective_until must be after effective_from")
        return self


class TeacherAssignmentEndRequest(CustomBaseModel):
    effective_until: date


class TeacherAssignmentResponse(CustomBaseModel):
    id: uuid.UUID
    classroom_id: uuid.UUID
    teacher_workos_user_id: str
    role: TeacherAssignmentRole
    effective_from: date
    effective_until: date | None
    created_at: datetime
    updated_at: datetime


class TeacherClassroomResponse(ClassroomResponse):
    assignment_id: uuid.UUID
    assignment_role: TeacherAssignmentRole
    assignment_effective_from: date
    assignment_effective_until: date | None
    access_status: Literal["current", "upcoming"]


class TeacherClassroomStudentResponse(CustomBaseModel):
    student_id: uuid.UUID
    enrollment_id: uuid.UUID
    placement_id: uuid.UUID
    first_name: str
    last_name: str
    effective_from: date
    effective_until: date | None


class DirectoryAttendanceResponse(CustomBaseModel):
    present: int = 0
    late: int = 0
    absent: int = 0
    excused: int = 0
    recorded_days: int = 0
    rate: float | None = None


class DirectoryStudentResponse(CustomBaseModel):
    id: uuid.UUID
    first_name: str
    last_name: str
    enrollment_id: uuid.UUID | None
    placement_id: uuid.UUID | None = None
    classroom_id: uuid.UUID | None = None
    attendance: DirectoryAttendanceResponse
    guardian_ids: list[str] = Field(default_factory=list)


class DirectoryClassroomResponse(CustomBaseModel):
    id: uuid.UUID
    name: str
    teachers: list[TeacherAssignmentResponse]
    student_ids: list[uuid.UUID]


class SchoolDirectoryResponse(CustomBaseModel):
    year_id: uuid.UUID
    year_name: str
    year_status: str
    school_date: date
    roster_date: date
    attendance_from: date
    attendance_through: date | None
    classrooms: list[DirectoryClassroomResponse]
    students: list[DirectoryStudentResponse]
