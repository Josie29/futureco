from pydantic import BaseModel, ConfigDict

from constraints.models import Constraint, ConstraintSet


class ConstraintDiff(BaseModel):
    """What one declaration changed. `removed` is the drop-visibility the
    idempotent contract promises: omission is deletion, and deletion is shown."""

    model_config = ConfigDict(frozen=True)

    added: tuple[Constraint, ...]
    removed: tuple[Constraint, ...]
    unchanged: tuple[Constraint, ...]


def diff(previous: ConstraintSet, declared: ConstraintSet) -> ConstraintDiff:
    """Partition a declaration against the set it replaces.

    Keys on `Constraint.key`, so a reworded reason reads as unchanged and
    duplicate keys within one declaration collapse. Deterministic order.

    Args:
        previous: The set in force before this declaration.
        declared: The newly declared set.

    Returns:
        The partition, each part sorted by key.
    """
    before = {c.key: c for c in previous.constraints}
    after = {c.key: c for c in declared.constraints}
    return ConstraintDiff(
        added=tuple(
            sorted((c for k, c in after.items() if k not in before), key=lambda c: c.key)
        ),
        removed=tuple(
            sorted((c for k, c in before.items() if k not in after), key=lambda c: c.key)
        ),
        unchanged=tuple(
            sorted((c for k, c in after.items() if k in before), key=lambda c: c.key)
        ),
    )
