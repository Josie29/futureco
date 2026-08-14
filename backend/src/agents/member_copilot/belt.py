from pydantic_ai.toolsets import FunctionToolset

from agents.member_copilot.deps import CopilotDeps

# Empty roster until the copilot migrates: the nine tool_runner tools in
# src/copilot/agent.py move into tools/ modules by family and get listed here.
toolset: FunctionToolset[CopilotDeps] = FunctionToolset(tools=[])
