import pytest

from graph.build.report import read_report
from graph.driver import graph_session
from plan.pipeline import generate
from plan.queries import MOVEMENT_FACTS
from plan.schemas import ReasonKind, Section
from resolve.resolver import Resolver
from resolve.vocabulary import Vocabulary
from safety.constraints import ConstraintKind, Op, UnappliedReason
from safety.directives import Instruction
from safety.policy import Status
from settings import settings

MEMBER = "mbr_01HX9JORDAN"


@pytest.fixture(scope="module")
def session():
    """One Neo4j session for the whole module."""
    with graph_session() as open_session:
        yield open_session


@pytest.fixture(scope="module")
def resolver(session) -> Resolver:
    """A resolver over the live vocabulary."""
    return Resolver(Vocabulary.load(session, settings.aliases_path))


def build(session, resolver, minutes: int = 50, **kwargs):
    """Generate a plan for the sample member."""
    return generate(session, resolver, MEMBER, minutes, **kwargs)


def reason_kinds(generated) -> set[ReasonKind]:
    """Every reason kind appearing anywhere in the plan."""
    return {reason.kind for block in generated.plan.blocks for reason in block.reasons}


class TestEndToEnd:
    """The whole deterministic half, from chart to session."""

    def test_a_plan_arrives_with_its_provenance(self, session, resolver) -> None:
        """A plan without its trace cannot be defended.

        `ASSESSMENT.md:33` asks which graph path justified a recommendation,
        and the answer has to travel with the recommendation rather than being
        reconstructable in principle.
        """
        generated = build(session, resolver)
        assert generated.plan.blocks
        assert generated.trace.result.attribution.kept == 17
        assert generated.run_id

        # The fingerprint has to be the *live* graph, so a stale verdict can be
        # told from a current one. Asserted against a fresh read rather than a
        # literal: a hardcoded total breaks whenever either graph grows, which
        # is a fact about the fixture rather than about provenance. KG2's
        # build-out took this from 170 to 224 without touching the generator.
        assert generated.trace.header.used_graph.node_total == read_report(session).node_total
        assert generated.trace.header.used_graph.node_total > 0

    def test_every_block_explains_itself(self, session, resolver) -> None:
        """The console renders `why` per movement and states it is never empty."""
        generated = build(session, resolver)
        for block in generated.plan.blocks:
            assert block.reasons, block.name

    def test_a_stand_in_says_whose_place_it_took(self, session, resolver) -> None:
        """A substituted movement is otherwise indistinguishable from a chosen one.

        `Dumbbell Goblet Split Squat` is in the plan on its own merits *and*
        covers the med-ball split squat she cannot perform; only the reason
        says so.
        """
        generated = build(session, resolver)
        block = next(
            b for b in generated.plan.blocks if b.name == "Dumbbell Goblet Split Squat"
        )
        substitution = next(r for r in block.reasons if r.kind is ReasonKind.SUBSTITUTION)
        assert "Med Ball Split Squat" in substitution.detail
        assert "needs equipment that is not available" in substitution.detail


