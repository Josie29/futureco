from datetime import UTC, datetime

from neo4j import Session
from pydantic import BaseModel, ConfigDict

from graph.build.report import BuildReport, read_report
from safety.filter import FilterResult
from safety.queries import ALL_QUERIES


class RunHeader(BaseModel):
    """What produced a set of verdicts, in PROV-O terms.

    Field names follow the ontology so the mapping is obvious to a reviewer:
    `was_generated_by` is the activity, `was_associated_with` the agent, and
    `used` the entities it drew on. This is a Pydantic model rather than RDF
    because the consumer is a typed API and a dashboard, not a triple store.
    """

    model_config = ConfigDict(frozen=True)

    was_generated_by: str = "safety.filter.run"
    was_associated_with: str
    generated_at_time: datetime
    used_queries: tuple[str, ...]
    used_graph: BuildReport
    """Node and edge counts at the moment of the run — which graph produced
    these verdicts, so a stale verdict can be told from a current one."""


class ProvenanceTrace(BaseModel):
    """A full account of one filter run, readable at three depths.

    The coach reads `headline` on each verdict; a reviewer reads the evidence
    paths; an auditor reads this header plus the constraint fold.
    """

    model_config = ConfigDict(frozen=True)

    header: RunHeader
    result: FilterResult

    def render(self) -> str:
        """Render the run as plain text, for a probe or a log."""
        composition = self.result.composition
        attribution = self.result.attribution
        lines = [
            f"member          {composition.applied.member_id}",
            f"graph           {self.header.used_graph.node_total} nodes, "
            f"{self.header.used_graph.edge_total} edges",
            f"policy          caution={self.result.policy.caution} "
            f"structure={self.result.policy.flagged_structure}",
            "",
            f"standing        {sorted(composition.standing.available_equipment)}",
        ]
        for directive in composition.directives:
            matched = directive.resolution.match
            landed = (
                f"{matched.name} [{matched.label}] via {matched.matched_by}"
                if matched
                else "no match"
            )
            lines.append(f"directive {directive.index}     {directive.op} "
                         f"{directive.kind}: {directive.phrase!r} -> {landed}")
        for unapplied in composition.unapplied:
            lines.append(f"  NOT APPLIED   {unapplied.explanation}")
        if self.result.unresolved_structures:
            lines.append(f"  NO CLOSURE    {list(self.result.unresolved_structures)}")

        lines += [
            "",
            f"removed {attribution.removed}, kept {attribution.kept}",
            f"  per reason    {attribution.per_reason}  (overlapping, sums to "
            f"{sum(attribution.per_reason.values())})",
            f"  attributed    {attribution.attributed}  (sums to {attribution.removed})",
        ]
        if self.result.is_thin:
            lines.append(
                f"  THIN POOL     {len(self.result.eligible)} eligible, mostly from "
                f"{self.result.costliest_constraint}"
            )
        return "\n".join(lines)


def trace(session: Session, result: FilterResult, agent: str = "coach-dashboard") -> ProvenanceTrace:
    """Wrap a filter result with the header describing how it was produced.

    Args:
        session: An open Neo4j session, used only to fingerprint the graph.
        result: The verdicts to describe.
        agent: What asked for them.

    Returns:
        The trace, ready to serialise alongside a plan.
    """
    return ProvenanceTrace(
        header=RunHeader(
            was_associated_with=agent,
            generated_at_time=datetime.now(UTC),
            used_queries=tuple(ALL_QUERIES),
            used_graph=read_report(session),
        ),
        result=result,
    )
