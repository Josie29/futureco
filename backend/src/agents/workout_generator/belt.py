from pydantic_ai.toolsets import FunctionToolset

from agents.workout_generator.deps import GeneratorDeps
from agents.workout_generator.tools.constraints import declare_constraints
from agents.workout_generator.tools.resolve import resolve_concept
from agents.workout_generator.tools.snapshot import member_snapshot

# The roster: if a tool is not in this list, the agent does not have it.
#
# The rest of the belt, in build order — each tool's contract is in the
# agentic-migration design note:
#   tools/candidates.py   eligible_exercises()   verdict-annotated candidates;
#                                                blocked never selectable
#                         expand_anatomy()       directed part_of closure
#                         explain_exclusion()    EvidencePath behind a verdict
#                         find_substitutes()     pattern siblings ∩ eligible
#   tools/checks.py       check_plan()           validator stack as a dry run
toolset: FunctionToolset[GeneratorDeps] = FunctionToolset(
    tools=[
        member_snapshot,
        resolve_concept,
        declare_constraints,
    ]
)
