from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from resolve.normalize import Side
from resolve.resolver import Resolution


class ConstraintKind(StrEnum):
    """What a constraint narrows."""

    EQUIPMENT = "equipment"
    EXCLUDED_EXERCISE = "excluded_exercise"
    EXCLUDED_PATTERN = "excluded_pattern"
    FLAGGED_STRUCTURE = "flagged_structure"
    INJURY = "injury"


class Origin(StrEnum):
    """Where a constraint came from, which the trace has to be able to say."""

    STANDING = "standing"
    DIRECTIVE = "directive"


class Op(StrEnum):
    """How a directive changes the standing set."""

    REPLACE = "replace"
    ADD = "add"
    REMOVE = "remove"


class UnappliedReason(StrEnum):
    """Why a directive did not take effect."""

    UNRESOLVED = "unresolved"
    NOT_WAIVABLE = "not_waivable"


# An injury is the entry point to the clinical path, so removing one would
# remove contraindications a clinician authored. Everything else is the
# member's preference or circumstance, which a coach may override for a
# session. See docs/decisions.md, KG1 item 2.
_WAIVABLE: dict[ConstraintKind, bool] = {
    ConstraintKind.EQUIPMENT: True,
    ConstraintKind.EXCLUDED_EXERCISE: True,
    ConstraintKind.EXCLUDED_PATTERN: True,
    ConstraintKind.FLAGGED_STRUCTURE: True,
    ConstraintKind.INJURY: False,
}


class Constraint(BaseModel):
    """One thing narrowing the catalog, and where it came from.

    Origin is kept rather than collapsed to a bare name so the trace can
    distinguish *"no yoga-mat work because you said so this request"* from
    *"because her chart says so"*.
    """

    model_config = ConfigDict(frozen=True)

    kind: ConstraintKind
    value: str
    origin: Origin
    side: Side | None = None
    directive_index: int | None = None

    @property
    def waivable(self) -> bool:
        """Whether a coach may override this for one session."""
        return _WAIVABLE[self.kind]


class Directive(BaseModel):
    """One instruction from this request, already resolved onto the graph.

    The whole `Resolution` is carried rather than just the matched name, so the
    trace gets the pass that fired, the score, and the near-misses for free.
    """

    model_config = ConfigDict(frozen=True)

    index: int
    phrase: str
    op: Op
    kind: ConstraintKind
    resolution: Resolution


class Unapplied(BaseModel):
    """A directive that did not take effect, and why."""

    model_config = ConfigDict(frozen=True)

    directive: Directive
    reason: UnappliedReason

    @property
    def explanation(self) -> str:
        """A sentence a coach can act on."""
        if self.reason is UnappliedReason.UNRESOLVED:
            near = ", ".join(c.name for c in self.directive.resolution.candidates[:3])
            suffix = f" Did you mean: {near}?" if near else ""
            return f"{self.directive.phrase!r} matched nothing in the catalog.{suffix}"
        return (
            f"{self.directive.phrase!r} would waive a clinical constraint, "
            f"which a request cannot do."
        )


class ConstraintSet(BaseModel):
    """Everything narrowing the catalog for one request."""

    model_config = ConfigDict(frozen=True)

    member_id: str
    constraints: tuple[Constraint, ...] = ()

    def of(self, kind: ConstraintKind) -> tuple[Constraint, ...]:
        """Every constraint of one kind, in order."""
        return tuple(c for c in self.constraints if c.kind is kind)

    def values(self, kind: ConstraintKind) -> frozenset[str]:
        """The bare values of one kind, for query parameters."""
        return frozenset(c.value for c in self.of(kind))

    @property
    def available_equipment(self) -> frozenset[str]:
        """Equipment the member has access to for this request."""
        return self.values(ConstraintKind.EQUIPMENT)

    @property
    def injury_ids(self) -> frozenset[str]:
        """Injuries whose clinical rules apply."""
        return self.values(ConstraintKind.INJURY)


class Composition(BaseModel):
    """The result of folding directives onto a member's standing constraints.

    Carrying all three makes the fold a printable data structure rather than
    control flow that happened somewhere.
    """

    model_config = ConfigDict(frozen=True)

    standing: ConstraintSet
    directives: tuple[Directive, ...]
    applied: ConstraintSet
    unapplied: tuple[Unapplied, ...]


def compose(standing: ConstraintSet, directives: tuple[Directive, ...]) -> Composition:
    """Fold this request's directives onto the member's standing constraints.

    Merge semantics live here and nowhere else, so no call site has to decide
    whether an instruction adds to the chart or replaces it.

    Args:
        standing: What the member's record says, from `standing.load_standing`.
        directives: This request's instructions, already resolved.

    Returns:
        The standing set, the directives, the composed result, and any
        directive that did not take effect with the reason.
    """
    constraints = list(standing.constraints)
    unapplied: list[Unapplied] = []

    for directive in directives:
        # Waivability is checked before resolution. Whether a request may
        # dismiss a clinical constraint does not depend on how well its wording
        # matched — reporting "unresolved" here would suggest better phrasing
        # might work, and nothing about the phrasing would.
        if not _WAIVABLE[directive.kind] and directive.op is not Op.ADD:
            unapplied.append(Unapplied(directive=directive, reason=UnappliedReason.NOT_WAIVABLE))
            continue
        if directive.resolution.match is None:
            unapplied.append(Unapplied(directive=directive, reason=UnappliedReason.UNRESOLVED))
            continue

        addition = Constraint(
            kind=directive.kind,
            value=directive.resolution.match.name,
            origin=Origin.DIRECTIVE,
            side=directive.resolution.side,
            directive_index=directive.index,
        )
        if directive.op is Op.REPLACE:
            # "Only dumbbells and a kettlebell" means exactly that, so the
            # chart's list goes. Successive REPLACE directives of one kind
            # accumulate, since together they name one set.
            constraints = [
                c
                for c in constraints
                if c.kind is not directive.kind or c.origin is Origin.DIRECTIVE
            ]
            constraints.append(addition)
        elif directive.op is Op.ADD:
            constraints.append(addition)
        else:
            constraints = [
                c
                for c in constraints
                if not (c.kind is directive.kind and c.value == addition.value)
            ]

    return Composition(
        standing=standing,
        directives=directives,
        applied=ConstraintSet(member_id=standing.member_id, constraints=tuple(constraints)),
        unapplied=tuple(unapplied),
    )
