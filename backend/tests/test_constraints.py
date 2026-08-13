from constraints.diff import diff
from constraints.models import (
    REQUIRING_EFFECTS,
    Constraint,
    ConstraintSet,
    Effect,
    Origin,
)


def c(target: str, effect: Effect = Effect.AVOID, reason: str = "r") -> Constraint:
    return Constraint(target=target, effect=effect, origin=Origin.COACH, reason=reason)


def cs(*constraints: Constraint) -> ConstraintSet:
    return ConstraintSet(constraints=constraints)


def test_declaring_the_same_set_twice_changes_nothing() -> None:
    """Idempotency: a re-declaration is not an edit.

    If a repeated declaration produced added/removed noise, the model would
    learn to distrust the diff and stop re-stating the full set — the exact
    failure the declarative contract replaces.
    """
    declared = cs(c("exercise:X"), c("muscle:glutes", Effect.PREFER))
    d = diff(declared, declared)
    assert d.added == () and d.removed == ()
    assert len(d.unchanged) == 2


def test_omission_is_deletion_and_deletion_is_shown() -> None:
    """A constraint left out of a declaration surfaces in `removed`.

    This is the drop-visibility that fixes the old adjustment bug where a
    refinement silently dropped constraints nobody had withdrawn.
    """
    before = cs(c("exercise:X"), c("exercise:Y"))
    after = cs(c("exercise:X"))
    d = diff(before, after)
    assert [r.target for r in d.removed] == ["exercise:Y"]


def test_new_constraints_surface_in_added() -> None:
    """A newly declared constraint is reported as such."""
    d = diff(cs(c("exercise:X")), cs(c("exercise:X"), c("exercise:Z")))
    assert [a.target for a in d.added] == ["exercise:Z"]


def test_rewording_a_reason_is_not_a_change() -> None:
    """Reason is annotation, not identity — a reworded reason reads unchanged.

    Otherwise every paraphrase would show as removed+added and the diff
    would lie about the coach's intent shifting.
    """
    before = cs(c("exercise:X", reason="no jumping"))
    after = cs(c("exercise:X", reason="coach said avoid jumping"))
    d = diff(before, after)
    assert d.added == () and d.removed == ()
    assert d.unchanged[0].reason == "coach said avoid jumping"


def test_same_target_different_effect_are_distinct_constraints() -> None:
    """avoid X and prefer X are different directives, not one edited one."""
    before = cs(c("muscle:glutes", Effect.PREFER))
    after = cs(c("muscle:glutes", Effect.AVOID))
    d = diff(before, after)
    assert len(d.added) == 1 and len(d.removed) == 1


def test_duplicate_keys_in_one_declaration_collapse() -> None:
    """Declaring the same constraint twice installs it once."""
    d = diff(cs(), cs(c("exercise:X"), c("exercise:X", reason="again")))
    assert len(d.added) == 1


def test_diff_ordering_is_deterministic() -> None:
    """Same declaration, same diff, byte for byte — provenance depends on it."""
    before = cs()
    after = cs(c("exercise:Z"), c("exercise:A"), c("muscle:core", Effect.PREFER))
    assert diff(before, after) == diff(before, after)
    assert [a.target for a in diff(before, after).added] == sorted(
        a.target for a in diff(before, after).added
    )


def test_set_helpers_filter_by_effect() -> None:
    """of() and targets() slice the set the way validators consume it."""
    declared = cs(
        c("exercise:X"), c("muscle:glutes", Effect.PREFER), c("exercise:Y", Effect.REQUIRE)
    )
    assert [x.target for x in declared.of(Effect.AVOID)] == ["exercise:X"]
    assert declared.targets(Effect.REQUIRE) == frozenset({"exercise:Y"})
    assert declared.targets(Effect.AVOID, Effect.REQUIRE) == frozenset(
        {"exercise:X", "exercise:Y"}
    )


def test_block_is_excluding_and_caution_is_not() -> None:
    """The effect lattice: BLOCK forbids, CAUTION annotates.

    If CAUTION joined the excluding set, every cautioned rehab exercise
    would vanish from eligibility — the exact failure the clinical split
    exists to prevent.
    """
    from constraints.models import EXCLUDING_EFFECTS

    assert Effect.BLOCK in EXCLUDING_EFFECTS
    assert Effect.CAUTION not in EXCLUDING_EFFECTS
    assert Effect.CAUTION not in REQUIRING_EFFECTS


def test_evidence_is_excluded_from_key_identity() -> None:
    """Two constraints differing only in evidence diff as unchanged."""
    from graph.evidence import EvidencePath

    before = cs(c("exercise:X"))
    after = cs(
        Constraint(
            target="exercise:X", effect=Effect.AVOID, origin=Origin.COACH,
            reason="r", evidence=EvidencePath(entry="somewhere"),
        )
    )
    d = diff(before, after)
    assert d.added == () and d.removed == ()


def test_compose_holds_every_clinical_constraint_verbatim() -> None:
    """No declared set can weaken the clinical floor.

    The monotone floor is the product's central safety claim: coach
    directives only ever narrow or steer, never unlock.
    """
    from constraints.compose import compose

    clinical = cs(
        Constraint(target="movement_pattern:plyo", effect=Effect.BLOCK,
                   origin=Origin.CLINICAL, reason="contraindicated"),
        Constraint(target="movement_pattern:squat", effect=Effect.CAUTION,
                   origin=Origin.CLINICAL, reason="cautioned"),
    )
    adversarial = (
        cs(),
        cs(c("movement_pattern:plyo", Effect.PREFER)),
        cs(c("movement_pattern:plyo", Effect.REQUIRE)),
        cs(c("movement_pattern:plyo", Effect.AVOID)),
        cs(c("exercise:Jump Squat", Effect.REQUIRE)),
    )
    for declared in adversarial:
        composed = compose(clinical, declared)
        for constraint in clinical.constraints:
            assert constraint in composed.constraints


def test_compose_orders_clinical_first() -> None:
    """Clinical constraints lead the composed set, deterministically."""
    from constraints.compose import compose

    clinical = cs(
        Constraint(target="movement_pattern:plyo", effect=Effect.BLOCK,
                   origin=Origin.CLINICAL, reason="x")
    )
    declared = cs(c("exercise:Y"))
    composed = compose(clinical, declared)
    assert composed.constraints[0].origin is Origin.CLINICAL
    assert composed.constraints[-1].origin is Origin.COACH
