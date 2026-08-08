import pytest

from graph.driver import graph_session
from graph.schema import NodeLabel
from resolve.resolver import Resolver
from resolve.vocabulary import Vocabulary
from safety.constraints import ConstraintKind, Op, Origin, UnappliedReason, compose
from safety.directives import Instruction, to_directives
from safety.evidence import SignalKind
from safety.filter import run
from safety.policy import Status
from safety.standing import load_standing
from settings import settings

MEMBER = "mbr_01HX9JORDAN"


@pytest.fixture(scope="session")
def session():
    """One Neo4j session for the whole module."""
    with graph_session() as open_session:
        yield open_session


@pytest.fixture(scope="session")
def resolver(session) -> Resolver:
    """A resolver over the live vocabulary."""
    return Resolver(Vocabulary.load(session, settings.aliases_path))


def filter_for(session, resolver: Resolver, *instructions: Instruction):
    """Run the filter for the sample member under zero or more instructions."""
    standing = load_standing(session, MEMBER)
    directives = to_directives(resolver, list(instructions))
    return run(session, compose(standing, directives))


def named(result, name: str):
    """The verdict for one exercise by name."""
    return next(v for v in result.verdicts if v.name == name)


class TestBaseline:
    """The member's standing constraints, with no instructions."""

    def test_counts_match_the_measured_baseline(self, session, resolver) -> None:
        """Snapshot of the whole filter against known data.

        The anchor for every other test here. If a traversal, a weight or the
        graph itself drifts, this is what notices.
        """
        result = filter_for(session, resolver)
        assert result.attribution.removed == 33
        assert result.attribution.kept == 17
        assert result.attribution.per_reason == {
            "contraindication": 6,
            "missing_equipment": 29,
            "dislike": 2,
        }
        assert not result.is_thin

    def test_attributed_counts_sum_to_removals(self, session, resolver) -> None:
        """Overlapping reasons are reported without pretending they partition.

        Per-reason sums to 37 across 33 removals. A UI showing 6/29/2 as a
        breakdown of 33 is quietly lying; the attributed figures add up.
        """
        result = filter_for(session, resolver)
        assert sum(result.attribution.per_reason.values()) == 37
        assert sum(result.attribution.attributed.values()) == 33
        assert result.attribution.attributed == {
            "contraindication": 6,
            "missing_equipment": 26,
            "dislike": 1,
        }

    def test_every_contraindicated_exercise_is_excluded_with_its_rationale(
        self, session, resolver
    ) -> None:
        """No plyometric survives, and each quotes the clinician verbatim.

        The spec's core requirement: the exclusion comes from a traversal, and
        the reason shown is authored text rather than generated prose.
        """
        result = filter_for(session, resolver)
        contraindicated = [v for v in result.verdicts if v.of(SignalKind.CONTRAINDICATION)]
        assert len(contraindicated) == 6
        for verdict in contraindicated:
            assert verdict.status is Status.EXCLUDED
            assert "Plyometrics are named directly" in verdict.headline

    def test_multi_reason_removal_keeps_every_reason(self, session, resolver) -> None:
        """An exercise removed twice over reports both causes.

        `Vertical Jump to Broad Jump` is disliked *and* plyometric. Reporting
        only the first found would make the dislike invisible if the injury
        ever resolved.
        """
        result = filter_for(session, resolver)
        verdict = named(result, "Vertical Jump to Broad Jump")
        kinds = {s.kind for s in verdict.signals}
        assert SignalKind.DISLIKE in kinds
        assert SignalKind.CONTRAINDICATION in kinds

    def test_no_kept_exercise_needs_absent_equipment(self, session, resolver) -> None:
        """Nothing survives that she could not physically perform."""
        result = filter_for(session, resolver)
        available = result.composition.applied.available_equipment
        for verdict in result.eligible:
            missing = [s for s in verdict.signals if s.kind is SignalKind.MISSING_EQUIPMENT]
            assert not missing, f"{verdict.name} needs equipment outside {sorted(available)}"

    def test_safety_outranks_goal_alignment(self, session, resolver) -> None:
        """The best goal-serving exercises still sort below the clean ones.

        Jordan's three split-squat variants serve both her goals and are the
        only cautioned survivors. This pins that a caution always wins, while
        `fit` stays visible so a coach can see what the caution cost.
        """
        result = filter_for(session, resolver)
        cautioned = [v for v in result.eligible if v.penalty > 0]
        assert {v.name for v in cautioned} == {
            "Alternating Dumbbell Racked Crossback Lunge",
            "Dumbbell Goblet Split Squat",
            "RNT Split Squat",
        }
        assert all(v.fit == 4 for v in cautioned)
        assert result.eligible[-3:] == tuple(
            sorted(cautioned, key=lambda v: v.sort_key)
        )


