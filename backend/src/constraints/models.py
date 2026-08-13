from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class Effect(StrEnum):
    """What a constraint asks of the plan."""

    AVOID = "avoid"
    PREFER = "prefer"
    REQUIRE = "require"
    # The safety envelope adds BLOCK, CAUTION, LIMIT; clinical exclusions
    # arrive as BLOCK, and AVOID stays the coach-severity exclusion.


class Origin(StrEnum):
    """Who a constraint speaks for. Full enum now so the clinical floor can
    arrive without reshaping the model; v0 stamps COACH only."""

    CLINICAL = "clinical"
    MEMBER = "member"
    COACH = "coach"


EXCLUDING_EFFECTS: frozenset[Effect] = frozenset({Effect.AVOID})
"""Effects that forbid a target. Validators read this constant, never the
enum directly — BLOCK joins here with the envelope, call sites unchanged."""

REQUIRING_EFFECTS: frozenset[Effect] = frozenset({Effect.REQUIRE})
"""Effects that demand a target's presence."""


class Constraint(BaseModel):
    """One directive: target x effect x origin."""

    model_config = ConfigDict(frozen=True)

    target: str
    """A concept_id in the resolver's namespace:name currency, any namespace."""

    effect: Effect
    origin: Origin
    reason: str = ""
    """The words behind it, e.g. "coach said no overhead work". Carried for
    the trace and retry messages; excluded from diff identity."""

    @property
    def key(self) -> tuple[str, str, str]:
        """What makes two declarations the same constraint."""
        return (self.target, self.effect.value, self.origin.value)


class ConstraintSet(BaseModel):
    """The full set in force, replaced wholesale on each declaration."""

    model_config = ConfigDict(frozen=True)

    constraints: tuple[Constraint, ...] = ()

    def of(self, effect: Effect) -> tuple[Constraint, ...]:
        """Constraints carrying one effect."""
        return tuple(c for c in self.constraints if c.effect is effect)

    def targets(self, *effects: Effect) -> frozenset[str]:
        """Every target any of the given effects touches."""
        return frozenset(c.target for c in self.constraints if c.effect in effects)
