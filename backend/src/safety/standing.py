from neo4j import Session

from safety.constraints import Constraint, ConstraintKind, ConstraintSet, Origin
from safety.queries import STANDING_CONSTRAINTS


def load_standing(session: Session, member_id: str) -> ConstraintSet:
    """Read what the member's record already constrains, before this request.

    Injuries are carried as constraints so the clinical path knows which to
    apply, not so they can be removed — `Constraint.waivable` is False for
    them, and `compose` refuses any directive that would drop one.

    Args:
        session: An open Neo4j session.
        member_id: The member whose record to read.

    Returns:
        Every standing constraint, each stamped `Origin.STANDING` so the trace
        can distinguish the chart from this request's instructions.

    Raises:
        ValueError: If the member does not exist. Silently returning an empty
            constraint set would produce a plan with no equipment limit and no
            injury filtering, which is the most dangerous possible failure.
    """
    record = session.run(STANDING_CONSTRAINTS, member_id=member_id).single()
    if record is None:
        raise ValueError(f"no member {member_id!r} in the graph")

    constraints = [
        Constraint(kind=ConstraintKind.EQUIPMENT, value=name, origin=Origin.STANDING)
        for name in sorted(record["equipment"])
    ]
    constraints += [
        Constraint(kind=ConstraintKind.EXCLUDED_EXERCISE, value=exercise_id, origin=Origin.STANDING)
        for exercise_id in sorted(record["disliked"])
    ]
    constraints += [
        Constraint(
            kind=ConstraintKind.INJURY,
            value=injury["id"],
            origin=Origin.STANDING,
            side=injury["side"],
        )
        for injury in sorted(record["injuries"], key=lambda row: row["id"])
    ]
    return ConstraintSet(member_id=member_id, constraints=tuple(constraints))
