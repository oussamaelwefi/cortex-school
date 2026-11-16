import uuid

from fastapi import Body, Depends, File, HTTPException, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import Permission, get_current_user, require_permission
from core.db import db_session
from core.router import APIRouter
from modules.reminders.policy import add_policy, delete_policy, list_policies, policy_passages
from modules.reminders.policy_pdf import (
    MAX_POLICY_PDF_BYTES,
    PDF_DOWNLOAD_RESPONSES,
    PolicyPDFError,
    pdf_policy_passages,
    pdf_policy_title,
    policy_pdf_download,
)
from modules.reminders.schemas import (
    ReminderApproval,
    ReminderPreparation,
    ReminderReviewResponse,
    SchoolPolicyCreate,
    SchoolPolicyResponse,
)
from modules.reminders.services import approve_reminder, get_notice, prepare_reminder, review_response


router = APIRouter(tags=["School Reminders"], dependencies=[Depends(require_permission(Permission.SCHOOL_MANAGE))])


def school_id(user: dict = Depends(get_current_user)) -> str:
    organization_id = user.get("organization_id")
    if not organization_id:
        raise HTTPException(400, "An active school is required.")
    return organization_id


@router.get("/school-policies", response_model=list[SchoolPolicyResponse])
async def get_school_policies(
    organization_id: str = Depends(school_id), session: AsyncSession = Depends(db_session)
):
    return await list_policies(session, organization_id)


@router.post("/school-policies", response_model=SchoolPolicyResponse, status_code=201)
async def create_school_policy(
    payload: SchoolPolicyCreate,
    organization_id: str = Depends(school_id),
    session: AsyncSession = Depends(db_session),
):
    result = await add_policy(session, organization_id, payload.title, policy_passages(payload.text))
    if not result.passage_count:
        raise HTTPException(422, "Enter policy text beneath the section headings.")
    return result


@router.post("/school-policies/pdf", response_model=SchoolPolicyResponse, status_code=201)
async def upload_school_policy_pdf(
    file: UploadFile = File(...),
    organization_id: str = Depends(school_id),
    session: AsyncSession = Depends(db_session),
):
    data = await file.read(MAX_POLICY_PDF_BYTES + 1)
    if len(data) > MAX_POLICY_PDF_BYTES:
        raise HTTPException(413, "Choose a PDF of 10 MB or less.")
    try:
        passages = await run_in_threadpool(pdf_policy_passages, data)
    except PolicyPDFError as exc:
        raise HTTPException(422, str(exc)) from exc
    return await add_policy(session, organization_id, pdf_policy_title(file.filename), passages, pdf=data)


@router.get("/school-policies/{document_id}/pdf", response_class=Response, responses=PDF_DOWNLOAD_RESPONSES)
async def download_school_policy(
    document_id: uuid.UUID,
    organization_id: str = Depends(school_id),
    session: AsyncSession = Depends(db_session),
):
    return await policy_pdf_download(session, organization_id, document_id)


@router.delete("/school-policies/{document_id}", status_code=204, response_class=Response)
async def delete_school_policy(
    document_id: uuid.UUID,
    organization_id: str = Depends(school_id),
    session: AsyncSession = Depends(db_session),
):
    if not await delete_policy(session, organization_id, document_id):
        raise HTTPException(404, "School policy not found.")


@router.get("/student-updates/{update_id}/reminder", response_model=ReminderReviewResponse)
async def get_reminder(
    update_id: uuid.UUID,
    organization_id: str = Depends(school_id),
    session: AsyncSession = Depends(db_session),
):
    notice = await get_notice(session, organization_id, update_id)
    return await review_response(session, notice)


@router.post("/student-updates/{update_id}/reminder", response_model=ReminderReviewResponse)
async def create_reminder(
    update_id: uuid.UUID,
    payload: ReminderPreparation = Body(default_factory=ReminderPreparation),
    organization_id: str = Depends(school_id),
    session: AsyncSession = Depends(db_session),
):
    return await prepare_reminder(session, organization_id, update_id, payload.message)


@router.post("/reminder-proposals/{proposal_id}/approve", response_model=ReminderReviewResponse)
async def approve_reminder_proposal(
    proposal_id: uuid.UUID,
    payload: ReminderApproval,
    organization_id: str = Depends(school_id),
    session: AsyncSession = Depends(db_session),
    user: dict = Depends(get_current_user),
):
    return await approve_reminder(
        session, organization_id, proposal_id, user["user_id"], payload.message,
        include_policy_sources=payload.include_policy_sources,
    )
