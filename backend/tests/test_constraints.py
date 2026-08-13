from constraints.diff import diff
from constraints.models import Constraint, ConstraintSet, Effect, Origin


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
