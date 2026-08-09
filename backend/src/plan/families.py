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
    "isometric": FamilyRole(section=Section.MAIN, modality=Modality.STRENGTH, slot=Slot.CORE),
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

def _ordinal(role: FamilyRole) -> tuple[int, int]:
    """Rank one role against another, section first."""
    return (SECTION_ORDER.index(role.section), SLOT_ORDER.index(role.slot))


def role_of(patterns: tuple[str, ...]) -> FamilyRole | None:
    """Decide where one exercise belongs from every family it claims.

    Section dominates, then slot. Every family sharing a section and slot also
    shares a modality, so the key is total over this catalog and shuffling
    `movement_patterns` cannot change a plan — asserted per exercise over every
    permutation in `test_plan_families`, which is what would catch a new family
    breaking that.

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


def deciding_pattern(patterns: tuple[str, ...]) -> str | None:
    """The one family that placed this exercise, of however many it claims.

    What makes the movement the movement it is: *Med Ball Hamstring Walkout*
    is a hip lift that happens to resist rotation, so the hip lift is what
    another exercise would have to share to stand in for it. The other
    families did not place it, and treating them as equals is how a bird dog
    ends up offered as a substitute for a hinge.

    Args:
        patterns: Every movement-pattern family the exercise names.

    Returns:
        The deciding family, or None when none of them is known.
    """
    role = role_of(patterns)
    if role is None:
        return None
    return next(
        pattern
        for pattern in patterns
        if pattern in FAMILY_ROLES and FAMILY_ROLES[pattern] == role
    )


def unmapped(patterns: tuple[str, ...]) -> tuple[str, ...]:
    """Families this table does not know, for reporting rather than guessing."""
    return tuple(pattern for pattern in patterns if pattern not in FAMILY_ROLES)
