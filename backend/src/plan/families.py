from plan.schemas import FamilyRole, Modality, Section, Slot

# Every movement-pattern family in the catalog, and what it implies about
# programming. Authored, like `contraindications.json`, rather than inferred
# from the family name: "regen" and "car" mean nothing to a string matcher, and
# a rule that guessed would guess silently. A test asserts the catalog names no
# family this table is missing.
#
# `car` is a Controlled Articular Rotation — a joint-prep drill, so warmup.
# `balance` never decides a section here; it only ever co-occurs, and rides
# along in LOWER.
FAMILY_ROLES: dict[str, FamilyRole] = {
    # Warmup
    "mobility - dynamic": FamilyRole(
        section=Section.WARMUP, modality=Modality.MOBILITY, slot=Slot.MOBILITY
    ),
    "car": FamilyRole(section=Section.WARMUP, modality=Modality.MOBILITY, slot=Slot.MOBILITY),
    # Cooldown
    "mobility - static": FamilyRole(
        section=Section.COOLDOWN, modality=Modality.MOBILITY, slot=Slot.MOBILITY
    ),
    "regen": FamilyRole(section=Section.COOLDOWN, modality=Modality.MOBILITY, slot=Slot.MOBILITY),
    "massage": FamilyRole(section=Section.COOLDOWN, modality=Modality.MOBILITY, slot=Slot.MOBILITY),
    "yoga": FamilyRole(section=Section.COOLDOWN, modality=Modality.MOBILITY, slot=Slot.MOBILITY),
    # Main — conditioning
    "cardio": FamilyRole(
        section=Section.MAIN, modality=Modality.CONDITIONING, slot=Slot.CONDITIONING
    ),
    "cardio - locomotion": FamilyRole(
        section=Section.MAIN, modality=Modality.CONDITIONING, slot=Slot.CONDITIONING
    ),
    "cardio - plyometric": FamilyRole(
        section=Section.MAIN, modality=Modality.CONDITIONING, slot=Slot.CONDITIONING
    ),
    "total body": FamilyRole(
        section=Section.MAIN, modality=Modality.CONDITIONING, slot=Slot.CONDITIONING
    ),
    # Main — core
    "isometric": FamilyRole(section=Section.MAIN, modality=Modality.ISOMETRIC, slot=Slot.CORE),
    "core - anti-extension": FamilyRole(
        section=Section.MAIN, modality=Modality.STRENGTH, slot=Slot.CORE
    ),
    "core - anti-lateral flexion": FamilyRole(
        section=Section.MAIN, modality=Modality.STRENGTH, slot=Slot.CORE
    ),
    "core - anti-rotation": FamilyRole(
        section=Section.MAIN, modality=Modality.STRENGTH, slot=Slot.CORE
    ),
    "core - flexion": FamilyRole(section=Section.MAIN, modality=Modality.STRENGTH, slot=Slot.CORE),
    "core - extension": FamilyRole(section=Section.MAIN, modality=Modality.STRENGTH, slot=Slot.CORE),
    "core - rotation": FamilyRole(section=Section.MAIN, modality=Modality.STRENGTH, slot=Slot.CORE),
    "core - carry": FamilyRole(section=Section.MAIN, modality=Modality.STRENGTH, slot=Slot.CORE),
    "quadruped": FamilyRole(section=Section.MAIN, modality=Modality.STRENGTH, slot=Slot.CORE),
    # Main — arms
    "arms - accessory": FamilyRole(
        section=Section.MAIN, modality=Modality.STRENGTH, slot=Slot.ARMS
    ),
    # Main — upper push
    "upper push - horizontal": FamilyRole(
        section=Section.MAIN, modality=Modality.STRENGTH, slot=Slot.UPPER_PUSH
    ),
    "upper push - vertical": FamilyRole(
        section=Section.MAIN, modality=Modality.STRENGTH, slot=Slot.UPPER_PUSH
    ),
    "upper - adduction": FamilyRole(
        section=Section.MAIN, modality=Modality.STRENGTH, slot=Slot.UPPER_PUSH
    ),
    "shoulders - accessory": FamilyRole(
        section=Section.MAIN, modality=Modality.STRENGTH, slot=Slot.UPPER_PUSH
    ),
    # Main — upper pull
    "upper pull - horizontal": FamilyRole(
        section=Section.MAIN, modality=Modality.STRENGTH, slot=Slot.UPPER_PULL
    ),
    "upper pull - vertical": FamilyRole(
        section=Section.MAIN, modality=Modality.STRENGTH, slot=Slot.UPPER_PULL
    ),
    # Main — lower
    "lower push - squat": FamilyRole(
        section=Section.MAIN, modality=Modality.STRENGTH, slot=Slot.LOWER
    ),
    "lower push - lunge": FamilyRole(
        section=Section.MAIN, modality=Modality.STRENGTH, slot=Slot.LOWER
    ),
    "lower push - split squat": FamilyRole(
        section=Section.MAIN, modality=Modality.STRENGTH, slot=Slot.LOWER
    ),
    "lower push - step-up": FamilyRole(
        section=Section.MAIN, modality=Modality.STRENGTH, slot=Slot.LOWER
    ),
    "lower push - calf raise": FamilyRole(
        section=Section.MAIN, modality=Modality.STRENGTH, slot=Slot.LOWER
    ),
    "lower pull - hip lift": FamilyRole(
        section=Section.MAIN, modality=Modality.STRENGTH, slot=Slot.LOWER
    ),
    "lower - abduction": FamilyRole(
        section=Section.MAIN, modality=Modality.STRENGTH, slot=Slot.LOWER
    ),
    "lower - adduction": FamilyRole(
        section=Section.MAIN, modality=Modality.STRENGTH, slot=Slot.LOWER
    ),
    "legs - accessory": FamilyRole(
        section=Section.MAIN, modality=Modality.STRENGTH, slot=Slot.LOWER
    ),
    "balance": FamilyRole(section=Section.MAIN, modality=Modality.STRENGTH, slot=Slot.LOWER),
}

