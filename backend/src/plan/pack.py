from safety.filter import FilterResult
from safety.policy import Verdict

from plan.families import SLOT_ORDER, role_of
from plan.prescribe import MAX_SETS, MIN_SETS, SECTION_PLANS, half_up, prescribe
from plan.schemas import (
    Block,
    MovementFacts,
    Section,
    Shortfall,
    ShortfallKind,
    Slot,
    TimeBudget,
    WorkoutPlan,
)

# Roughly what one main-block exercise costs once solved, used only to decide
# how many to select before any of them are dosed. Wrong in either direction
# just means the set solver has more or less room to work with.
NOMINAL_MAIN_SECONDS = 260

MIN_MAIN_SLOTS = 3
MAX_MAIN_SLOTS = 8

# Warmup and cooldown are sized from the window, then capped together. Without
# the cap a twenty-minute session spends a third of itself on neck circles.
WARMUP_MINUTES_PER_ITEM = 15
COOLDOWN_MINUTES_PER_ITEM = 20
PREPARATORY_SHARE = 0.35

# Slots a main block is meant to cover. MOBILITY is absent on purpose: it is
# what warmup and cooldown are made of, and reporting it missing from the main
# block would be noise.
MAIN_SLOTS: tuple[Slot, ...] = tuple(slot for slot in SLOT_ORDER if slot is not Slot.MOBILITY)

PER_SIDE_NOTE = (
    "Unilateral exercises are prescribed for both sides. The catalog records a "
    "single side per unilateral row and no pairing, so no side is named."
)


def _clamp(value: int, low: int, high: int) -> int:
    """Hold a count inside an inclusive range."""
    return min(max(value, low), high)


def _facts_of(verdict: Verdict, facts: dict[str, MovementFacts]) -> MovementFacts | None:
    """The catalog facts for a verdict, or None when the graph lacks them."""
    return facts.get(verdict.exercise_id)


def _partition(
    result: FilterResult, facts: dict[str, MovementFacts]
) -> tuple[dict[Section, list[Verdict]], list[Shortfall]]:
    """Split the eligible pool into sections, keeping rank order.

    Args:
        result: The filter's verdicts for the whole catalog.
        facts: Movement facts by exercise id.

    Returns:
        Candidates per section, best first, and a shortfall for every exercise
        that could not be placed — dropped one at a time rather than failing
        the whole request.
    """
    pools: dict[Section, list[Verdict]] = {section: [] for section in Section}
    shortfalls: list[Shortfall] = []
    for verdict in result.eligible:
        movement = _facts_of(verdict, facts)
        role = role_of(movement.patterns) if movement else None
        if role is None:
            shortfalls.append(
                Shortfall(
                    kind=ShortfallKind.UNPLACEABLE_EXERCISE,
                    detail=f"{verdict.name} names no movement pattern this planner knows",
                )
            )
            continue
        pools[role.section].append(verdict)
    return pools, shortfalls


def _fixed_blocks(
    verdicts: list[Verdict], section: Section, facts: dict[str, MovementFacts]
) -> list[Block]:
    """Dose warmup or cooldown, whose set counts are not solved."""
    plan = SECTION_PLANS[section]
    blocks = []
    for verdict in verdicts:
        movement = facts[verdict.exercise_id]
        role = role_of(movement.patterns)
        blocks.append(
            Block(
                exercise_id=verdict.exercise_id,
                name=verdict.name,
                section=section,
                slot=role.slot,
                modality=role.modality,
                prescription=prescribe(movement, role, plan.sets),
                order=0,
                penalty=verdict.penalty,
                fit=verdict.fit,
                headline=verdict.headline,
            )
        )
    return blocks


def _cost(blocks: list[Block]) -> int:
    """Wall-clock seconds a set of blocks occupies."""
    return sum(block.prescription.total_seconds for block in blocks)


