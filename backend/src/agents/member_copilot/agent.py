from pydantic_ai import Agent

from agents.member_copilot.belt import toolset
from agents.member_copilot.deps import CopilotDeps
from settings import settings

# Placeholder until the copilot migrates from the SDK tool_runner
# (src/copilot/agent.py, still live). Its answer schema, citation allowlist
# and degraded path carry over as output_type + output validators here.
COPILOT_SYSTEM = """\
You answer a coach's questions about one member. Placeholder — the live
prompt is in src/copilot/agent.py until this package replaces it.
"""


MODEL = f"anthropic:{settings.anthropic_model}"
"""Bound at run time, not construction — same keyless-import rule as the
generator's MODEL."""


copilot = Agent(
    deps_type=CopilotDeps,
    instructions=COPILOT_SYSTEM,
    toolsets=[toolset],
)
