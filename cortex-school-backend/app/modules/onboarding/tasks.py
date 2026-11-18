import asyncio
import logging
import uuid

from sqlalchemy import select

from core.celery_app import celery_app
from core.db import SessionLocal, close_db_connections
from modules.onboarding.models import SchoolRequest, SchoolRequestStatus
from modules.onboarding.services import process_school_request


logger = logging.getLogger(__name__)


async def _process_and_close(request_id: uuid.UUID):
    try:
        return await process_school_request(request_id)
    finally:
        await close_db_connections()


@celery_app.task(name="onboarding.provision_school", acks_late=True, reject_on_worker_lost=True)
def provision_school_task(request_id: str):
    return asyncio.run(_process_and_close(uuid.UUID(request_id)))


def enqueue_school_provisioning(request_id: uuid.UUID):
    try:
        provision_school_task.apply_async(args=[str(request_id)], retry=False)
    except Exception:
        # Approval is already durable. Beat recovers broker handoff failures.
        logger.warning("School provisioning will be recovered by scheduler request_id=%s", request_id)


async def drain_school_requests():
    try:
        async with SessionLocal() as session:
            request_ids = (await session.scalars(select(SchoolRequest.id).where(
                SchoolRequest.status == SchoolRequestStatus.PROVISIONING,
            ).order_by(SchoolRequest.reviewed_at).limit(20))).all()
        for request_id in request_ids:
            await process_school_request(request_id)
    finally:
        await close_db_connections()


@celery_app.task(name="onboarding.recover_provisioning")
def recover_school_provisioning_task():
    asyncio.run(drain_school_requests())