def _trim_preparatory(
    warmup: list[Block], cooldown: list[Block], window: int
) -> tuple[list[Block], list[Block], list[str]]:
    """Cap warmup and cooldown together, trimming the longer one first.

    Sized from the window they would otherwise crowd out the main work in a
    short session, where two mobility drills and two stretches can outweigh
    the training.

    Args:
        warmup: Warmup blocks, best first.
        cooldown: Cooldown blocks, best first.
        window: The whole requested session, in seconds.

    Returns:
        The kept blocks and the names dropped, for reporting.
    """
    cap = int(window * PREPARATORY_SHARE)
    dropped: list[str] = []
    while _cost(warmup) + _cost(cooldown) > cap:
        longer = warmup if _cost(warmup) >= _cost(cooldown) else cooldown
        if len(longer) <= 1:
            other = cooldown if longer is warmup else warmup
            if len(other) <= 1:
                break
            longer = other
        dropped.append(longer.pop().name)
    return warmup, cooldown, dropped


def _slot_order(candidates: list[Verdict], facts: dict[str, MovementFacts]) -> list[Slot]:
    """Deal order for the main block's slots, derived from the member.

    Slots holding the best goal-serving work come first, so a member training
    for lower-body strength gets a lower-body movement before an accessory
    one, without an authored preference that would be wrong for the next
    member.
    """
    by_slot: dict[Slot, list[Verdict]] = {}
    for verdict in candidates:
        slot = role_of(facts[verdict.exercise_id].patterns).slot
        by_slot.setdefault(slot, []).append(verdict)
    return sorted(
        by_slot,
        key=lambda slot: (-max(v.fit for v in by_slot[slot]), by_slot[slot][0].sort_key),
    )


def _select_main(
    candidates: list[Verdict], facts: dict[str, MovementFacts], count: int
) -> tuple[list[Verdict], Verdict | None]:
    """Choose the main block: one goal anchor, then round-robin across slots.

    Pure rank alone is not enough. The sample member's only goal-serving
    exercises are also her only cautioned ones, so they rank last of seventeen
    and a short session excludes every one of them — a shoulder-and-core plan
    for someone whose two priority-one goals are both lower-body. The anchor is
    one authored rule against that, and it is recorded on the block rather than
    hidden in a weight.

    Args:
        candidates: Eligible main-block verdicts, best first.
        facts: Movement facts by exercise id.
        count: How many to select.

    Returns:
        The selection in rank order, and the anchor when one was promoted
        ahead of its rank.
    """
    if not candidates or count <= 0:
        return [], None

    chosen: list[Verdict] = []
    promoted: Verdict | None = None
    best_fit = max(verdict.fit for verdict in candidates)
    if best_fit > 0:
        # Best goal fit first, ties broken by the safety rank as everywhere else.
        anchor = min((v for v in candidates if v.fit == best_fit), key=lambda v: v.sort_key)
        chosen.append(anchor)
        # Only a promotion if rank alone would not have reached it first.
        promoted = anchor if anchor is not candidates[0] else None

    remaining = [v for v in candidates if v not in chosen]
    by_slot: dict[Slot, list[Verdict]] = {}
    for verdict in remaining:
        by_slot.setdefault(role_of(facts[verdict.exercise_id].patterns).slot, []).append(verdict)

    order = _slot_order(remaining, facts) if remaining else []
    while len(chosen) < count and any(by_slot.values()):
        for slot in order:
            if len(chosen) >= count:
                break
            if by_slot.get(slot):
                chosen.append(by_slot[slot].pop(0))

    chosen.sort(key=lambda v: v.sort_key)
    return chosen, promoted


def _dose_main(
    chosen: list[Verdict], facts: dict[str, MovementFacts], budget: int, anchor: Verdict | None
) -> list[Block]:
    """Fit the selected main exercises into their budget.

    Solves the largest uniform set count that fits, dropping the lowest-ranked
    exercise if even one set each overflows, then tops up one set at a time in
    rank order. Topping up in rank order means the cautioned exercises receive
    the least volume, which is the direction a clinician would choose.

    Args:
        chosen: Selected verdicts, best first.
        facts: Movement facts by exercise id.
        budget: Seconds available for the main block.
        anchor: The goal-anchored verdict, if any.

    Returns:
        The dosed blocks, best first.
    """
    working = list(chosen)
    while working:
        for sets in range(MAX_SETS, MIN_SETS - 1, -1):
            blocks = [_main_block(v, facts, sets, anchor) for v in working]
            if _cost(blocks) <= budget:
                return _top_up(blocks, working, facts, budget, anchor)
        working.pop()
    return []


