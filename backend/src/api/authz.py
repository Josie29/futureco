from typing import Annotated

from fastapi import Header, HTTPException, status
from neo4j import Session

from api.members import coaches_member

CoachId = Annotated[
    str,
    Header(alias="X-Coach-Id", description="The coach making the request."),
]


def authorize(session: Session, coach_id: str, member_id: str) -> None:
    """Require a coaches edge between this coach and this member.

    Raises:
        HTTPException: 404, never 403 — a 403 confirms the member exists,
            which makes the id space worth enumerating.
    """
    if not coaches_member(session, coach_id, member_id):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"No member {member_id} on your roster."
        )
