import pytest

from graph.driver import graph_session
from plan.families import SLOT_ORDER
from plan.pack import MAX_MAIN_SLOTS, pack
from plan.prescribe import MAX_SETS
from plan.queries import movement_facts
from plan.schemas import Section, ShortfallKind, Slot
from safety.constraints import compose
from safety.filter import run
from safety.standing import load_standing

MEMBER = "mbr_01HX9JORDAN"


@pytest.fixture(scope="module")
def session():
    """One Neo4j session for the whole module."""
    with graph_session() as open_session:
        yield open_session


@pytest.fixture(scope="module")
def result(session):
    """The sample member's verdicts under her standing constraints alone."""
    return run(session, compose(load_standing(session, MEMBER), ()))


@pytest.fixture(scope="module")
def facts(session):
    """Catalog facts for every exercise."""
    return movement_facts(session, MEMBER)


def kinds(plan, kind: ShortfallKind) -> list:
    """Every shortfall of one kind."""
    return [shortfall for shortfall in plan.shortfalls if shortfall.kind is kind]


class TestBaseline:
    """The sample member at her preferred session length."""

    def test_the_fifty_minute_plan_matches_the_measured_snapshot(self, result, facts) -> None:
        """Anchors every other test here.

        If the eligible pool, the family table, the prescription tables or the
        solver drift, this is what notices — and the numbers are the ones
        quoted in `decisions.md` and the README's worked example.
        """
        plan = pack(result, facts, 50)
        assert len(plan.section(Section.WARMUP)) == 3
        assert len(plan.section(Section.MAIN)) == 8
        assert len(plan.section(Section.COOLDOWN)) == 2
        assert plan.budget.scheduled_seconds == 2934
        assert plan.eligible_count == 17

    def test_no_section_is_empty(self, result, facts) -> None:
        """A session with no cooldown must not ship silently.

        Her cooldown pool is two exercises, so this is closer to failing than
        the seventeen-strong eligible count suggests.
        """
        plan = pack(result, facts, 50)
        for section in Section:
            assert plan.section(section), section

    @pytest.mark.parametrize("minutes", [20, 30, 45, 50, 60])
    def test_the_window_is_nearly_filled(self, result, facts, minutes: int) -> None:
        """A coach books fifty minutes and must not get thirty-five.

        The solver can always under-fill by refusing to add a set that would
        overflow; without a floor here that failure is invisible.
        """
        plan = pack(result, facts, minutes)
        assert plan.budget.fill_ratio >= 0.9, plan.budget

    def test_time_arithmetic_reconciles(self, result, facts) -> None:
        """Block times must sum to the reported total.

        The plan prints a per-block cost and a session total; if they disagree
        the coach cannot trust either.
        """
        plan = pack(result, facts, 50)
        assert sum(b.prescription.total_seconds for b in plan.blocks) == (
            plan.budget.scheduled_seconds
        )


class TestSafety:
    """What the packer must never do, whatever the window."""

    @pytest.mark.parametrize("minutes", [5, 20, 50, 90, 240])
    def test_no_excluded_verdict_is_ever_programmed(self, result, facts, minutes: int) -> None:
        """The whole safety argument.

        The packer reads `eligible`, so an excluded exercise reaching a plan
        would mean the filter's verdict was bypassed rather than overruled.
        """
        excluded = {v.exercise_id for v in result.verdicts if not v.eligible}
        plan = pack(result, facts, minutes)
        assert not {b.exercise_id for b in plan.blocks} & excluded

    def test_no_exercise_is_programmed_twice(self, result, facts) -> None:
        """Padding a long window by repeating movements is not volume.

        At 120 minutes the pool cannot fill the request, and repeating is the
        tempting way to hide that.
        """
        plan = pack(result, facts, 120)
        ids = [b.exercise_id for b in plan.blocks]
        assert len(ids) == len(set(ids))

    def test_sets_are_capped(self, result, facts) -> None:
        """Four sets is the ceiling however much time is left over."""
        plan = pack(result, facts, 240)
        assert all(b.prescription.sets <= MAX_SETS for b in plan.blocks)


class TestGoalAnchor:
    """One authored rule against a plan that serves no stated goal."""

    def test_a_short_session_still_serves_a_goal(self, result, facts) -> None:
        """By rank alone, her twenty-minute plan has no lower-body work at all.

        Her only goal-serving exercises are also her only cautioned ones, so
        they rank last of seventeen and every short cut excludes them — a
        shoulder-and-core session for a member whose two priority-one goals
        are both lower-body.
        """
        plan = pack(result, facts, 20)
        assert plan.serves_a_goal
        assert not kinds(plan, ShortfallKind.NO_GOAL_SERVING_BLOCK)

    def test_the_anchor_is_marked_and_keeps_its_caution(self, result, facts) -> None:
        """A promotion past the safety rank has to be visible.

        The anchored block is cautioned, so a coach reading the plan needs the
        clinician's words on it rather than an unexplained appearance near the
        top.
        """
        plan = pack(result, facts, 20)
        anchored = [b for b in plan.blocks if b.anchored]
        assert len(anchored) == 1
        assert anchored[0].fit > 0
        assert anchored[0].penalty > 0
        assert "front knee" in anchored[0].headline

    def test_the_anchor_never_overrules_exclusion(self, result, facts) -> None:
        """Goal fit promotes within the eligible pool and no further.

        The anchor is chosen from candidates the filter already cleared, so
        it cannot reach a contraindicated exercise however well it scores.
        """
        excluded = {v.exercise_id for v in result.verdicts if not v.eligible}
        for minutes in (10, 20, 50):
            plan = pack(result, facts, minutes)
            assert not {b.exercise_id for b in plan.blocks if b.anchored} & excluded


