from fastapi import APIRouter, HTTPException, status

router = APIRouter(tags=["plans"])

# Agentic migration: the deterministic generator (one-shot extraction ->
# plan.pipeline -> pack) has been removed and is being rebuilt as a Pydantic AI
# planning agent over the same graphs. The routes stay mounted so the console
# gets an honest 501 rather than a 404 that reads as a wrong URL. The kept
# deterministic walls — resolve/, safety/, plan/schemas.py, plan/queries.py —
# are the tool and validator bodies of the replacement.

_DETAIL = "Plan generation is being rebuilt as a planning agent; not available on this branch."


@router.post("/members/{member_id}/plans")
def create_plan(member_id: str) -> None:
    """Generate a workout plan. Disabled during the agentic migration.

    Raises:
        HTTPException: Always, with 501, until the planning agent lands.
    """
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, _DETAIL)


@router.post("/members/{member_id}/plans/{run_id}/adjust")
def adjust_plan(member_id: str, run_id: str) -> None:
    """Refine an existing plan. Disabled during the agentic migration.

    Raises:
        HTTPException: Always, with 501, until the planning agent lands.
    """
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, _DETAIL)


@router.get("/members/{member_id}/eligibility")
def get_eligibility(member_id: str) -> None:
    """Report the member's eligible exercise set. Disabled during the agentic migration.

    Raises:
        HTTPException: Always, with 501, until the safety envelope is exposed
            through the agent's tool layer.
    """
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, _DETAIL)