class TestAnatomyPath:
    """The mechanical path, which only a coach's words can trigger."""

    def flag(self, session, resolver, phrase: str):
        """Run the filter with one flagged anatomical structure."""
        return filter_for(
            session,
            resolver,
            Instruction(op=Op.ADD, kind=ConstraintKind.FLAGGED_STRUCTURE, phrase=phrase),
        )

    @pytest.mark.parametrize(
        "phrase", ["her left knee", "patellofemoral joint", "lower body"]
    )
    def test_every_granularity_reaches_the_knee(self, session, resolver, phrase: str) -> None:
        """A coach's word resolves at any depth and still reaches the joint.

        ASSESSMENT.md:30 asks for exactly this — sub-structures count too. The
        substructure ascends, the region descends, the joint matches directly.
        """
        result = self.flag(session, resolver, phrase)
        flagged = [v for v in result.verdicts if v.of(SignalKind.FLAGGED_STRUCTURE)]
        assert any("knee" in s.detail for v in flagged for s in v.signals)

    def test_mechanical_path_never_excludes(self, session, resolver) -> None:
        """Loading a flagged joint down-ranks; it never removes.

        The graph knows an exercise touches the knee, not that doing so is
        harmful. Hard-excluding here would strip `Cow Pose` and
        `World's Greatest Stretch` — the rehab work a patellofemoral protocol
        actually wants.
        """
        result = self.flag(session, resolver, "her left knee")
        for verdict in result.verdicts:
            if verdict.of(SignalKind.FLAGGED_STRUCTURE) and verdict.status is Status.EXCLUDED:
                assert any(s.kind in {SignalKind.MISSING_EQUIPMENT, SignalKind.CONTRAINDICATION,
                                      SignalKind.DISLIKE} for s in verdict.signals)
        assert named(result, "Cow Pose").eligible
        assert named(result, "World's Greatest Stretch").eligible

    def test_no_sibling_leakage(self, session, resolver) -> None:
        """Flagging the knee never reaches an ankle-only exercise.

        Undirected `part_of*` walks up to `lower limb` and back down to
        `ankle`. This is the test that catches that traversal bug — it is
        invisible in the counts and wrong in the plan.
        """
        result = self.flag(session, resolver, "her left knee")
        for verdict in result.verdicts:
            for signal in verdict.of(SignalKind.FLAGGED_STRUCTURE):
                assert "knee" in signal.detail, f"{verdict.name}: {signal.detail}"

    def test_affects_annotates_but_does_not_score(self, session, resolver) -> None:
        """A recorded injury explains a signal without weighting it.

        `decisions.md` KG1 item 3 promises `affects` is never traversed to
        filter. Ranking is the filter's output, so if the annotation moved a
        number that promise would be false. `High Plank Bird Dog` stresses both
        knee and shoulder, so it is the row that would shift if this regressed.
        """
        knee = self.flag(session, resolver, "her left knee")
        shoulder = self.flag(session, resolver, "her shoulder")

        knee_verdict = named(knee, "High Plank Bird Dog")
        shoulder_verdict = named(shoulder, "High Plank Bird Dog")
        assert knee_verdict.penalty == shoulder_verdict.penalty

        annotations = [s.annotation for s in knee_verdict.signals if s.annotation]
        assert any("inj_knee_left" in a for a in annotations)
        assert not [s.annotation for s in shoulder_verdict.signals if s.annotation]

    def test_structure_with_no_joint_closure_is_reported(self, session, resolver) -> None:
        """`erector spinae` reaches no joint, and the filter says so.

        It is a substructure parented straight to the `spine` region, skipping
        the joint tier. Silently matching nothing would look like "nothing to
        worry about" when the truth is "this term could not be applied".
        """
        result = self.flag(session, resolver, "erector spinae")
        assert "erector spinae" in result.unresolved_structures


