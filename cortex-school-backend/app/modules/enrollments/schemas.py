import uuid
from datetime import datetime

from core.pydantic import CustomBaseModel


class EnrollmentCreateRequest(CustomBaseModel):
    academic_year_id: uuid.UUID


class EnrollmentResponse(CustomBaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    academic_year_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
