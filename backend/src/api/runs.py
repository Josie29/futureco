from collections import OrderedDict
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from safety.directives import Instruction


class PlanRun(BaseModel):
    """What one generation was asked for, kept so the next one can build on it.

    `instructions` is the **accumulated** fold, not this utterance's own: an
    adjustment stores its parent's instructions plus whatever it added, so
    refining a plan is one lookup rather than a walk up the chain. `prompt`
    stays this run's own words, because the trail is what a coach reads and
    concatenated prose is not a sentence anyone said.

    Structured instructions are stored rather than the prose they came from
    because resolution is deterministic and extraction is not. Re-extracting an
    earlier utterance on every adjustment would let a model reread a constraint
    the coach set three refinements ago — `decisions.md`, *Agent runtime* 6
    records that the same sentence can land differently across runs. Freezing
    the structured half is what stops a refinement quietly rewriting history.
    """

    model_config = ConfigDict(frozen=True)

    run_id: str
    parent_run_id: str | None = None
    member_id: str
    prompt: str
    duration_min: int
    instructions: tuple[Instruction, ...] = ()
    emphasis: tuple[str, ...] = ()


# Agentic migration: `accumulate` — the cross-utterance instruction fold — is
# gone. The planning agent holds conversation state itself and declares the
# full constraint set idempotently, so there is no edit algebra to fold. The
# lineage store below survives: an adjustment still needs to find its parent.


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