class TestDirectives:
    """Composition of this request's instructions onto the chart."""

    def test_replace_equipment_drops_chart_items_and_attributes_it(
        self, session, resolver
    ) -> None:
        """The spec's equipment example, end to end.

        "Only dumbbells and a kettlebell" replaces her stored list, so the
        yoga-mat work goes — and the trace attributes that to the instruction
        rather than to her record.
        """
        result = filter_for(
            session,
            resolver,
            Instruction(op=Op.REPLACE, kind=ConstraintKind.EQUIPMENT, phrase="dumbbells"),
            Instruction(op=Op.REPLACE, kind=ConstraintKind.EQUIPMENT, phrase="a kettlebell"),
        )
        assert result.composition.applied.available_equipment == {"Dumbbell", "Kettlebell"}
        assert all(
            c.origin is Origin.DIRECTIVE
            for c in result.composition.applied.of(ConstraintKind.EQUIPMENT)
        )
        assert len(result.eligible) < 17

    def test_thin_pool_is_flagged_with_its_cause(self, session, resolver) -> None:
        """Over-constraining is reported, not silently obeyed.

        Without this the agent cannot tell "5 good options" from "5 because you
        asked for too much", and a coach gets a thin plan with no explanation.
        """
        result = filter_for(
            session,
            resolver,
            Instruction(op=Op.REPLACE, kind=ConstraintKind.EQUIPMENT, phrase="dumbbells"),
        )
        assert result.is_thin
        assert result.costliest_constraint == "missing_equipment"

    def test_add_equipment_only_grows_the_pool(self, session, resolver) -> None:
        """An additive instruction leaves the chart intact."""
        baseline = filter_for(session, resolver)
        result = filter_for(
            session,
            resolver,
            Instruction(op=Op.ADD, kind=ConstraintKind.EQUIPMENT, phrase="pull-up bar"),
        )
        assert result.composition.applied.available_equipment > baseline.composition.applied.available_equipment
        assert len(result.eligible) >= len(baseline.eligible)

    def test_unresolved_instruction_changes_nothing_and_says_so(
        self, session, resolver
    ) -> None:
        """"Exclude deadlifts" excludes nothing, and reports that it did not.

        The catalog stocks no deadlift. Silently dropping the instruction would
        leave the coach believing an exclusion is in force.
        """
        baseline = filter_for(session, resolver)
        result = filter_for(
            session,
            resolver,
            Instruction(op=Op.ADD, kind=ConstraintKind.EXCLUDED_EXERCISE, phrase="deadlifts"),
        )
        assert len(result.eligible) == len(baseline.eligible)
        assert result.composition.unapplied[0].reason is UnappliedReason.UNRESOLVED

    def test_a_request_cannot_waive_an_injury(self, session, resolver) -> None:
        """No instruction restores a contraindicated exercise.

        The safety property that matters most. If this fails, the language
        model extracting instructions has a path around the deterministic rule.
        """
        result = filter_for(
            session,
            resolver,
            Instruction(op=Op.REMOVE, kind=ConstraintKind.INJURY, phrase="knee"),
        )
        assert result.composition.applied.injury_ids == {"inj_knee_left"}
        assert result.composition.unapplied[0].reason is UnappliedReason.NOT_WAIVABLE
        assert named(result, "Static Jump").status is Status.EXCLUDED


def test_two_runs_are_identical(session, resolver) -> None:
    """The same graph and constraints produce byte-identical verdicts.

    Determinism is what makes the filter auditable: a provenance trace is only
    worth reading if re-running would produce it again.
    """
    first = filter_for(session, resolver)
    second = filter_for(session, resolver)
    assert first.verdicts == second.verdicts
    assert first.attribution == second.attribution
