from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status

from api import members as read
from api.deps import GraphSession

router = APIRouter(tags=["members"])

CoachId = Annotated[
    str,
    Header(
        alias="X-Coach-Id",
        description="The signed-in coach. Mock auth, but the check is real.",
    ),
]


def _authorize(session: GraphSession, coach_id: str, member_id: str) -> None:
    """Refuse a member this coach does not coach.

    404 rather than 403, for both an unknown member and one belonging to
    somebody else. A 403 confirms the member exists, which turns the member id
    space into something worth guessing at.

    Raises:
        HTTPException: 404 when the coach has no `coaches` edge to this member.
    """
    if not read.coaches_member(session, coach_id, member_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No member {member_id} on your roster.",
        )


@router.get("/coaches", summary="Coaches who can sign in")
def get_coaches(session: GraphSession) -> list[read.Coach]:
    """The sign-in list.

    Unauthenticated on purpose: it is the screen a coach reaches *before* they
    have an identity to send. It returns names and ids and nothing else, and no
    member data hangs off it.
    """
    return read.coaches(session)


@router.get("/members", summary="The signed-in coach's roster")
def get_roster(session: GraphSession, coach_id: CoachId) -> list[read.RosterEntry]:
    """Roster metadata for this coach's members.

    Roster-level only — a name, a last-session date, an adherence figure, and
    whether she needs attention. Never goals, injuries, or history: the roster
    renders for every member at once, and clinical detail belongs behind the
    per-member check.

    Args:
        session: An open Neo4j session.
        coach_id: The signed-in coach, from the session rather than the URL.

    Returns:
        Members needing attention first, then the rest, then the filler.
    """
    return read.roster(session, coach_id)


@router.get("/members/{member_id}", summary="Full context for one member")
def get_member(session: GraphSession, member_id: str, coach_id: CoachId) -> read.MemberView:
    """Everything the member page renders, assembled from KG2.

    Args:
        session: An open Neo4j session.
        member_id: Whose context to read.
        coach_id: The signed-in coach.

    Returns:
        The assembled view, including the derived churn reading and `as_of`.

    Raises:
        HTTPException: 404 when the member is not on this coach's roster, and
            when she is but the graph holds no context for her — the roster's
            synthetic filler. The console renders a designed empty state for
            the second rather than fabricating clinical detail.
    """
    _authorize(session, coach_id, member_id)
    view = read.member(session, member_id)
    if view is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No context loaded for {member_id}.",
        )
    return view


@router.get("/members/{member_id}/messages", summary="The coach-member thread")
def get_messages(
    session: GraphSession, member_id: str, coach_id: CoachId
) -> list[read.MemberMessage]:
    """Coach and member, oldest first.

    Distinct from the copilot thread by design: these are member context the
    copilot retrieves *over*, not turns in the coach's conversation with it.

    Args:
        session: An open Neo4j session.
        member_id: Whose thread to read.
        coach_id: The signed-in coach.

    Returns:
        Every message, with attachments rebuilt from their stored arrays.

    Raises:
        HTTPException: 404 when the member is not on this coach's roster.
    """
    _authorize(session, coach_id, member_id)
    return read.messages(session, member_id)
