import asyncio
from dataclasses import dataclass

from workos import AsyncWorkOSClient

from core.config import settings


@dataclass(frozen=True)
class MemberSummary:
    id: str
    name: str
    email: str


class MemberLookupUnavailable(RuntimeError):
    pass


async def list_school_members(organization_id: str | None) -> list[dict]:
    """WorkOS is the source of truth; invitation acceptance activates membership.

    Read active memberships directly instead of requiring a local registration
    record or an administrator's approval. Never create or reactivate membership
    here, so suspended users cannot regain access by opening the directory.
    """
    if not organization_id:
        raise MemberLookupUnavailable("School organization is required")
    if not settings.WORKOS_API_KEY:
        raise MemberLookupUnavailable("WorkOS is not configured")

    options = {
        "base_url": settings.WORKOS_API_BASE_URL,
        "timeout": 20,
        "max_retries": 0,
    }
    semaphore = asyncio.Semaphore(8)
    try:
        async with AsyncWorkOSClient(api_key=settings.WORKOS_API_KEY) as client:
            members = {}
            after = None
            seen_cursors = set()
            while True:
                page = await client.organization_membership.list_organization_memberships(
                    organization_id=organization_id,
                    statuses=["active"],
                    limit=100,
                    after=after,
                    request_options=options,
                )
                async def resolve(membership):
                    # Keep the organization boundary explicit even when a provider
                    # adapter returns records beyond the requested filters.
                    if membership.organization_id != organization_id or membership.status != "active":
                        return None
                    async with semaphore:
                        user = await client.user_management.get_user(
                            membership.user_id, request_options=options,
                        )
                    return {
                        "id": user.id,
                        "membership_id": membership.id,
                        "name": " ".join(filter(None, [user.first_name, user.last_name])) or user.email,
                        "email": user.email,
                        "roles": [role.slug for role in membership.roles],
                        "status": "active",
                    }
                for result in await asyncio.gather(*(resolve(m) for m in page.data)):
                    if result:
                        members[result["membership_id"]] = result
                after = page.list_metadata.after
                if not after:
                    break
                if after in seen_cursors:
                    raise MemberLookupUnavailable("Could not finish loading school members")
                seen_cursors.add(after)
            return sorted(members.values(), key=lambda m: (m["name"].casefold(), m["email"]))
    except MemberLookupUnavailable:
        raise
    except Exception as exc:
        raise MemberLookupUnavailable("Could not load school members") from exc


async def load_member_summaries(
    organization_id: str | None,
    user_ids: set[str],
    *,
    tolerate_errors: bool,
) -> dict[str, MemberSummary]:
    if not user_ids:
        return {}
    if not settings.WORKOS_API_KEY:
        if tolerate_errors:
            return {}
        raise MemberLookupUnavailable("WorkOS is not configured")

    request_options = {
        "base_url": settings.WORKOS_API_BASE_URL,
        "timeout": 20,
        "max_retries": 0,
    }
    semaphore = asyncio.Semaphore(8)

    async def load_one(client: AsyncWorkOSClient, user_id: str):
        async with semaphore:
            memberships = (
                await client.organization_membership.list_organization_memberships(
                    organization_id=organization_id,
                    user_id=user_id,
                    statuses=["active"],
                    limit=1,
                    request_options=request_options,
                )
            )
            if not memberships.data:
                return None
            user = await client.user_management.get_user(
                user_id,
                request_options=request_options,
            )
            name = " ".join(filter(None, [user.first_name, user.last_name])) or user.email
            return MemberSummary(id=user.id, name=name, email=user.email)

    try:
        async with AsyncWorkOSClient(api_key=settings.WORKOS_API_KEY) as client:
            results = await asyncio.gather(
                *(load_one(client, user_id) for user_id in sorted(user_ids)),
                return_exceptions=True,
            )
    except Exception as exc:
        if tolerate_errors:
            return {}
        raise MemberLookupUnavailable("Could not load school members") from exc

    summaries: dict[str, MemberSummary] = {}
    for result in results:
        if isinstance(result, Exception):
            if not tolerate_errors:
                raise MemberLookupUnavailable("Could not load school member") from result
            continue
        if result is not None:
            summaries[result.id] = result
    return summaries
