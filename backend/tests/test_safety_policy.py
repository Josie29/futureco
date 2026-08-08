import itertools
import random

import pytest

from graph.schema import NodeLabel, RelType
from resolve.normalize import Side
from resolve.resolver import Candidate, Pass, Reason, Resolution
from safety.constraints import (
    Constraint,
    ConstraintKind,
    ConstraintSet,
    Directive,
    Op,
    Origin,
    UnappliedReason,
    compose,
)
from safety.evidence import EvidencePath, ExerciseEvidence, Hop, Signal, SignalKind
from safety.policy import EXCLUDING, Policy, Status, score


def signal(kind: SignalKind, detail: str = "because", annotation: str | None = None) -> Signal:
    """Build a signal with a one-hop path, for tests that don't care about paths."""
    return Signal(
        kind=kind,
        detail=detail,
        annotation=annotation,
        path=EvidencePath(
            entry="entry",
            hops=(Hop(rel=RelType.IS_A, to_label=NodeLabel.MOVEMENT_PATTERN, to_name="pattern"),),
        ),
    )


def evidence(*signals: Signal, name: str = "Exercise", priorities: tuple[int, ...] = ()) -> ExerciseEvidence:
    """Build evidence for one exercise."""
    return ExerciseEvidence(
        exercise_id=name.lower().replace(" ", "-"),
        name=name,
        signals=signals,
        goal_priorities=priorities,
    )


def resolution(name: str | None, label: NodeLabel = NodeLabel.EQUIPMENT) -> Resolution:
    """Build a resolved or unresolved Resolution."""
    if name is None:
        return Resolution(
            term="whatever", normalized="whatever", side=None, match=None,
            candidates=[Candidate(name="near", label=label, score=0.4, matched_by=Pass.FUZZY)],
            reason=Reason.BELOW_THRESHOLD,
        )
    match = Candidate(name=name, label=label, score=1.0, matched_by=Pass.EXACT)
    return Resolution(
        term=name, normalized=name.lower(), side=None, match=match, candidates=[match]
    )


class TestStatus:
    """Status is set membership, and penalties can never reach it."""

    def test_hard_signal_excludes_and_keeps_soft_evidence(self) -> None:
        """An excluded exercise still reports its soft problems.

        Without this the trace can only say "excluded for equipment" when the
        honest answer is "excluded for equipment, and it was cautioned anyway" —
        which is what a coach needs when deciding whether to source the kit.
        """
        verdict = score(
            evidence(
                signal(SignalKind.MISSING_EQUIPMENT, "needs a Barbell"),
                signal(SignalKind.CAUTION, "deep flexion under load"),
            )
        )
        assert verdict.status is Status.EXCLUDED
        assert {s.kind for s in verdict.signals} == {
            SignalKind.MISSING_EQUIPMENT,
            SignalKind.CAUTION,
        }

    @pytest.mark.parametrize("count", [1, 5, 50])
    def test_no_penalty_total_ever_excludes(self, count: int) -> None:
        """Stacking soft signals never crosses into exclusion.

        The property that keeps "down-ranked" and "forbidden" distinct. If a
        big enough penalty could exclude, a coach's anatomy mention would
        silently acquire the force of a clinical contraindication.
        """
        verdict = score(evidence(*[signal(SignalKind.CAUTION) for _ in range(count)]))
        assert verdict.status is Status.PENALIZED
        assert verdict.penalty == count * Policy().caution

    def test_clean_exercise_is_clear(self) -> None:
        """No signals means no penalty and no exclusion."""
        verdict = score(evidence())
        assert verdict.status is Status.CLEAR
        assert verdict.penalty == 0


class TestPenalty:
    """Soft signals stack, and caution outranks anatomy."""

    def test_caution_outranks_flagged_structure(self) -> None:
        """A clinician's caution penalises more than a coach's anatomy mention.

        Caution is authored judgement about a movement; a structure hit is
        inference that the exercise touches a joint. Flip this and `Cow Pose`
        would rank alongside a movement a clinician explicitly warned about.
        """
        cautioned = score(evidence(signal(SignalKind.CAUTION)))
        flagged = score(evidence(signal(SignalKind.FLAGGED_STRUCTURE)))
        assert cautioned.penalty > flagged.penalty

    def test_signals_stack(self) -> None:
        """Cautioned *and* loading a flagged joint is worse than either alone.

        This is the real shape of Jordan's split-squat variants versus
        `Cow Pose`, which only loads the knee.
        """
        both = score(evidence(signal(SignalKind.CAUTION), signal(SignalKind.FLAGGED_STRUCTURE)))
        one = score(evidence(signal(SignalKind.CAUTION)))
        assert both.penalty > one.penalty

    def test_affects_annotation_does_not_change_the_score(self) -> None:
        """An annotation explains without weighting.

        `affects` is documented as never traversed to filter (decisions.md KG1
        item 3). Ranking is the filter's output, so if an annotation moved a
        number that promise would be false.
        """
        plain = score(evidence(signal(SignalKind.FLAGGED_STRUCTURE)))
        annotated = score(
            evidence(signal(SignalKind.FLAGGED_STRUCTURE, annotation="site of inj_knee_left"))
        )
        assert plain.penalty == annotated.penalty
        assert plain.status is annotated.status
        assert "inj_knee_left" in annotated.headline


