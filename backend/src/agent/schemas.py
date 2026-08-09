from pydantic import BaseModel, ConfigDict, Field

from safety.directives import Instruction


class ExtractionResult(BaseModel):
    """What one coach utterance becomes.

    Strings and enums only, mirroring `Instruction`: no node ids, no weights,
    no severities. The model says what it heard; the resolver decides what
    those words mean and the filter decides what follows. There is deliberately
    no field here that could waive a clinical constraint.
    """

    model_config = ConfigDict(frozen=True)

    instructions: list[Instruction] = Field(default_factory=list)
    """Constraints the utterance places on the session."""

    emphasis: list[str] = Field(default_factory=list)
    """Muscles the coach asked to work, which widen rather than narrow and so
    are not constraints. Resolved against Muscle downstream."""

    unmapped: list[str] = Field(default_factory=list)
    """Anything heard that fits none of the above. Surfaced to the coach and
    never fed to the filter — how the model says "she mentioned she is tired"
    without inventing a constraint kind for it."""
