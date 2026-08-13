from pydantic import BaseModel, ConfigDict

from resolver.models import ResolutionResult


class MemberPriors(BaseModel):
    """The slice of one member's context that legitimately re-ranks resolution.

    Loaded from KG2 (or the member's own graph, once the per-member split
    lands) before an agent run and carried in the run's deps. Deliberately
    narrow: priors may reorder candidates, never mint or veto them — safety
    verdicts belong to the filter, not the resolver.
    """

    model_config = ConfigDict(frozen=True)

    injured_structure_ids: tuple[str, ...] = ()
    """Concept ids of structures with live documented injuries. "shoulder"
    from a coach whose member has a documented left-shoulder impingement
    should prefer the documented reading."""

    owned_equipment_ids: tuple[str, ...] = ()
    """"bands" resolves to the miniband she owns, not the barbell she doesn't."""

    dominant_side: str | None = None
    """Laterality prior, when the record states one."""


def apply_member_prior(result: ResolutionResult, member: MemberPriors) -> ResolutionResult:
    """Re-rank a KG1 resolution against one member's context.

    Runs after `core.resolve` and never before it: the base pass stays a pure
    function of KG1, and this step may promote an alternative the member's
    record makes more plausible. A promotion is a re-ordering with provenance,
    not a new match — confidence is adjusted transparently and the original
    ranking survives in `alternatives`.

    Args:
        result: What the 3-pass core produced.
        member: The member's re-ranking priors.

    Returns:
        The result, re-ranked where the member's record justifies it.

    Raises:
        NotImplementedError: Scaffolding; not implemented yet.
    """
    raise NotImplementedError
