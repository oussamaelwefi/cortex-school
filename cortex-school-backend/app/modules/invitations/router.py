import uuid

from fastapi import Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import Permission, get_current_user, require_permission
from core.db import db_session
from core.router import APIRouter
from modules.invitations.models import Invitation, InvitationSendStatus
from modules.invitations.schemas import (
    InvitationCreateRequest,
    InvitationResponse,
    InvitationUploadResponse,
)
from modules.invitations.services import (
    InvitationCsvError,
    _ensure_same_organization,
    create_invitations_from_csv,
    get_invitation,
    list_invitations,
    mark_invitation_enqueue_failed,
    should_enqueue_invitation,
)
from modules.invitations.tasks import enqueue_invitation_task

router = APIRouter(
    prefix="/invitations",
    tags=["Invitations"],
    dependencies=[Depends(require_permission(Permission.SCHOOL_MANAGE))],
)


@router.post(
    "/",
    response_model=InvitationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_invitation(
    payload: InvitationCreateRequest,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    organization_id = current_user.get("organization_id")
    if not organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authenticated user must belong to an organization",
        )

    email = str(payload.email).strip().lower()
    invitation = await session.scalar(
        select(Invitation).where(
            Invitation.organization_id == organization_id,
            Invitation.email == email,
        )
    )
    if invitation is not None:
        if invitation.role_slug != payload.role_slug:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An invitation already exists for this email with a different role",
            )
        if not should_enqueue_invitation(invitation):
            return invitation
        invitation.first_name = payload.first_name
        invitation.last_name = payload.last_name
        invitation.send_status = InvitationSendStatus.PENDING
        invitation.celery_task_id = None
        invitation.workos_invitation_id = None
        invitation.workos_state = None
        invitation.error_message = None
        invitation.expires_at = None
        invitation.sent_at = None
    else:
        invitation = Invitation(
            organization_id=organization_id,
            created_by_user_id=current_user.get("user_id"),
            email=email,
            first_name=payload.first_name,
            last_name=payload.last_name,
            role_slug=payload.role_slug,
            send_status=InvitationSendStatus.PENDING,
        )
        session.add(invitation)

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An invitation already exists for this email",
        ) from exc
    await session.refresh(invitation)
    try:
        return await enqueue_invitation_task(session, invitation)
    except Exception as exc:
        await mark_invitation_enqueue_failed(session, invitation, str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not enqueue invitation",
        ) from exc


@router.post(
    "/upload/",
    response_model=InvitationUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_invitations(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    organization_id = current_user.get("organization_id")
    if not organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authenticated user must belong to an organization",
        )

    is_csv_upload = file.content_type in {"text/csv", "application/vnd.ms-excel"}
    is_csv_name = bool(file.filename and file.filename.lower().endswith(".csv"))
    if not is_csv_upload and not is_csv_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload a CSV file",
        )

    try:
        csv_content = (await file.read()).decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CSV must be UTF-8 encoded",
        ) from exc

    try:
        upload_result = await create_invitations_from_csv(
            session,
            csv_content=csv_content,
            organization_id=organization_id,
            created_by_user_id=current_user.get("user_id"),
        )
    except InvitationCsvError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    queued_count = 0
    failed_count = 0
    skipped_count = 0
    for invitation in upload_result.invitations:
        if not should_enqueue_invitation(invitation):
            skipped_count += 1
            continue
        try:
            await enqueue_invitation_task(session, invitation)
        except Exception:
            failed_count += 1
            continue
        queued_count += 1

    return InvitationUploadResponse(
        created_count=upload_result.created_count,
        updated_count=upload_result.updated_count,
        queued_count=queued_count,
        failed_count=failed_count,
        skipped_count=skipped_count,
        invitations=upload_result.invitations,
    )


@router.get("/", response_model=list[InvitationResponse])
async def get_invitations(
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    organization_id = current_user.get("organization_id")
    if not organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authenticated user must belong to an organization",
        )
    return await list_invitations(session, organization_id=organization_id)


@router.get("/{invitation_id}/", response_model=InvitationResponse)
async def get_invitation_status(
    invitation_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    try:
        invitation = await get_invitation(session, invitation_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    _ensure_same_organization(invitation.organization_id, current_user)
    return invitation


@router.post(
    "/{invitation_id}/retry/",
    response_model=InvitationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_invitation(
    invitation_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    try:
        invitation = await get_invitation(session, invitation_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    _ensure_same_organization(invitation.organization_id, current_user)

    if invitation.send_status in {
        InvitationSendStatus.QUEUED,
        InvitationSendStatus.PROCESSING,
    }:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Invitation is already queued or processing",
        )

    invitation.celery_task_id = None
    invitation.workos_invitation_id = None
    invitation.workos_state = None
    invitation.expires_at = None
    invitation.sent_at = None

    try:
        return await enqueue_invitation_task(session, invitation)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not enqueue invitation",
        ) from exc
