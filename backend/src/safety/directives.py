from pydantic import BaseModel, ConfigDict

from graph.schema import NodeLabel
from resolve.resolver import Resolver
from safety.constraints import ConstraintKind, Directive, Op

# What each kind of instruction may resolve onto. Restricting before scoring is
# what stops "squats" reaching the Muscle `quads` when the coach meant a
# movement pattern — see docs/decisions.md, *Resolver* item 1.
_LABELS: dict[ConstraintKind, frozenset[NodeLabel]] = {
    ConstraintKind.EQUIPMENT: frozenset({NodeLabel.EQUIPMENT}),
    ConstraintKind.EXCLUDED_EXERCISE: frozenset({NodeLabel.EXERCISE}),
    ConstraintKind.EXCLUDED_PATTERN: frozenset({NodeLabel.MOVEMENT_PATTERN}),
    ConstraintKind.FLAGGED_STRUCTURE: frozenset({NodeLabel.ANATOMICAL_STRUCTURE}),
    ConstraintKind.INJURY: frozenset({NodeLabel.INJURY}),
}


class Instruction(BaseModel):
    """One structured instruction, before its term is resolved.

    This is the shape an agent tool accepts: an operation, a kind, and a
    phrase. Never a node id, never a weight, never a severity — extraction,
    not decision. There is deliberately no verb for waiving a clinical
    constraint, so no prompt can produce one.
    """

    model_config = ConfigDict(frozen=True)

    op: Op
    kind: ConstraintKind
    phrase: str


def to_directives(resolver: Resolver, instructions: list[Instruction]) -> tuple[Directive, ...]:
    """Resolve each instruction's phrase onto a canonical concept.

    Args:
        resolver: The concept resolver, over the graph's vocabulary.
        instructions: Structured instructions from the caller.

    Returns:
        One directive per instruction, in order, each carrying its whole
        `Resolution` — including a failed one, so `compose` can report it
        rather than silently dropping the instruction.
    """
    return tuple(
        Directive(
            index=index,
            phrase=instruction.phrase,
            op=instruction.op,
            kind=instruction.kind,
            resolution=resolver.resolve(instruction.phrase, _LABELS[instruction.kind]),
        )
        for index, instruction in enumerate(instructions)
    )
