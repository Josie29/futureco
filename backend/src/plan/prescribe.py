import math

from pydantic import BaseModel, ConfigDict

from plan.schemas import FamilyRole, Modality, MovementFacts, Prescription, Section


class SectionPlan(BaseModel):
    """How one section is dosed, before the catalog's cadence is applied."""

    model_config = ConfigDict(frozen=True)

    sets: int
    """Sets for warmup and cooldown, which are fixed. The main block solves
    its own, so this is only its starting point."""

    work_target_seconds: int
    """Roughly how long one set should take. Divided by the exercise's own
    seconds-per-rep to get a rep count."""

    rest_seconds: int
    hold_seconds: int
    """Prescribed instead of reps when the exercise is held for time."""


# Authored, and deliberately coarse. A warmup set is short and barely rested; a
# main set is long and fully rested; a cooldown hold is long and barely rested.
# Three rows beat fifty judgement calls, and a reviewer can check three rows.
SECTION_PLANS: dict[Section, SectionPlan] = {
    Section.WARMUP: SectionPlan(
        sets=1, work_target_seconds=40, rest_seconds=15, hold_seconds=30
    ),
    Section.MAIN: SectionPlan(sets=2, work_target_seconds=45, rest_seconds=60, hold_seconds=40),
    Section.COOLDOWN: SectionPlan(
        sets=2, work_target_seconds=45, rest_seconds=20, hold_seconds=45
    ),
}

# What a sane set looks like for each way of counting. These bound the division
# below, and they bind often — see `reps_clamped`.
REP_RANGES: dict[Modality, tuple[int, int]] = {
    Modality.STRENGTH: (6, 15),
    Modality.CONDITIONING: (20, 120),
    Modality.MOBILITY: (5, 12),
}

MIN_SETS = 1
MAX_SETS = 4
"""Above four sets of one movement a session stops being a session and starts
being a specialisation. The solver caps here rather than padding a long
window."""


def half_up(value: float) -> int:
    """Round to the nearest integer, halves going up.

    Python's `round` is banker's rounding: `round(4.5)` is 4 while
    `round(13.5)` is 14. Two catalog cadences land exactly on those halves
    (10.0 and 3.33 seconds against a 45-second target), so the built-in would
    apply two different rules to the same arithmetic.
    """
    return math.floor(value + 0.5)


def prescribe(facts: MovementFacts, role: FamilyRole, sets: int) -> Prescription:
    """Dose one exercise for one section.

    Reps come from dividing the section's work target by the exercise's own
    seconds-per-rep, then clamping to the modality's range. The clamp is not a
    rare correction — it decides 21 of the catalog's 42 rep-based rows, because
    a 45-second target against a fast cadence asks for more reps than anyone
    performs. So `estimated_rep_seconds` sets each set's *duration* and the
    range sets the reps; `reps_clamped` records which one decided.

    Args:
        facts: The catalog fields for this exercise.
        role: Its section and modality, from `families.role_of`.
        sets: How many sets to prescribe, solved by the packer for the main
            block and taken from `SECTION_PLANS` elsewhere.

    Returns:
        The dose, with whole-second timings so block arithmetic stays exact.
    """
    plan = SECTION_PLANS[role.section]
    multiplier = 2 if facts.per_side else 1

    if facts.is_held:
        return Prescription(
            sets=sets,
            reps=None,
            hold_seconds=plan.hold_seconds,
            rest_seconds=plan.rest_seconds,
            per_side=facts.per_side,
            work_seconds=plan.hold_seconds * multiplier,
            reps_clamped=False,
        )

    low, high = REP_RANGES[role.modality]
    wanted = half_up(plan.work_target_seconds / facts.rep_seconds)
    reps = min(max(wanted, low), high)
    return Prescription(
        sets=sets,
        reps=reps,
        hold_seconds=None,
        rest_seconds=plan.rest_seconds,
        per_side=facts.per_side,
        work_seconds=half_up(reps * facts.rep_seconds) * multiplier,
        reps_clamped=reps != wanted,
    )