# Twenty-nine of fifty exercises carry more than one family, so resolution
# needs a rule. These two ordinals are it — never JSON list order, which is
# fragile, and never lexicographic, which would file `Push-Up to Knee-Drive`
# under CORE because `core - anti-extension` sorts before
# `upper push - horizontal`. It is a push-up.
#
# WARMUP before COOLDOWN is load-bearing: the conflict is `mobility - dynamic`
# paired with `regen`, and reversing the precedence drops the sample member's
# warmup pool from three exercises to one.
SECTION_ORDER: tuple[Section, ...] = (Section.WARMUP, Section.COOLDOWN, Section.MAIN)

# Compound before accessory, so a main block that can only fit three exercises
# fills them with the movements that matter most.
SLOT_ORDER: tuple[Slot, ...] = (
    Slot.LOWER,
    Slot.UPPER_PUSH,
    Slot.UPPER_PULL,
    Slot.CORE,
    Slot.ARMS,
    Slot.CONDITIONING,
    Slot.MOBILITY,
)

# Section and slot alone do not decide a role: `High Plank Bird Dog` is
# `isometric` + `core - anti-rotation` + `quadruped`, which agree on MAIN and
# CORE and disagree on modality. Modality fixes the rep range, while `is_reps`
# separately decides whether an exercise is held or counted — so the modality
# that says the most about counting wins, and ISOMETRIC, which sets no range at
# all, only wins when nothing else claims the exercise.
MODALITY_ORDER: tuple[Modality, ...] = (
    Modality.CONDITIONING,
    Modality.STRENGTH,
    Modality.MOBILITY,
    Modality.ISOMETRIC,
)


def _ordinal(role: FamilyRole) -> tuple[int, int, int]:
    """Rank one role against another. Total, so resolution cannot tie."""
    return (
        SECTION_ORDER.index(role.section),
        SLOT_ORDER.index(role.slot),
        MODALITY_ORDER.index(role.modality),
    )


def role_of(patterns: tuple[str, ...]) -> FamilyRole | None:
    """Decide where one exercise belongs from every family it claims.

    Section dominates, then slot, then modality — one total ordinal, so the
    result cannot depend on the order the catalog happens to list patterns in.
    A partial key would leave ties broken by list position, which is how
    `High Plank Bird Dog` came out isometric or strength depending on nothing.

    Args:
        patterns: Every movement-pattern family the exercise names.

    Returns:
        The role, or None when no family is in the table — which makes the
        exercise unplaceable rather than silently misfiled.
    """
    roles = [FAMILY_ROLES[pattern] for pattern in patterns if pattern in FAMILY_ROLES]
    if not roles:
        return None
    return min(roles, key=_ordinal)


def unmapped(patterns: tuple[str, ...]) -> tuple[str, ...]:
    """Families this table does not know, for reporting rather than guessing."""
    return tuple(pattern for pattern in patterns if pattern not in FAMILY_ROLES)
