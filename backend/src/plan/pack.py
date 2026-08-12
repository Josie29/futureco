from safety.filter import FilterResult

from plan.families import SLOT_ORDER, role_of
from plan.prescribe import MAX_SETS, MIN_SETS, SECTION_PLANS, half_up, prescribe
from plan.why import reasons_for
from plan.schemas import (
    Block,
    Candidate,
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


def _partition(
    result: FilterResult, facts: dict[str, MovementFacts], focus: frozenset[str]
) -> tuple[dict[Section, list[Candidate]], list[Shortfall]]:
    """Bundle every cleared movement with what the packer needs to place it.

    The one place a `Candidate` is built, because it is the one place that has
    established the movement is placeable at all — everything downstream can
    then take `role` as given rather than re-deriving it and re-handling the
    None. Pools come out in `Candidate.key` order, which is the only order the
    packer has: the warmup and cooldown slices, the per-slot lists and the set
    solver all read it, and sorting once here means there is no second
    definition of "best first" to keep in step.

    Args:
        result: The filter's verdicts for the whole catalog.
        facts: Movement facts by exercise id.
        focus: Muscles the request asked to emphasise, already resolved.

    Returns:
        Candidates per section, best first, and a shortfall for every exercise
        that could not be placed — dropped one at a time rather than failing
        the whole request.
    """
    pools: dict[Section, list[Candidate]] = {section: [] for section in Section}
    shortfalls: list[Shortfall] = []
    for verdict in result.eligible:
        movement = facts.get(verdict.exercise_id)
        role = role_of(movement.patterns) if movement else None
        if movement is None or role is None:
            shortfalls.append(
                Shortfall(
                    kind=ShortfallKind.UNPLACEABLE_EXERCISE,
                    detail=f"{verdict.name} names no movement pattern this planner knows",
                )
            )
            continue
        pools[role.section].append(
            Candidate(
                verdict=verdict,
                movement=movement,
                role=role,
                emphasised=tuple(sorted(focus & set(movement.muscles))),
            )
        )
    for pool in pools.values():
        pool.sort(key=lambda candidate: candidate.key)
    return pools, shortfalls


def _fixed_blocks(candidates: list[Candidate], section: Section) -> list[Block]:
    """Dose warmup or cooldown, whose set counts are not solved."""
    plan = SECTION_PLANS[section]
    return [_block(candidate, section, plan.sets) for candidate in candidates]


def _block(candidate: Candidate, section: Section, sets: int, anchored: bool = False) -> Block:
    """One dosed exercise, wherever it sits in the session."""
    return Block(
        exercise_id=candidate.exercise_id,
        name=candidate.verdict.name,
        section=section,
        slot=candidate.role.slot,
        modality=candidate.role.modality,
        prescription=prescribe(candidate.movement, candidate.role, sets),
        order=0,
        penalty=candidate.verdict.penalty,
        fit=candidate.verdict.fit,
        headline=candidate.verdict.headline,
        anchored=anchored,
        reasons=reasons_for(
            candidate.verdict, candidate.movement, candidate.role, candidate.emphasised
        ),
        **_catalog_fields(candidate.movement),
    )


def _catalog_fields(movement: MovementFacts) -> dict[str, tuple[str, ...]]:
    """Catalog facts a block carries so the wire layer stays a projection.

    Denormalised onto the block for the same reason `name` and `headline`
    already are: a consumer rendering one movement should not have to hold the
    whole catalog to do it.
    """
    return {
        "muscles": movement.muscles,
        "equipment": movement.equipment,
        "goal_muscles": tuple(sorted({service.muscle for service in movement.goals})),
    }


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


def _by_slot(candidates: list[Candidate]) -> dict[Slot, list[Candidate]]:
    """Group candidates by slot, keeping the order they arrived in."""
    grouped: dict[Slot, list[Candidate]] = {}
    for candidate in candidates:
        grouped.setdefault(candidate.role.slot, []).append(candidate)
    return grouped


def _slot_order(by_slot: dict[Slot, list[Candidate]]) -> list[Slot]:
    """Deal order for the main block's slots, derived from the member.

    Slots that can serve the emphasis come first, then those holding the best
    goal-serving work, so a member training for lower-body strength gets a
    lower-body movement before an accessory one, without an authored preference
    that would be wrong for the next member.

    The emphasis term is separate from `Candidate.key` and not redundant with
    it: the round-robin deals one exercise per slot, so a chest movement only
    makes a three-slot main block if the slot holding it is dealt early.
    Ordering within a slot cannot reach that.
    """
    return sorted(
        by_slot,
        key=lambda slot: (
            -max(len(c.emphasised) for c in by_slot[slot]),
            -max(c.verdict.fit for c in by_slot[slot]),
            by_slot[slot][0].key,
        ),
    )


def _select_main(
    candidates: list[Candidate], count: int
) -> tuple[list[Candidate], Candidate | None]:
    """Choose the main block: one goal anchor, then round-robin across slots.

    Pure rank alone is not enough. The sample member's only goal-serving
    exercises are also her only cautioned ones, so they rank last of seventeen
    and a short session excludes every one of them — a shoulder-and-core plan
    for someone whose two priority-one goals are both lower-body. The anchor is
    one authored rule against that, and it is recorded on the block rather than
    hidden in a weight.

    The emphasis reaches this through `candidates`, which arrive in
    `Candidate.key` order, and through the slot deal order. It gets no anchor
    of its own: the deal order already seats it first among the round-robin
    picks, and a second authored exception would spend both free slots of a
    three-slot session on exceptions.

    Args:
        candidates: Eligible main-block candidates, best first by `key`.
        count: How many to select.

    Returns:
        The selection in `key` order, and the anchor when one was promoted
        ahead of its rank.
    """
    if not candidates or count <= 0:
        return [], None

    chosen: list[Candidate] = []
    promoted: Candidate | None = None
    best_fit = max(candidate.verdict.fit for candidate in candidates)
    if best_fit > 0:
        # Best goal fit first, ties broken by the safety rank as everywhere else.
        anchor = min(
            (c for c in candidates if c.verdict.fit == best_fit),
            key=lambda c: c.verdict.sort_key,
        )
        chosen.append(anchor)
        # Only a promotion if the pick order would not have reached it first.
        promoted = anchor if anchor.exercise_id != candidates[0].exercise_id else None

    taken = {candidate.exercise_id for candidate in chosen}
    by_slot = _by_slot([c for c in candidates if c.exercise_id not in taken])

    order = _slot_order(by_slot)
    while len(chosen) < count and any(by_slot.values()):
        for slot in order:
            if len(chosen) >= count:
                break
            if by_slot.get(slot):
                chosen.append(by_slot[slot].pop(0))

    # Back into `key` order, which is what `_dose_main` drops from and `_top_up`
    # spends surplus sets in: the emphasised movement should be the last to lose
    # its place and the first to gain a set. `penalty` leads the key, so the
    # cautioned movements are still dropped first and dosed least whatever the
    # request emphasised.
    chosen.sort(key=lambda candidate: candidate.key)
    return chosen, promoted


def _dose_main(chosen: list[Candidate], budget: int, anchor: Candidate | None) -> list[Block]:
    """Fit the selected main exercises into their budget.

    Solves the largest uniform set count that fits, dropping the lowest-ranked
    exercise if even one set each overflows, then tops up one set at a time in
    rank order. Topping up in rank order means the cautioned exercises receive
    the least volume, which is the direction a clinician would choose.

    Args:
        chosen: Selected candidates, best first.
        budget: Seconds available for the main block.
        anchor: The goal-anchored candidate, if any.

    Returns:
        The dosed blocks, best first.
    """
    working = list(chosen)
    while working:
        for sets in range(MAX_SETS, MIN_SETS - 1, -1):
            blocks = [_main_block(candidate, sets, anchor) for candidate in working]
            if _cost(blocks) <= budget:
                return _top_up(blocks, working, budget, anchor)
        working.pop()
    return []


def _main_block(candidate: Candidate, sets: int, anchor: Candidate | None) -> Block:
    """One dosed main-block exercise, told whether it is the goal anchor."""
    anchored = anchor is not None and candidate.exercise_id == anchor.exercise_id
    return _block(candidate, Section.MAIN, sets, anchored)


def _top_up(
    blocks: list[Block],
    chosen: list[Candidate],
    budget: int,
    anchor: Candidate | None,
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
        for index, candidate in enumerate(chosen):
            if result[index].prescription.sets >= MAX_SETS:
                continue
            dosed = _main_block(candidate, result[index].prescription.sets + 1, anchor)
            trial = result[:index] + [dosed] + result[index + 1 :]
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
    pools: dict[Section, list[Candidate]],
    blocks: list[Block],
    budget: TimeBudget,
    result: FilterResult,
    trimmed: list[str],
    focus: frozenset[str],
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
    coverable = {candidate.role.slot for candidate in pools[Section.MAIN]}
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

    # Against the schedule rather than the eligible pool, which is the opposite
    # of the slot rule above: a coach who asked for chest work and did not get
    # it is owed that fact whether the cause was the filter or the window.
    scheduled_muscles = {muscle for block in blocks for muscle in block.muscles}
    for muscle in sorted(focus - scheduled_muscles):
        found.append(
            Shortfall(
                kind=ShortfallKind.FOCUS_UNSERVED,
                detail=f"nothing in the session trains {muscle}, which the request emphasised",
                muscle=muscle,
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


def pack(
    result: FilterResult,
    facts: dict[str, MovementFacts],
    minutes: int,
    focus: frozenset[str] = frozenset(),
) -> WorkoutPlan:
    """Build a timed session from the exercises the filter cleared.

    Deterministic throughout: the inputs are the ranked verdicts, the catalog
    facts and the authored tables, so two runs over the same graph produce the
    same plan. Nothing here judges safety — every candidate has already been
    cleared, and `Candidate.key` orders what survives without ever reordering
    across the filter's own penalty.

    Args:
        result: The filter's verdicts for the whole catalog.
        facts: Movement facts by exercise id, from `plan.queries`.
        minutes: The requested session length.
        focus: Muscles the request asked to emphasise, already resolved.

    Returns:
        The session, the time arithmetic, and every gap between the two.
    """
    window = minutes * 60
    pools, shortfalls = _partition(result, facts, focus)

    warmup = _fixed_blocks(
        pools[Section.WARMUP][: _clamp(half_up(minutes / WARMUP_MINUTES_PER_ITEM), 2, 5)],
        Section.WARMUP,
    )
    cooldown = _fixed_blocks(
        pools[Section.COOLDOWN][: _clamp(half_up(minutes / COOLDOWN_MINUTES_PER_ITEM), 2, 4)],
        Section.COOLDOWN,
    )
    warmup, cooldown, trimmed = _trim_preparatory(warmup, cooldown, window)

    main_budget = max(0, window - _cost(warmup) - _cost(cooldown))
    slots = _clamp(main_budget // NOMINAL_MAIN_SECONDS, MIN_MAIN_SLOTS, MAX_MAIN_SLOTS)
    chosen, anchor = _select_main(pools[Section.MAIN], slots)
    main = _dose_main(chosen, main_budget, anchor)

    blocks = _sequence(warmup) + _sequence(main) + _sequence(cooldown)
    budget = TimeBudget(
        requested_seconds=window,
        warmup_seconds=_cost(warmup),
        main_seconds=main_budget,
        cooldown_seconds=_cost(cooldown),
        scheduled_seconds=_cost(blocks),
    )
    shortfalls += _shortfalls(pools, blocks, budget, result, trimmed, focus)

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
