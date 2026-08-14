from dataclasses import dataclass, field

from neo4j import Session

# The member copilot's migration onto Pydantic AI comes after the generator:
# src/copilot (SDK tool_runner) still serves the live route and stays
# untouched until this package can replace it wholesale. Scaffolding only.


@dataclass
class CopilotDeps:
    """Everything one copilot run carries that isn't conversation.

    Grows when the migration starts: retrieval state, the citation allowlist
    of message ids returned this run, chart request capture.
    """

    member_id: str
    coach_id: str
    graph: Session
    tool_log: list = field(default_factory=list)