class TestSequencing:
    """The order blocks are performed in, which is not the order they were chosen."""

    def test_compounds_precede_accessories(self, result, facts) -> None:
        """Rank order alone schedules single-arm tricep work before the press.

        `sort_key` ranks by risk. Followed literally it is a safety ordering
        presented as a training one.
        """
        plan = pack(result, facts, 50)
        main = plan.section(Section.MAIN)
        slots = [SLOT_ORDER.index(b.slot) for b in main]
        assert slots == sorted(slots)
        assert main[-1].slot is Slot.ARMS

    def test_within_a_slot_the_safety_rank_still_decides(self, result, facts) -> None:
        """A cautioned movement is performed after a clean one of its kind.

        Sequencing must reorder across slots without discarding the ranking
        inside them, or the plan stops reflecting the filter at all.
        """
        plan = pack(result, facts, 50)
        for section in Section:
            blocks = plan.section(section)
            for slot in {b.slot for b in blocks}:
                ranks = [(b.penalty, -b.fit) for b in blocks if b.slot is slot]
                assert ranks == sorted(ranks), (section, slot)

    def test_order_is_contiguous_within_each_section(self, result, facts) -> None:
        """`order` is what the UI renders by; gaps or repeats scramble a plan."""
        plan = pack(result, facts, 50)
        for section in Section:
            orders = [b.order for b in plan.section(section)]
            assert orders == list(range(len(orders)))


class TestShortfalls:
    """Gaps between the request and the schedule, reported rather than absorbed."""

    def test_absent_slots_name_the_constraint_that_caused_them(self, result, facts) -> None:
        """A plan with no pulling reads as a programming choice otherwise.

        Every pulling exercise needs a bar, a machine or a bench she does not
        have, and every conditioning row is contraindicated or unequipped.
        That is the equipment limit talking, and the plan should say so.
        """
        plan = pack(result, facts, 50)
        absent = {s.slot for s in kinds(plan, ShortfallKind.SLOT_ABSENT)}
        assert absent == {Slot.UPPER_PULL, Slot.CONDITIONING}
        assert all(s.cause == "missing_equipment" for s in kinds(plan, ShortfallKind.SLOT_ABSENT))

    def test_a_slot_the_session_had_no_room_for_is_not_reported_absent(
        self, result, facts
    ) -> None:
        """"Nothing eligible covers core" is false when core work was eligible.

        A short session reaches fewer slots than a long one. Reporting that as
        an absence blames the member's equipment for the coach's clock.
        """
        short = pack(result, facts, 20)
        long = pack(result, facts, 50)
        assert Slot.CORE not in {s.slot for s in kinds(short, ShortfallKind.SLOT_ABSENT)}
        assert {s.slot for s in kinds(short, ShortfallKind.SLOT_ABSENT)} == {
            s.slot for s in kinds(long, ShortfallKind.SLOT_ABSENT)
        }

    def test_an_over_long_window_admits_the_gap(self, result, facts) -> None:
        """The catalog tops out well short of two hours for this member.

        Eight exercises at four sets is everything her pool can honestly
        support. Filling the rest would mean fifth sets or repeats.
        """
        plan = pack(result, facts, 120)
        assert plan.budget.unscheduled_seconds > 40 * 60
        assert kinds(plan, ShortfallKind.SECTION_UNDERFILLED)
        assert len(plan.section(Section.MAIN)) == MAX_MAIN_SLOTS

    def test_a_short_window_reports_what_it_trimmed(self, result, facts) -> None:
        """Warmup and cooldown must not crowd out the training.

        Capped together at a share of the session, so a twenty-minute booking
        does not spend seven of them on mobility work.
        """
        plan = pack(result, facts, 20)
        trimmed = kinds(plan, ShortfallKind.SECTION_TRIMMED)
        assert trimmed
        assert "Ground Upper Trap Stretch" in trimmed[0].detail


class TestDeterminism:
    """Two coaches, same member, same plan."""

    def test_two_runs_are_identical(self, result, facts) -> None:
        """A provenance trace is only worth reading if the plan reproduces.

        Mirrors the filter's own determinism test one layer up.
        """
        assert pack(result, facts, 50) == pack(result, facts, 50)

    def test_the_plan_does_not_depend_on_dictionary_order(self, result, facts) -> None:
        """Facts arrive keyed by id; iteration order must not reach the output.

        A plan that changes with insertion order is reproducible only by
        accident.
        """
        reversed_facts = dict(reversed(list(facts.items())))
        assert pack(result, facts, 50) == pack(result, reversed_facts, 50)


def test_per_side_blocks_carry_the_note(result, facts) -> None:
    """The catalog records only left-hand rows, so no side may be named.

    "Left Split Squat, 3 x 14" would be a fabricated clinical instruction. The
    plan says "each side" and explains why once.
    """
    plan = pack(result, facts, 50)
    assert any(b.prescription.per_side for b in plan.blocks)
    assert plan.notes
    assert "no side is named" in plan.notes[0]
    assert not any("left" in b.prescription.render().lower() for b in plan.blocks)
