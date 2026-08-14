import functools
import time
from collections.abc import Callable

from pydantic_ai import RunContext
from pydantic_ai.toolsets import FunctionToolset

from agents.workout_generator.deps import GeneratorDeps
from agents.workout_generator.tools.candidates import get_eligible_exercises
from agents.workout_generator.tools.constraints import declare_constraints
from agents.workout_generator.tools.resolve import resolve_concept
from agents.workout_generator.tools.snapshot import member_snapshot


def _timed[**P, R](tool: Callable[P, R]) -> Callable[P, R]:
    """Stamp real timings onto the provenance events one tool call appends.

    Timing lives here rather than in the tools so a tool stays a pure
    decision-maker; `functools.wraps` preserves the signature pydantic-ai
    builds the tool schema from.

    Args:
        tool: A sync tool taking a RunContext[GeneratorDeps] first.

    Returns:
        The tool, with every event it logs carrying started_ms/duration_ms
        offset from the run's start (or from this call, when the deps carry
        no anchor — a bare-tool test).
    """

    @functools.wraps(tool)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        ctx: RunContext[GeneratorDeps] = args[0]  # pyright: ignore[reportAssignmentType]
        log = ctx.deps.tool_log
        before = len(log)
        began = time.perf_counter()
        try:
            return tool(*args, **kwargs)
        finally:
            anchor = ctx.deps.run_began or began
            started_ms = round((began - anchor) * 1000, 2)
            duration_ms = round((time.perf_counter() - began) * 1000, 2)
            for i in range(before, len(log)):
                log[i] = log[i].model_copy(
                    update={"started_ms": started_ms, "duration_ms": duration_ms}
                )

    return wrapper


# The roster: if a tool is not in this list, the agent does not have it.
#
# The rest of the belt, in build order — each tool's contract is in the
# agentic-migration design note:
#   tools/anatomy.py      expand_anatomy()       directed part_of closure
#   tools/candidates.py   find_substitutes()     pattern siblings ∩ eligible
#   tools/checks.py       check_plan()           validator stack as a dry run
# sequential=True: the tools share one neo4j Session, which is not
# thread-safe, and pydantic-ai otherwise runs sync tools in parallel
# executor threads.
toolset: FunctionToolset[GeneratorDeps] = FunctionToolset(
    tools=[
        _timed(member_snapshot),
        _timed(resolve_concept),
        _timed(declare_constraints),
        _timed(get_eligible_exercises),
    ],
    sequential=True,
)
