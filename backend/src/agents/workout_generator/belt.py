from pydantic_ai.toolsets import FunctionToolset

from agents.workout_generator.deps import GeneratorDeps
from agents.workout_generator.tools.resolve import resolve_concept

# The roster: if a tool is not in this list, the agent does not have it.
#
# The rest of the belt, in build order — each tool's contract is in the
# agentic-migration design note:
#
#   tools/snapshot.py     member_snapshot()      KG2 read: injuries with
#                                                status, equipment, dislikes,
#                                                goals, recent patterns
#   tools/constraints.py  declare_constraints()  full coach set, idempotent;
#                                                recompose -> re-filter -> diff
#   tools/candidates.py   eligible_exercises()   verdict-annotated candidates;
#                                                blocked never selectable
#                         expand_anatomy()       directed part_of closure
#                         explain_exclusion()    EvidencePath behind a verdict
#                         find_substitutes()     pattern siblings ∩ eligible
#   tools/checks.py       check_plan()           validator stack as a dry run
toolset: FunctionToolset[GeneratorDeps] = FunctionToolset(
    tools=[
        resolve_concept,
    ]
)