class TestInstructions:
    """This request's instructions, folded onto the chart."""

    def test_replacing_equipment_thins_the_plan(self, session, resolver) -> None:
        """The spec's limited-equipment scenario, end to end.

        "Only dumbbells" has to reach the session, not just the verdict list —
        a filter that narrows while the plan stays the same is a filter with
        no effect.
        """
        baseline = build(session, resolver)
        limited = build(
            session,
            resolver,
            instructions=(
                Instruction(op=Op.REPLACE, kind=ConstraintKind.EQUIPMENT, phrase="dumbbells"),
            ),
        )
        assert len(limited.plan.blocks) < len(baseline.plan.blocks)
        assert limited.trace.result.is_thin

    def test_an_instruction_cannot_waive_the_injury(self, session, resolver) -> None:
        """The safety property that matters most, through the whole pipeline.

        If a request could drop the injury, every downstream stage would
        faithfully build a plan around a contraindication a clinician wrote.
        The plan is the last place that failure would be visible.
        """
        generated = build(
            session,
            resolver,
            instructions=(
                Instruction(op=Op.REMOVE, kind=ConstraintKind.INJURY, phrase="knee"),
            ),
        )
        unapplied = generated.composition.unapplied
        assert unapplied[0].reason is UnappliedReason.NOT_WAIVABLE
        plyometric = [
            v for v in generated.trace.result.verdicts if v.name == "Static Jump"
        ]
        assert plyometric[0].status is Status.EXCLUDED
        assert "Static Jump" not in {b.name for b in generated.plan.blocks}

    def test_an_unresolved_phrase_changes_nothing_and_is_reported(
        self, session, resolver
    ) -> None:
        """"Exclude deadlifts" excludes nothing, because the catalog has none.

        Silently dropping it would leave the coach believing an exclusion is
        in force. The catalog stocks no deadlift and the resolver declines by
        design — `decisions.md`, Resolver 4.
        """
        baseline = build(session, resolver)
        generated = build(
            session,
            resolver,
            instructions=(
                Instruction(
                    op=Op.ADD, kind=ConstraintKind.EXCLUDED_EXERCISE, phrase="deadlifts"
                ),
            ),
        )
        assert generated.plan.blocks == baseline.plan.blocks
        unapplied = generated.composition.unapplied[0]
        assert unapplied.reason is UnappliedReason.UNRESOLVED
        assert "matched nothing in the catalog" in unapplied.explanation


class TestEmphasis:
    """What the spec's first example prompt asks for."""

    def test_a_resolved_emphasis_is_reported_on_the_movements_that_serve_it(
        self, session, resolver
    ) -> None:
        """"Isolation around my pecs" must visibly do something.

        Emphasis is not a `ConstraintKind` — it widens rather than narrows, so
        it acts on the packer's tie-break. That makes it easy for it to change
        nothing at all and say nothing either.
        """
        generated = build(session, resolver, emphasis=("pecs",))
        assert [r.match.name for r in generated.focus] == ["chest"]
        assert ReasonKind.FOCUS_MATCH in reason_kinds(generated)

    def test_an_unresolved_emphasis_is_carried_rather_than_dropped(
        self, session, resolver
    ) -> None:
        """A phrase that reached nothing must not look like one that applied."""
        generated = build(session, resolver, emphasis=("wingspan",))
        assert generated.focus[0].match is None
        assert ReasonKind.FOCUS_MATCH not in reason_kinds(generated)

    def test_emphasis_never_promotes_an_excluded_movement(
        self, session, resolver
    ) -> None:
        """Goal fit and emphasis both rank inside the eligible pool and no further."""
        generated = build(session, resolver, emphasis=("quads",))
        excluded = {
            v.exercise_id for v in generated.trace.result.verdicts if not v.eligible
        }
        assert not {b.exercise_id for b in generated.plan.blocks} & excluded


class TestDeterminism:
    """The promise the provenance trace depends on."""

    def test_two_runs_differ_only_by_their_identifiers(self, session, resolver) -> None:
        """A trace is worth reading only if re-running reproduces the plan.

        `run_id` and the trace timestamp are per-run by design; everything
        else must match, so they are the only fields excluded.
        """
        first = build(session, resolver).model_dump()
        second = build(session, resolver).model_dump()
        for dump in (first, second):
            dump.pop("run_id")
            dump["trace"]["header"].pop("generated_at_time")
        assert first == second


def test_the_pattern_property_agrees_with_the_is_a_edges(session) -> None:
    """Ordering comes from the node property, membership from the edges.

    The catalog lists an exercise's primary family first and `collect` does not
    preserve that, so `patterns` is read from the property — which is only
    sound while the two describe the same set. If a build ever wrote one
    without the other, a plan would justify itself with an edge that is not
    in the graph.
    """
    for row in session.run(MOVEMENT_FACTS, member_id=MEMBER):
        assert set(row["patterns"]) == set(row["linked"]), row["exercise_id"]


def test_a_plan_covers_every_section(session, resolver) -> None:
    """The probe's output is the README's worked example; an empty section shows."""
    generated = build(session, resolver)
    for section in Section:
        assert generated.plan.section(section), section
