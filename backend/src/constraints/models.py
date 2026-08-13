from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from graph.evidence import EvidencePath


class Effect(StrEnum):
    """What a constraint asks of the plan."""

    AVOID = "avoid"
    PREFER = "prefer"
    REQUIRE = "require"
    BLOCK = "block"
    """Clinical contraindication: excluding, never coach-declarable."""

    CAUTION = "caution"
    """Clinical caution: annotates, neither excluding nor requiring."""

    # LIMIT stays deferred — dosage semantics need per-slot enforcement.


class Origin(StrEnum):
    """Who a constraint speaks for."""

    CLINICAL = "clinical"
    MEMBER = "member"
    COACH = "coach"


EXCLUDING_EFFECTS: frozenset[Effect] = frozenset({Effect.AVOID, Effect.BLOCK})
"""Effects that forbid a target. Validators and eligibility read this
constant, never the enum directly."""

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

    evidence: EvidencePath | None = None
    """The traversal that produced it; clinical constraints only, coach
    constraints carry none. Excluded from key identity like reason."""

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
