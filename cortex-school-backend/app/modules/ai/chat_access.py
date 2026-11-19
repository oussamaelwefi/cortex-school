"""Deterministic tool access; no consent decision is delegated to the model."""

from core.db import utcnow
from fastapi import HTTPException
from modules.ai.models import GuardianChatPreference
from modules.schools.models import School
from modules.students.models import GuardianStudent, Student
from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import insert


def blocked_guardians(organization_id):
    return (
        select(GuardianChatPreference.guardian_user_id)
        .where(
            GuardianChatPreference.organization_id == organization_id,
            GuardianChatPreference.data_enabled.is_(False),
        )
        .correlate(None)
    )


def protected_students(organization_id):
    # A single opt-out protects a shared child, even if another guardian opted in.
    return (
        select(GuardianStudent.student_id)
        .join(
            Student,
            Student.id == GuardianStudent.student_id,
        )
        .where(
            Student.organization_id == organization_id,
            GuardianStudent.guardian_workos_user_id.in_(
                blocked_guardians(organization_id)
            ),
        )
        .correlate(None)
    )


async def access_state(session, current_user, role):
    row = (
        await session.execute(
            select(
                School.ai_chat_data_enabled,
                School.ai_chat_data_revision,
                exists(
                    select(GuardianChatPreference.guardian_user_id).where(
                        GuardianChatPreference.organization_id
                        == School.organization_id,
                        GuardianChatPreference.guardian_user_id
                        == current_user["user_id"],
                        GuardianChatPreference.data_enabled.is_(False),
                    )
                ),
            ).where(School.organization_id == current_user["organization_id"])
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(404, "School not found")
    school_enabled, revision, opted_out = row
    # Personal opt-out also applies if this guardian switches to another role.
    return {
        "school_data_enabled": school_enabled,
        "personal_data_enabled": not opted_out,
        "effective_data_enabled": school_enabled and not opted_out,
        "can_manage_school": role == "admin",
        "can_manage_personal": role == "guardian",
        "revision": revision,
    }


async def save_preference(session, current_user, *, enabled, personal):
    org = current_user["organization_id"]
    # Serialize all preference changes for this school. Queries observe the new
    # revision together with the setting after commit, never a half-updated pair.
    row = (
        await session.execute(
            select(School)
            .where(
                School.organization_id == org,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "School not found")
    if personal:
        await session.execute(
            insert(GuardianChatPreference)
            .values(
                organization_id=org,
                guardian_user_id=current_user["user_id"],
                data_enabled=enabled,
            )
            .on_conflict_do_update(
                index_elements=["organization_id", "guardian_user_id"],
                set_={"data_enabled": enabled, "updated_at": utcnow()},
            )
        )
    else:
        row.ai_chat_data_enabled = enabled
    row.ai_chat_data_revision += 1
    await session.commit()
    return await access_state(
        session, current_user, "guardian" if personal else "admin"
    )
