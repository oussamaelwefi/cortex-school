from core.db import SCHEMA_NAME, Base, TimestampMixin
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column


class GuardianChatPreference(Base, TimestampMixin):
    """School-scoped AI consent, separate from access to normal school screens."""

    organization_id: Mapped[str] = mapped_column(
        ForeignKey(f"{SCHEMA_NAME}.school.organization_id", ondelete="CASCADE"),
        primary_key=True,
    )
    guardian_user_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    data_enabled: Mapped[bool] = mapped_column(
        default=True,
        server_default="true",
        nullable=False,
    )
