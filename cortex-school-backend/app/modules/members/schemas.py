from core.pydantic import CustomBaseModel


class MemberSummaryResponse(CustomBaseModel):
    id: str
    name: str
    email: str


class SchoolMemberResponse(MemberSummaryResponse):
    membership_id: str
    roles: list[str]
    status: str
