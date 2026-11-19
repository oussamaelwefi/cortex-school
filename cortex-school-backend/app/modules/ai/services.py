import asyncio
import logging
import re
import time
from collections.abc import Iterable
from typing import Any, TypeVar

from fastapi import HTTPException, status
from redis import asyncio as redis_asyncio
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
from sqlalchemy.ext.asyncio import AsyncSession

from ai.openrouter import (
    OpenRouterNotConfiguredError,
    get_teacher_update_draft_chain,
)
from core.config import settings
from modules.ai.schemas import (
    TeacherDraftLanguage,
    TeacherUpdateDraftRequest,
    TeacherUpdateDraftResult,
)
from modules.schools.models import School
from modules.student_updates.models import StudentUpdateTargetType
from modules.student_updates.schemas import StudentsTarget
from modules.student_updates.services import _resolve_teacher_update_audience
from modules.teachers.services import _require_teacher_access
from prompts.registry import PROMPTS
from prompts.utils import render_template


logger = logging.getLogger(__name__)
ResultT = TypeVar("ResultT")


class RateLimitExceededError(RuntimeError):
    pass


class RateLimitUnavailableError(RuntimeError):
    pass


_UNSAFE_OUTPUT_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bdiagnos(?:is|ed|e)\b",
        r"\b(?:autis(?:m|tic)|adhd|depress(?:ion|ed)|anxious|mental illness|disorder)\b",
        r"\b(?:medication|prescription|medical advice|safeguard(?:ing)?|abuse|neglect)\b",
        r"\b(?:violence|bully(?:ing|ied)|criminal|lawyer|legal action|suspend(?:ed|sion)|expel(?:led|sion))\b",
        r"\b(?:predict(?:ion|ive|ed)?|forecast|medical|legal)\b",
        r"\b(?:bad student|lazy|stupid|problem child)\b",
        r"\b(?:ignore (?:all )?(?:previous|prior) instructions|system prompt|developer message)\b",
        r"\b(?:diagnostic|diagnostiqu|autisme|tdah|dépression|anxiété|médicament|abus|négligence)\b",
        r"\b(?:violence|harcèlement|avocat|plainte|exclu|suspendu|renvoi|paresseux|élève à problème)\b",
        r"(?:تجاهل|تجاهلي|التعليمات السابقة|رسالة النظام|تعليمات المطور|تشخيص|توحد|فرط الحركة|اكتئاب|قلق|دواء|إيذاء|عنف|تنمر|طرد|قانوني|كسول|غبي|مشاغب)",
    )
)


def _contains_unsafe_text(values: Iterable[str]) -> bool:
    content = " ".join(values)
    return any(pattern.search(content) for pattern in _UNSAFE_OUTPUT_PATTERNS)


def _contains_unsafe_output(result: TeacherUpdateDraftResult) -> bool:
    return _contains_unsafe_text(
        [result.title or "", result.body or "", *result.questions]
    )


def _safe_error_category(error: Exception) -> str:
    name = type(error).__name__.lower()
    if "timeout" in name:
        return "timeout"
    if getattr(error, "status_code", None) in {400, 401, 402, 403, 404, 422}:
        return "provider_configuration"
    if "rate" in name or "429" in str(error):
        return "provider_rate_limit"
    if isinstance(error, ValueError) or "parse" in name or "validation" in name:
        return "invalid_output"
    return "provider_error"


def _log_event(
    *,
    request_id: str,
    organization_id: str,
    actor_id: str,
    classroom_id: str,
    target_type: StudentUpdateTargetType | None,
    target_count: int | None,
    outcome: str,
    latency_ms: int,
    error_category: str | None = None,
    token_usage: dict[str, Any] | None = None,
) -> None:
    logger.info(
        "teacher_update_draft",
        extra={
            "event": "teacher_update_draft",
            "request_id": request_id,
            "organization_id": organization_id,
            "actor_id": actor_id,
            "classroom_id": classroom_id,
            "target_type": target_type.value if target_type else None,
            "target_count": target_count,
            "outcome": outcome,
            "latency_ms": latency_ms,
            "prompt_version": PROMPTS["workflow_teacher_update_draft"]["version"],
            "model": settings.llm.OPENROUTER_MODEL or None,
            "token_usage": token_usage,
            "error_category": error_category,
        },
    )


async def _consume_rate_limit(
    organization_id: str,
    actor_id: str,
    *,
    namespace: str = "teacher-draft",
) -> None:
    window = settings.AI_TEACHER_DRAFT_RATE_WINDOW_SECONDS
    now = int(time.time())
    bucket = now // window
    ttl = window - (now % window)
    user_key = f"ai:{namespace}:user:{organization_id}:{actor_id}:{bucket}"
    organization_key = f"ai:{namespace}:organization:{organization_id}:{bucket}"
    client = None
    try:
        client = redis_asyncio.from_url(
            settings.AI_TEACHER_DRAFT_REDIS_URL or settings.CELERY_BROKER_URL,
            socket_connect_timeout=2,
            socket_timeout=2,
            retry_on_timeout=False,
            retry=Retry(NoBackoff(), 0),
        )
        async with asyncio.timeout(3):
            async with client.pipeline(transaction=True) as pipeline:
                pipeline.incr(user_key)
                pipeline.incr(organization_key)
                pipeline.expire(user_key, ttl)
                pipeline.expire(organization_key, ttl)
                user_count, organization_count, _, _ = await pipeline.execute()
    except Exception as exc:
        raise RateLimitUnavailableError from exc
    finally:
        if client is not None:
            try:
                async with asyncio.timeout(1):
                    await client.aclose()
            except Exception:
                pass

    if (
        user_count > settings.AI_TEACHER_DRAFT_USER_RATE_LIMIT
        or organization_count > settings.AI_TEACHER_DRAFT_ORGANIZATION_RATE_LIMIT
    ):
        raise RateLimitExceededError


