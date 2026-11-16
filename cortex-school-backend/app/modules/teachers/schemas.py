import uuid
from datetime import date, datetime
from enum import StrEnum

from core.pydantic import CustomBaseModel
from modules.classrooms.models import TeacherAssignmentRole
from modules.student_updates.models import StudentUpdateTargetType


class TeacherTodayDayStatus(StrEnum):
    INSTRUCTIONAL = "instructional"
    NON_INSTRUCTIONAL = "non_instructional"
    OUTSIDE_ACTIVE_YEAR = "outside_active_year"


class TeacherTodayAttendanceStatus(StrEnum):
    NOT_STARTED = "not_started"
    SUBMITTED = "submitted"


class TeacherTodayAttendanceResponse(CustomBaseModel):
    status: TeacherTodayAttendanceStatus
    recorded_student_count: int
    exception_count: int
    submitted_at: datetime | None
    updated_at: datetime | None


class TeacherTodayUpdateResponse(CustomBaseModel):
    id: uuid.UUID
    title: str
    target_type: StudentUpdateTargetType
    recipient_count: int
    created_at: datetime
    authored_by_current_teacher: bool


class TeacherTodayClassroomResponse(CustomBaseModel):
    id: uuid.UUID
    name: str
    assignment_role: TeacherAssignmentRole
    active_student_count: int
    attendance: TeacherTodayAttendanceResponse
    recent_update: TeacherTodayUpdateResponse | None


class TeacherTodayResponse(CustomBaseModel):
    school_date: date
    current_school_date: date
    day_status: TeacherTodayDayStatus
    can_submit_attendance: bool
    ai_teacher_draft_enabled: bool
    classrooms: list[TeacherTodayClassroomResponse]