def _main_block(
    verdict: Verdict, facts: dict[str, MovementFacts], sets: int, anchor: Verdict | None
) -> Block:
    """One dosed main-block exercise."""
    movement = facts[verdict.exercise_id]
    role = role_of(movement.patterns)
    return Block(
        exercise_id=verdict.exercise_id,
        name=verdict.name,
        section=Section.MAIN,
        slot=role.slot,
        modality=role.modality,
        prescription=prescribe(movement, role, sets),
        order=0,
        penalty=verdict.penalty,
        fit=verdict.fit,
        headline=verdict.headline,
        anchored=anchor is not None and verdict.exercise_id == anchor.exercise_id,
    )


def _top_up(
    blocks: list[Block],
    chosen: list[Verdict],
    facts: dict[str, MovementFacts],
    budget: int,
    anchor: Verdict | None,
) -> list[Block]:
    """Spend leftover budget one set at a time, cycling best-ranked first.

    One pass per round rather than maxing each exercise before moving on:
    depth-first spends the whole surplus on whichever movement happens to sort
    first, which put eight minutes of side plank in a fifty-minute session.
    Cycling in rank order still gives the cleanest exercises the extra volume
    and the cautioned ones the least, which is the direction a clinician would
    choose — it just spreads it.
    """
    result = list(blocks)
    added = True
    while added:
        added = False
        for index, verdict in enumerate(chosen):
            if result[index].prescription.sets >= MAX_SETS:
                continue
            candidate = _main_block(verdict, facts, result[index].prescription.sets + 1, anchor)
            trial = result[:index] + [candidate] + result[index + 1 :]
            if _cost(trial) <= budget:
                result = trial
                added = True
    return result


def _sequence(blocks: list[Block]) -> list[Block]:
    """Order a section for performance rather than for safety.

    `Verdict.sort_key` ranks by risk, which is the right way to *choose* and
    the wrong way to *sequence* — followed literally it schedules single-arm
    tricep extensions before the heaviest press. Slot order puts compounds
    first, and within a slot the safety rank still decides, so a cautioned
    movement is performed after a clean one of the same kind. Warmup and
    cooldown are all one slot, so they keep rank order throughout.

    Selection has already happened. Nothing here changes which exercises are
    in the plan, only the order they are performed in.
    """
    ordered = sorted(blocks, key=lambda b: (SLOT_ORDER.index(b.slot), b.penalty, -b.fit, b.name))
    return [block.model_copy(update={"order": index}) for index, block in enumerate(ordered)]


