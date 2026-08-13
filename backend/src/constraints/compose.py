from constraints.models import ConstraintSet


def compose(clinical: ConstraintSet, declared: ConstraintSet) -> ConstraintSet:
    """The set eligibility and validation judge against: clinical, then coach.

    The monotone floor is structural rather than checked: `declared` never
    holds clinical constraints (only the declaration tool writes it, stamping
    coach origin) and compose drops nothing, so no declaration can weaken the
    clinical set.

    Args:
        clinical: The chart-derived constraints, evidence attached.
        declared: The coach-declared set in force.

    Returns:
        The composed set, clinical constraints first.
    """
    return ConstraintSet(constraints=(*clinical.constraints, *declared.constraints))
