from pydantic_ai import RunContext

from agents.workout_generator.deps import GeneratorDeps, ProvenanceEvent, ProvenanceKind
from member.snapshot import MemberSnapshot, load_snapshot


def member_snapshot(ctx: RunContext[GeneratorDeps]) -> MemberSnapshot:
    """Read this member's chart: equipment owned, disliked exercises, injuries
    as recorded, goals, and completed-session history by movement pattern.
    Call once, before resolving or planning. Concept_ids here are member
    context, not plannable citations — plan slots still require ids returned
    by resolve_concept."""
    snapshot = load_snapshot(ctx.deps.graph, ctx.deps.member_id)
    ctx.deps.tool_log.append(
        ProvenanceEvent(kind=ProvenanceKind.MEMBER_SNAPSHOT, member=snapshot.member_id)
    )
    return snapshot