def _shortfalls(
    pools: dict[Section, list[Verdict]],
    blocks: list[Block],
    budget: TimeBudget,
    result: FilterResult,
    trimmed: list[str],
    facts_by_id: dict[str, MovementFacts],
) -> list[Shortfall]:
    """Everything the request asked for that the plan could not supply."""
    found: list[Shortfall] = []
    cause = result.costliest_constraint

    for section in Section:
        scheduled = [b for b in blocks if b.section is section]
        if not scheduled:
            found.append(
                Shortfall(
                    kind=ShortfallKind.EMPTY_SECTION,
                    detail=f"no eligible exercise belongs in the {section.value}",
                    section=section,
                    cause=cause,
                )
            )
    if trimmed:
        found.append(
            Shortfall(
                kind=ShortfallKind.SECTION_TRIMMED,
                detail=(
                    f"warmup and cooldown were capped at "
                    f"{int(PREPARATORY_SHARE * 100)}% of the session, dropping "
                    f"{', '.join(trimmed)}"
                ),
            )
        )

    main_scheduled = sum(b.prescription.total_seconds for b in blocks if b.section is Section.MAIN)
    gap = budget.main_seconds - main_scheduled
    if gap > SECTION_PLANS[Section.MAIN].rest_seconds:
        found.append(
            Shortfall(
                kind=ShortfallKind.SECTION_UNDERFILLED,
                detail=(
                    f"the eligible pool ran out {gap} seconds short of the main block's "
                    f"share of the session"
                ),
                section=Section.MAIN,
                seconds=gap,
                cause=cause,
            )
        )

    # Against the eligible pool, not the schedule. A slot the session had no
    # room for is a short session; a slot nothing in the catalog can fill for
    # this member is a constraint, and only the second is worth reporting.
    coverable = {
        role_of(facts_by_id[verdict.exercise_id].patterns).slot
        for verdict in pools[Section.MAIN]
    }
    for slot in MAIN_SLOTS:
        if slot not in coverable:
            found.append(
                Shortfall(
                    kind=ShortfallKind.SLOT_ABSENT,
                    detail=f"nothing eligible covers {slot.value.replace('_', ' ')}",
                    slot=slot,
                    cause=cause,
                )
            )

    if blocks and not any(block.fit > 0 for block in blocks):
        found.append(
            Shortfall(
                kind=ShortfallKind.NO_GOAL_SERVING_BLOCK,
                detail="no eligible exercise serves a stated goal",
                cause=cause,
            )
        )

    for block in blocks:
        target = SECTION_PLANS[block.section].work_target_seconds
        if block.prescription.work_seconds * 2 < target:
            found.append(
                Shortfall(
                    kind=ShortfallKind.PACE_IMPLAUSIBLE,
                    detail=(
                        f"{block.name} works for only "
                        f"{block.prescription.work_seconds}s against "
                        f"{block.prescription.rest_seconds}s of rest"
                    ),
                    section=block.section,
                    seconds=block.prescription.work_seconds,
                )
            )
    return found


def pack(result: FilterResult, facts: dict[str, MovementFacts], minutes: int) -> WorkoutPlan:
    """Build a timed session from the exercises the filter cleared.

    Deterministic throughout: the inputs are the ranked verdicts, the catalog
    facts and the authored tables, so two runs over the same graph produce the
    same plan. Nothing here judges safety — every candidate has already been
    cleared, and the ranking that cleared it decides who is chosen.

    Args:
        result: The filter's verdicts for the whole catalog.
        facts: Movement facts by exercise id, from `plan.queries`.
        minutes: The requested session length.

    Returns:
        The session, the time arithmetic, and every gap between the two.
    """
    window = minutes * 60
    pools, shortfalls = _partition(result, facts)

    warmup = _fixed_blocks(
        pools[Section.WARMUP][: _clamp(half_up(minutes / WARMUP_MINUTES_PER_ITEM), 2, 5)],
        Section.WARMUP,
        facts,
    )
    cooldown = _fixed_blocks(
        pools[Section.COOLDOWN][: _clamp(half_up(minutes / COOLDOWN_MINUTES_PER_ITEM), 2, 4)],
        Section.COOLDOWN,
        facts,
    )
    warmup, cooldown, trimmed = _trim_preparatory(warmup, cooldown, window)

    main_budget = max(0, window - _cost(warmup) - _cost(cooldown))
    slots = _clamp(main_budget // NOMINAL_MAIN_SECONDS, MIN_MAIN_SLOTS, MAX_MAIN_SLOTS)
    chosen, anchor = _select_main(pools[Section.MAIN], facts, slots)
    main = _dose_main(chosen, facts, main_budget, anchor)

    blocks = _sequence(warmup) + _sequence(main) + _sequence(cooldown)
    budget = TimeBudget(
        requested_seconds=window,
        warmup_seconds=_cost(warmup),
        main_seconds=main_budget,
        cooldown_seconds=_cost(cooldown),
        scheduled_seconds=_cost(blocks),
    )
    shortfalls += _shortfalls(pools, blocks, budget, result, trimmed, facts)

    notes = (PER_SIDE_NOTE,) if any(b.prescription.per_side for b in blocks) else ()
    return WorkoutPlan(
        member_id=result.composition.applied.member_id,
        budget=budget,
        blocks=tuple(blocks),
        shortfalls=tuple(shortfalls),
        notes=notes,
        eligible_count=len(result.eligible),
        attribution=result.attribution,
    )