class TestRanking:
    """Ordering is total, reproducible, and safety-first."""

    def test_penalty_dominates_goal_fit(self) -> None:
        """A cautioned exercise never outranks a clean one, whatever it serves.

        Jordan's best goal-serving exercises are exactly the ones her injury
        cautions against. This pins that safety wins and `fit` only breaks
        ties — the tension stays visible rather than being resolved silently.
        """
        cautioned_but_perfect = score(evidence(signal(SignalKind.CAUTION), priorities=(1, 1)))
        clean_but_useless = score(evidence(name="Other"))
        assert clean_but_useless.sort_key < cautioned_but_perfect.sort_key
        assert cautioned_but_perfect.fit > clean_but_useless.fit

    def test_fit_breaks_ties_among_equals(self) -> None:
        """With equal penalty, the exercise serving a goal ranks higher."""
        serves = score(evidence(name="A", priorities=(1,)))
        does_not = score(evidence(name="B"))
        assert serves.sort_key < does_not.sort_key

    def test_order_is_total_and_shuffle_invariant(self) -> None:
        """Identical inputs in any order produce identical output.

        Without a total order the plan would differ between runs and no
        snapshot test could hold.
        """
        verdicts = [
            score(evidence(name="Tie A")),
            score(evidence(name="Tie B")),
            score(evidence(signal(SignalKind.CAUTION), name="Cautioned")),
            score(evidence(signal(SignalKind.DISLIKE), name="Disliked")),
        ]
        shuffled = verdicts[:]
        random.Random(0).shuffle(shuffled)
        assert [v.name for v in sorted(verdicts, key=lambda v: v.sort_key)] == [
            v.name for v in sorted(shuffled, key=lambda v: v.sort_key)
        ]


class TestAttribution:
    """Overlapping reasons are reported without pretending they partition."""

    def test_multi_reason_removal_attributes_to_one_cause(self) -> None:
        """Counts that sum correctly, without discarding the other reasons.

        `Vertical Jump to Broad Jump` is both disliked and contraindicated.
        Reporting 29 + 6 + 2 as a breakdown of 33 removals is quietly false;
        attribution gives figures that add up while the signals stay intact.
        """
        verdict = score(
            evidence(
                signal(SignalKind.DISLIKE, "she dislikes it"),
                signal(SignalKind.CONTRAINDICATION, "plyometrics are contraindicated"),
            )
        )
        assert verdict.attributed_to is SignalKind.CONTRAINDICATION
        assert len(verdict.signals) == 2

    def test_eligible_exercise_attributes_to_nothing(self) -> None:
        """Only removals are attributed."""
        assert score(evidence()).attributed_to is None

    def test_every_excluding_kind_is_attributable(self) -> None:
        """No excluding signal can produce a removal with no cause.

        Guards the precedence list against a new excluding kind being added to
        `EXCLUDING` but forgotten in `ATTRIBUTION_ORDER`, which would raise at
        runtime on a real member.
        """
        for kind in EXCLUDING:
            assert score(evidence(signal(kind))).attributed_to is not None


