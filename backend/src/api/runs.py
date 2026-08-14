from collections import OrderedDict
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from agents.workout_generator.agent import WorkoutPlan
from constraints.models import ConstraintSet


class PlanRun(BaseModel):
    """What one generation was and produced, kept so the next can build on it.

    An adjustment replays `message_history` (the pydantic-ai conversation)
    and seeds its deps with `declared_constraints`, so re-declaration diffs
    stay honest across turns.
    """

    model_config = ConfigDict(frozen=True)

    run_id: str
    parent_run_id: str | None = None
    member_id: str
    prompt: str
    duration_min: int
    declared_constraints: ConstraintSet = ConstraintSet()
    message_history: str = ""
    """The run's full pydantic-ai message history, as JSON text."""

    plan: WorkoutPlan | None = None


class PlanRunStore(Protocol):
    """Where generation requests are kept, so an adjustment can find its parent."""

    def record(self, run: PlanRun) -> None: ...

    def get(self, run_id: str) -> PlanRun | None: ...

    def lineage(self, run_id: str) -> list[PlanRun]: ...
    """Every run from the root of the chain down to this one, oldest first."""


class InMemoryPlanRunStore:
    """A bounded map of recent runs.

    The fallback for a process with no database — `uv run pytest`, or a bare
    `uvicorn` outside compose. Bounded for the same reason the trace ring is:
    an unbounded dict inside a long-running API is a memory leak with a nice
    name. A run that ages out cannot be refined, which the route reports rather
    than silently rebuilding from nothing.
    """

    def __init__(self, capacity: int = 500) -> None:
        self._runs: OrderedDict[str, PlanRun] = OrderedDict()
        self._capacity = capacity

    def record(self, run: PlanRun) -> None:
        self._runs[run.run_id] = run
        while len(self._runs) > self._capacity:
            self._runs.popitem(last=False)

    def get(self, run_id: str) -> PlanRun | None:
        return self._runs.get(run_id)

    def lineage(self, run_id: str) -> list[PlanRun]:
        """Walk parent pointers up to the root, then return the chain in order.

        Stops on a missing parent rather than failing: a chain whose head has
        aged out is still a real trail, just a shorter one than it was.
        """
        chain: list[PlanRun] = []
        seen: set[str] = set()
        current = self._runs.get(run_id)
        while current is not None and current.run_id not in seen:
            seen.add(current.run_id)
            chain.append(current)
            current = self._runs.get(current.parent_run_id) if current.parent_run_id else None
        return list(reversed(chain))
