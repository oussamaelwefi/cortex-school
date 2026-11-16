from datetime import datetime

from sqlalchemy import and_

from modules.student_updates.models import (
    GuardianUpdateState,
    StudentUpdate,
    StudentUpdateRecipient,
    StudentUpdateStatus,
)
from modules.students.models import GuardianStudent, Student


def overdue_guardian_acknowledgements(query, organization_id: str, as_of: datetime):
    """Extend a query from StudentUpdate with its pending guardian/recipient pairs."""
    return (
        query.join(
            StudentUpdateRecipient,
            StudentUpdateRecipient.student_update_id == StudentUpdate.id,
        )
        .join(Student, Student.id == StudentUpdateRecipient.student_id)
        .join(GuardianStudent, GuardianStudent.student_id == Student.id)
        .outerjoin(
            GuardianUpdateState,
            and_(
                GuardianUpdateState.recipient_id == StudentUpdateRecipient.id,
                GuardianUpdateState.guardian_workos_user_id
                == GuardianStudent.guardian_workos_user_id,
            ),
        )
        .where(
            StudentUpdate.organization_id == organization_id,
            Student.organization_id == organization_id,
            StudentUpdate.requires_acknowledgement.is_(True),
            StudentUpdate.due_at < as_of,
            StudentUpdateRecipient.status != StudentUpdateStatus.COMPLETED,
            GuardianUpdateState.acknowledged_at.is_(None),
        )
    )
