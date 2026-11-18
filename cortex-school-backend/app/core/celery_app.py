from celery import Celery

from core.config import settings


celery_app = Celery(
    "cortex_school",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["modules.invitations.tasks", "modules.reminders.tasks", "modules.onboarding.tasks"],
)

celery_app.conf.update(
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    beat_schedule={
        "recover-school-provisioning": {
            "task": "onboarding.recover_provisioning",
            "schedule": 15.0,
            "options": {"expires": 15},
        },
        "deliver-approved-reminders": {
            "task": "reminders.deliver_approved",
            "schedule": 15.0,
            "options": {"expires": 15},
        },
    },
)
