import itertools
import random

import pytest

from graph.build.catalog import load_exercises
from plan.families import (
    FAMILY_ROLES,
    MODALITY_ORDER,
    SECTION_ORDER,
    SLOT_ORDER,
    role_of,
    unmapped,
)
from plan.schemas import Modality, Section, Slot
from settings import settings


@pytest.fixture(scope="module")
def exercises():
    """The catalog, read once."""
    return load_exercises(settings.exercises_path)


@pytest.fixture(scope="module")
def families(exercises) -> list[str]:
    """Every distinct movement-pattern family the catalog names."""
    return sorted({pattern for ex in exercises for pattern in ex.movement_patterns})


class TestTable:
    """The authored family table, against the catalog it has to cover."""

    def test_every_catalog_family_is_mapped(self, families) -> None:
        """A family with no role silently drops its exercise from every plan.

        The coach sees an absence with no explanation, and nothing in the
        output distinguishes "not suitable" from "the table forgot it".
        """
        missing = [family for family in families if family not in FAMILY_ROLES]
        assert not missing, f"unmapped families: {missing}"

    def test_the_table_maps_nothing_the_catalog_lacks(self, families) -> None:
        """A stale row outlives the pattern it described.

        Not a runtime bug, but it makes the table read as authoritative about
        movements this catalog has never contained.
        """
        stale = sorted(set(FAMILY_ROLES) - set(families))
        assert not stale, f"table has families the catalog does not: {stale}"

    def test_every_section_and_slot_is_reachable(self) -> None:
        """A dead section or slot is a rule nothing can ever trigger.

        The resolver's calibration turned up exactly this — a vector pass whose
        cases were all resolved by fuzzy. An unreachable branch reads as
        coverage and provides none.
        """
        assert {role.section for role in FAMILY_ROLES.values()} == set(Section)
        assert {role.slot for role in FAMILY_ROLES.values()} == set(Slot)

    def test_the_ordinals_cover_every_value(self) -> None:
        """A value missing from an ordinal raises at resolution time.

        The three `.index` calls are the comparison key, so an omission is a
        ValueError on a coach's request, not merely a wrong sort.
        """
        assert set(SECTION_ORDER) == set(Section)
        assert set(SLOT_ORDER) == set(Slot)
        assert set(MODALITY_ORDER) == set(Modality)


class TestResolution:
    """Deciding one section and slot from several families."""

    def test_warmup_outranks_cooldown_on_dynamic_regen(self) -> None:
        """Reversing this precedence guts the warmup.

        `mobility - dynamic` paired with `regen` is the only real section
        conflict in the catalog, and it covers three rows. With COOLDOWN
        first, the sample member's warmup pool drops from three exercises to
        one — a plan that opens with a single set of toe touches.
        """
        assert role_of(("mobility - dynamic", "regen")).section is Section.WARMUP
        assert role_of(("regen", "mobility - dynamic")).section is Section.WARMUP

    def test_a_rep_counted_hold_keeps_a_rep_range(self) -> None:
        """`High Plank Bird Dog` claims both isometric and strength.

        They agree on section and slot, so a key of only those two left the
        winner decided by list position. Landing on ISOMETRIC gives a
        rep-counted exercise no rep range at all, and the prescription falls
        back to whatever the catalog's cadence produces unbounded.
        """
        role = role_of(("core - anti-rotation", "isometric", "quadruped"))
        assert role.modality is Modality.STRENGTH
        assert role_of(("isometric", "quadruped", "core - anti-rotation")) == role

    def test_a_push_up_is_filed_as_a_push(self) -> None:
        """Lexicographic order would call `Push-Up to Knee-Drive` core work.

        `core - anti-extension` sorts before `upper push - horizontal`, so the
        obvious tie-break puts a push-up in the core slot and leaves the main
        block with no pressing movement.
        """
        role = role_of(("core - flexion", "core - anti-extension", "upper push - horizontal"))
        assert role.slot is Slot.UPPER_PUSH

    def test_resolution_ignores_pattern_order(self, exercises) -> None:
        """Reordering the catalog JSON must not change a plan.

        Without an authored ordinal the first-listed pattern wins, so an
        editorial tidy-up of `exercises.json` silently reshapes every session.
        """
        rng = random.Random(0)
        for exercise in exercises:
            patterns = list(exercise.movement_patterns)
            expected = role_of(tuple(patterns))
            for _ in range(20):
                rng.shuffle(patterns)
                assert role_of(tuple(patterns)) == expected, exercise.name

    @pytest.mark.parametrize("patterns", [(), ("not a real family",)])
    def test_an_unknown_family_is_unplaceable_not_a_crash(self, patterns) -> None:
        """One bad pattern must cost one exercise, not the whole request.

        A KeyError here 500s a coach mid-session. Returning None lets the
        packer drop that row with a Shortfall and build the rest.
        """
        assert role_of(patterns) is None

    def test_a_partially_known_exercise_still_places(self) -> None:
        """An exercise is placed on the families that are known.

        Dropping it because one of its four patterns is unrecognised would
        lose a usable movement over a vocabulary gap.
        """
        role = role_of(("not a real family", "upper push - horizontal"))
        assert role.slot is Slot.UPPER_PUSH
        assert unmapped(("not a real family", "upper push - horizontal")) == ("not a real family",)


def test_every_catalog_exercise_places(exercises) -> None:
    """Every one of the fifty is placeable, so no plan starts a row short.

    The per-exercise guarantee the family-coverage test only implies.
    """
    unplaceable = [ex.name for ex in exercises if role_of(tuple(ex.movement_patterns)) is None]
    assert not unplaceable


def test_no_two_families_disagree_within_one_exercise_silently(exercises) -> None:
    """Multi-family exercises resolve to exactly one section, deterministically.

    Guards the resolution contract itself: whatever the rule decides, it must
    decide the same thing for every permutation of the same input.
    """
    for exercise in exercises:
        roles = {
            role_of(tuple(order))
            for order in itertools.permutations(exercise.movement_patterns)
        }
        assert len(roles) == 1, exercise.name