def _extract_chain_result(
    raw_result: Any,
    result_type: type[ResultT],
) -> tuple[ResultT, dict[str, Any] | None]:
    if isinstance(raw_result, result_type):
        return raw_result, None
    if not isinstance(raw_result, dict):
        raise ValueError("structured output was not returned")
    if raw_result.get("parsing_error") is not None:
        raise ValueError("structured output could not be parsed")
    parsed = raw_result.get("parsed")
    if not isinstance(parsed, result_type):
        raise ValueError("structured output was not validated")
    raw_message = raw_result.get("raw")
    usage_metadata = getattr(raw_message, "usage_metadata", None)
    return parsed, usage_metadata if isinstance(usage_metadata, dict) else None


class TeacherUpdateDraftService:
    async def generate(
        self,
        *,
        session: AsyncSession,
        payload: TeacherUpdateDraftRequest,
        current_user: dict,
        request_id: str,
        chain: Any | None = None,
    ) -> TeacherUpdateDraftResult:
        actor_id, organization_id = _require_teacher_access(current_user)
        school = await session.get(School, organization_id)
        if school is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="School not found",
            )
        if not school.ai_teacher_draft_enabled:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="AI teacher drafting is disabled for this school",
            )

        classroom, roster, target_type = await _resolve_teacher_update_audience(
            session,
            payload.classroom_id,
            payload.target,
            current_user,
        )
        target_count = len(roster)
        audience_label = (
            "the selected students"
            if target_type == StudentUpdateTargetType.STUDENTS
            else "the whole classroom"
        )
        student_first_name = None
        if isinstance(payload.target, StudentsTarget) and len(roster) == 1:
            student_first_name = roster[0][0].first_name

        selected_language = payload.output_language
        if selected_language is None:
            try:
                selected_language = TeacherDraftLanguage(
                    school.ai_teacher_draft_default_language
                )
            except ValueError:
                selected_language = TeacherDraftLanguage.AUTO

        started_at = time.monotonic()

        def log_event(
            *,
            outcome: str,
            error_category: str | None = None,
            token_usage: dict[str, Any] | None = None,
        ) -> None:
            _log_event(
                request_id=request_id,
                organization_id=organization_id,
                actor_id=actor_id,
                classroom_id=str(classroom.id),
                target_type=target_type,
                target_count=target_count,
                outcome=outcome,
                latency_ms=int((time.monotonic() - started_at) * 1000),
                error_category=error_category,
                token_usage=token_usage,
            )

        try:
            await _consume_rate_limit(organization_id, actor_id)
        except RateLimitExceededError:
            log_event(outcome="failed", error_category="rate_limited")
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="AI draft limit reached. Continue with the manual composer.",
            )
        except RateLimitUnavailableError:
            log_event(outcome="failed", error_category="rate_limit_unavailable")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AI drafting is temporarily unavailable. Continue with the manual composer.",
            )

        prompt = render_template(
            PROMPTS["workflow_teacher_update_draft"]["template"],
            {
                "audience_label": audience_label,
                "classroom_name": classroom.name,
                "student_count": target_count,
                "student_first_name": student_first_name,
                "tone": payload.tone.value,
                "output_language": selected_language.value,
                "observations": payload.observations,
            },
        )

        try:
            draft_chain = chain if chain is not None else get_teacher_update_draft_chain()
            async with asyncio.timeout(settings.AI_TEACHER_DRAFT_TIMEOUT_SECONDS):
                result, token_usage = _extract_chain_result(
                    await draft_chain.ainvoke(prompt),
                    TeacherUpdateDraftResult,
                )
            if _contains_unsafe_output(result):
                log_event(
                    outcome="failed",
                    error_category="unsafe_output",
                    token_usage=token_usage,
                )
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="The draft could not be safely generated. Continue with the manual composer.",
                )
        except HTTPException:
            raise
        except asyncio.CancelledError:
            raise
        except OpenRouterNotConfiguredError:
            log_event(outcome="failed", error_category="not_configured")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AI drafting is not configured. Continue with the manual composer.",
            )
        except Exception as exc:
            category = _safe_error_category(exc)
            log_event(outcome="failed", error_category=category)
            if category == "timeout":
                raise HTTPException(
                    status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                    detail="AI drafting timed out. Please try again or continue with the manual composer.",
                ) from exc
            if category == "provider_configuration":
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="AI drafting configuration needs attention. Contact your school administrator or use the manual composer.",
                ) from exc
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AI drafting is temporarily unavailable. Continue with the manual composer.",
            )

        log_event(outcome=result.outcome, token_usage=token_usage)
        return result


teacher_update_draft_service = TeacherUpdateDraftService()