class TestCompose:
    """Directives fold onto the chart with their origin preserved."""

    def _standing(self) -> ConstraintSet:
        return ConstraintSet(
            member_id="mbr_1",
            constraints=(
                Constraint(kind=ConstraintKind.EQUIPMENT, value="Yoga Mat", origin=Origin.STANDING),
                Constraint(kind=ConstraintKind.EQUIPMENT, value="Flat Bench", origin=Origin.STANDING),
                Constraint(kind=ConstraintKind.INJURY, value="inj_knee_left", origin=Origin.STANDING),
            ),
        )

    def test_replace_drops_the_chart_and_records_the_source(self) -> None:
        """"Only dumbbells" means only dumbbells, and the trace can say why.

        Origin is what lets a coach see that the missing mat work is their own
        instruction rather than something the member's record caused.
        """
        directive = Directive(
            index=0, phrase="only dumbbells", op=Op.REPLACE,
            kind=ConstraintKind.EQUIPMENT, resolution=resolution("Dumbbell"),
        )
        result = compose(self._standing(), (directive,))
        assert result.applied.available_equipment == {"Dumbbell"}
        assert all(
            c.origin is Origin.DIRECTIVE
            for c in result.applied.of(ConstraintKind.EQUIPMENT)
        )

    def test_successive_replaces_accumulate_into_one_set(self) -> None:
        """"Only dumbbells and a kettlebell" is one set, not a last-one-wins race."""
        directives = tuple(
            Directive(index=i, phrase=p, op=Op.REPLACE, kind=ConstraintKind.EQUIPMENT,
                      resolution=resolution(p))
            for i, p in enumerate(["Dumbbell", "Kettlebell"])
        )
        result = compose(self._standing(), directives)
        assert result.applied.available_equipment == {"Dumbbell", "Kettlebell"}

    def test_add_keeps_the_chart(self) -> None:
        """A directive that adds does not disturb what the record holds."""
        directive = Directive(
            index=0, phrase="she has a pull-up bar today", op=Op.ADD,
            kind=ConstraintKind.EQUIPMENT, resolution=resolution("Pull-Up Bar"),
        )
        result = compose(self._standing(), (directive,))
        assert result.applied.available_equipment == {"Yoga Mat", "Flat Bench", "Pull-Up Bar"}

    def test_a_request_cannot_waive_a_clinical_constraint(self) -> None:
        """"Ignore her knee injury" is refused, loudly.

        The single most important test here. If a directive could remove an
        injury it would remove the contraindications a clinician authored, and
        the LLM extracting directives would have a path around the
        deterministic safety rule.
        """
        directive = Directive(
            index=0, phrase="ignore her knee injury", op=Op.REMOVE,
            kind=ConstraintKind.INJURY,
            resolution=resolution("inj_knee_left", NodeLabel.INJURY),
        )
        result = compose(self._standing(), (directive,))
        assert result.applied.injury_ids == {"inj_knee_left"}
        assert result.unapplied[0].reason is UnappliedReason.NOT_WAIVABLE
        assert "clinical" in result.unapplied[0].explanation

    def test_unresolved_directive_is_reported_with_candidates(self) -> None:
        """"Exclude deadlifts" changes nothing, and says so.

        Silently dropping it would leave the coach believing an exclusion is in
        force that is not — the failure mode the resolver already guards.
        """
        directive = Directive(
            index=0, phrase="exclude deadlifts", op=Op.ADD,
            kind=ConstraintKind.EXCLUDED_EXERCISE, resolution=resolution(None),
        )
        result = compose(self._standing(), (directive,))
        assert result.applied.constraints == self._standing().constraints
        assert result.unapplied[0].reason is UnappliedReason.UNRESOLVED
        assert "Did you mean" in result.unapplied[0].explanation

    def test_composition_records_the_whole_fold(self) -> None:
        """Standing, directives and result are all retained for the trace."""
        directive = Directive(
            index=0, phrase="only dumbbells", op=Op.REPLACE,
            kind=ConstraintKind.EQUIPMENT, resolution=resolution("Dumbbell"),
        )
        result = compose(self._standing(), (directive,))
        assert result.standing.available_equipment == {"Yoga Mat", "Flat Bench"}
        assert result.directives == (directive,)
        assert result.applied.available_equipment == {"Dumbbell"}


def test_every_signal_kind_is_exercised() -> None:
    """Every declared signal kind is covered by some assertion above.

    Mirrors the resolver's `test_every_pass_is_exercised`. Calibration there
    found a whole pass firing on nothing; this stops the weight table growing
    entries no test touches.
    """
    covered = {
        kind
        for kind in SignalKind
        if score(evidence(signal(kind))).status is not Status.CLEAR
    }
    assert covered == set(SignalKind)


def test_headline_uses_only_authored_text() -> None:
    """The coach-facing sentence contains the rationale verbatim.

    Every clause is authored or a fixed connective, so there is no generated
    prose and therefore nothing to hallucinate.
    """
    rationale = "Plyometrics are named directly in the clinician note."
    verdict = score(evidence(signal(SignalKind.CONTRAINDICATION, rationale), name="Static Jump"))
    assert rationale in verdict.headline
    assert verdict.headline.startswith("Static Jump: Excluded")


def test_policy_weights_are_injectable() -> None:
    """A different policy changes the numbers without touching the traversal."""
    strict = Policy(caution=10)
    assert score(evidence(signal(SignalKind.CAUTION)), strict).penalty == 10


@pytest.mark.parametrize(("priority", "expected"), [(1, 2), (2, 1), (3, 1), (9, 1)])
def test_only_the_top_goal_rank_is_distinguished(priority: int, expected: int) -> None:
    """Top-priority goals count double; everything below counts the same.

    The member's goals use priorities 1 and 2 only, so a graded scale would
    invent precision the data does not carry. This also pins that an
    out-of-range priority still contributes rather than silently scoring zero.
    """
    assert Policy().goal_weight(priority) == expected


def test_fit_counts_each_goal_once_not_each_muscle() -> None:
    """Two goals give twice the credit; two muscles of one goal do not.

    Jordan's split squats hit `glutes` and `quads`, which together serve
    `goal_strength` and `goal_knee`. Crediting per shared muscle instead of per
    goal would inflate `fit` for exercises that happen to be compound.
    """
    two_goals = score(evidence(priorities=(1, 1)))
    one_goal = score(evidence(priorities=(1,)))
    assert two_goals.fit == 4
    assert one_goal.fit == 2


def test_status_and_penalty_never_convert() -> None:
    """No combination of soft signals produces an excluding status.

    Exhaustive over every subset of the soft kinds up to length three.
    """
    soft = [kind for kind in SignalKind if kind not in EXCLUDING]
    for length in (1, 2, 3):
        for combination in itertools.product(soft, repeat=length):
            verdict = score(evidence(*[signal(kind) for kind in combination]))
            assert verdict.status is Status.PENALIZED
