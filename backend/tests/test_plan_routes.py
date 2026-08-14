import json

import pytest
from fastapi.testclient import TestClient

from agents.workout_generator.agent import GenerationRun, Usage, WorkoutPlan
from agents.workout_generator.agent import PlannedExercise
from api.app import app
from api.plan_models import PlanResponse
from constraints.models import Constraint, ConstraintSet, Effect, Origin

COACH = {"X-Coach-Id": "coach_01HXSAM"}
MEMBER = "mbr_01HX9JORDAN"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def fake_plan() -> WorkoutPlan:
    return WorkoutPlan(
        title="t",
        total_seconds=2400,
        main=[
            PlannedExercise(
                concept_id="exercise:Goblet Squat", label="Goblet Squat",
                sets=3, reps="8-10", seconds=2400, rationale="r",
            )
        ],
    )


@pytest.fixture()
def fake_generate(monkeypatch):
    calls: list[dict] = []

    async def fake(prompt, deps, message_history=None):
        calls.append(
            {"prompt": prompt, "deps": deps, "message_history": message_history}
        )
        return GenerationRun(
            plan=fake_plan(),
            messages_json=json.dumps([]).encode(),
            new_messages_json=json.dumps([]).encode(),
            usage=Usage(llm_calls=3, tokens_in=100, tokens_out=50),
        )

    monkeypatch.setattr("api.routes.plans.generate", fake)
    return calls


def test_blank_prompt_is_rejected(client, fake_generate) -> None:
    """An empty request never reaches the agent.

    A blank prompt would burn a full agent run to produce a plan nobody
    asked for.
    """
    response = client.post(
        f"/api/members/{MEMBER}/plans", headers=COACH, json={"prompt": ""}
    )
    assert response.status_code == 422
    assert fake_generate == []


def test_wrong_coach_is_a_404_that_names_no_member(client, fake_generate) -> None:
    """An unauthorized coach learns nothing about the member id space."""
    response = client.post(
        f"/api/members/{MEMBER}/plans",
        headers={"X-Coach-Id": "coach_nobody"},
        json={"prompt": "40 minutes"},
    )
    assert response.status_code == 404
    assert fake_generate == []


def test_create_persists_run_and_trace(client, fake_generate) -> None:
    """A generation leaves a run record and a trace behind.

    Without the run record the plan can never be adjusted; without the
    trace the run never happened as far as observability is concerned.
    """
    response = client.post(
        f"/api/members/{MEMBER}/plans", headers=COACH, json={"prompt": "40 minutes"}
    )
    assert response.status_code == 200
    payload = PlanResponse.model_validate(response.json())
    assert payload.member_id == MEMBER
    assert payload.parent_run_id is None
    assert payload.plan.main[0].concept_id == "exercise:Goblet Squat"

    runtime = client.app.state.runtime
    recorded = runtime.plan_runs.get(payload.run_id)
    assert recorded is not None
    assert recorded.plan is not None
    assert recorded.message_history == "[]"
    trace = runtime.traces.get(payload.run_id)
    assert trace is not None
    assert trace.source == "generator"
    assert trace.totals.llm_calls == 3


def test_adjust_unknown_run_is_a_404(client, fake_generate) -> None:
    """Adjusting a run that aged out says so instead of silently rebuilding."""
    response = client.post(
        f"/api/members/{MEMBER}/plans/run_missing/adjust",
        headers=COACH,
        json={"prompt": "shorter"},
    )
    assert response.status_code == 404
    assert "aged out" in response.json()["detail"]


def test_adjust_replays_the_parent_conversation(client, fake_generate) -> None:
    """An adjustment carries the parent's declared set and message history.

    This is the whole multi-turn contract: without it every adjustment
    rebuilds from nothing and silently drops the coach's standing directives.
    """
    from api.runs import PlanRun

    declared = ConstraintSet(
        constraints=(
            Constraint(
                target="muscle:glutes", effect=Effect.PREFER,
                origin=Origin.COACH, reason="focus",
            ),
        )
    )
    client.app.state.runtime.plan_runs.record(
        PlanRun(
            run_id="run_parent01",
            member_id=MEMBER,
            prompt="original",
            duration_min=40,
            declared_constraints=declared,
            message_history='[{"kind": "request", "parts": [{"part_kind": "user-prompt", "content": "original"}]}]',
        )
    )
    response = client.post(
        f"/api/members/{MEMBER}/plans/run_parent01/adjust",
        headers=COACH,
        json={"prompt": "make it 30 minutes", "duration_min": 30},
    )
    assert response.status_code == 200
    payload = PlanResponse.model_validate(response.json())
    assert payload.parent_run_id == "run_parent01"

    (call,) = fake_generate
    assert call["deps"].declared_constraints == declared
    assert call["message_history"] is not None
    assert len(call["message_history"]) == 1

    child = client.app.state.runtime.plan_runs.get(payload.run_id)
    assert child is not None and child.parent_run_id == "run_parent01"


def test_adjusting_another_members_run_is_a_404(client, fake_generate) -> None:
    """A run id from another member's chart is unreachable."""
    from api.runs import PlanRun

    client.app.state.runtime.plan_runs.record(
        PlanRun(
            run_id="run_other01",
            member_id="mbr_someone_else",
            prompt="x",
            duration_min=40,
        )
    )
    response = client.post(
        f"/api/members/{MEMBER}/plans/run_other01/adjust",
        headers=COACH,
        json={"prompt": "shorter"},
    )
    assert response.status_code == 404


def test_eligibility_reports_the_live_counts(client) -> None:
    """The pre-directive catalog stance for the sample member.

    6 blocked by the clinical envelope, 2 disliked, 10 cautioned survivors
    (12 exercises sit in cautioned patterns; 2 of those are excluded) — the
    numbers the whole safety story hangs on.
    """
    response = client.get(f"/api/members/{MEMBER}/eligibility", headers=COACH)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 50
    assert body["blocked"] == 6
    assert body["disliked"] == 2
    assert body["cautioned"] == 10
    assert body["eligible"] == 43, "one exercise is both blocked and disliked"


def test_build_provenance_projects_every_event_kind() -> None:
    """Each provenance event kind lands in its wire slot, latest retrieval wins."""
    from api.plan_models import build_provenance
    from agents.workout_generator.deps import ProvenanceEvent, ProvenanceKind
    from catalog.eligibility import Exclusion, ExclusionCause
    from constraints.diff import ConstraintDiff

    log = [
        ProvenanceEvent(
            kind=ProvenanceKind.CLINICAL_ENVELOPE,
            constraint_set=ConstraintSet(
                constraints=(
                    Constraint(
                        target="movement_pattern:plyo", effect=Effect.BLOCK,
                        origin=Origin.CLINICAL, reason="contraindicated",
                    ),
                )
            ),
        ),
        ProvenanceEvent(
            kind=ProvenanceKind.CONCEPT_RESOLUTION,
            query="pecs", concept="muscle:chest", confidence=1.0,
        ),
        ProvenanceEvent(
            kind=ProvenanceKind.CONSTRAINT_DECLARATION,
            constraint_set=ConstraintSet(),
            constraint_diff=ConstraintDiff(added=(), removed=(), unchanged=()),
        ),
        ProvenanceEvent(
            kind=ProvenanceKind.CANDIDATE_RETRIEVAL,
            candidates=("exercise:A",),
            exclusions=(
                Exclusion(
                    concept_id="exercise:B", cause=ExclusionCause.BLOCKED,
                    matched_target="movement_pattern:plyo", reason="contraindicated",
                ),
            ),
        ),
        ProvenanceEvent(
            kind=ProvenanceKind.CANDIDATE_RETRIEVAL,
            candidates=("exercise:A", "exercise:C"),
            exclusions=(),
        ),
    ]
    provenance = build_provenance(log, Usage(llm_calls=1, tokens_in=1, tokens_out=1))
    assert provenance.clinical[0].target == "movement_pattern:plyo"
    assert provenance.resolutions[0].query == "pecs"
    assert len(provenance.declarations) == 1
    assert provenance.retrieval is not None
    assert provenance.retrieval.eligible_count == 2, "the latest retrieval wins"
    assert provenance.retrieval.exclusions == ()


def test_build_provenance_of_an_empty_log_is_empty() -> None:
    """No events, no provenance — never an error."""
    from api.plan_models import build_provenance

    provenance = build_provenance([], Usage(llm_calls=0, tokens_in=0, tokens_out=0))
    assert provenance.clinical == ()
    assert provenance.retrieval is None


def eligible_card(**overrides):
    from catalog.cards import GoalOverlap
    from catalog.eligibility import EligibleExercise

    base = dict(
        concept_id="exercise:Kettlebell Goblet Cyclist Squat",
        name="Kettlebell Goblet Cyclist Squat",
        patterns=("movement_pattern:lower push - squat",),
        muscles=("muscle:quads", "muscle:glutes"),
        equipment_required=("equipment:Kettlebell", "equipment:Slant Board"),
        missing_equipment=("equipment:Slant Board",),
        joints=("anatomy:knee",),
        is_reps=True,
        is_duration=True,
        estimated_rep_seconds=3.3,
        is_bilateral=True,
        side=None,
        supports_weight=True,
        disliked=False,
        goal_overlap=(
            GoalOverlap(
                goal_id="g1", text="Build glute strength", priority=1,
                muscle="muscle:glutes",
            ),
        ),
    )
    base.update(overrides)
    return EligibleExercise(**base)


def facts_plan(concept_id: str) -> WorkoutPlan:
    return WorkoutPlan(
        title="t",
        total_seconds=600,
        main=[
            PlannedExercise(
                concept_id=concept_id, label="x", sets=3, reps="8",
                seconds=600, rationale="r",
            )
        ],
    )


def test_exercise_facts_project_the_planned_cards() -> None:
    """The PlanSheet's tag row is built from this projection — muscles and
    equipment as display names, the coach's ask and goal alignment marked."""
    from api.plan_models import build_exercise_facts
    from catalog.eligibility import EligibilityResult

    result = EligibilityResult(
        eligible=(eligible_card(preferred_because=("muscle:glutes",)),),
        excluded=(),
        unmatched_requires=(),
    )
    facts = build_exercise_facts(
        facts_plan("exercise:Kettlebell Goblet Cyclist Squat"), result
    )
    f = facts["exercise:Kettlebell Goblet Cyclist Squat"]
    assert f.muscles == ("quads", "glutes")
    assert f.equipment == ("Kettlebell", "Slant Board")
    assert f.missing_equipment == ("Slant Board",)
    assert f.from_coach == ("glutes",)
    assert f.focus_muscles == ("glutes",), "asked for and goal-aligned"
    assert f.goals[0].muscle == "glutes"
    assert f.goals[0].goal == "Build glute strength"
    assert f.disliked is False


def test_exercise_facts_skip_an_id_with_no_card() -> None:
    """A stale or unknown planned id must not invent facts or crash the
    response projection."""
    from api.plan_models import build_exercise_facts
    from catalog.eligibility import EligibilityResult

    result = EligibilityResult(eligible=(), excluded=(), unmatched_requires=())
    assert build_exercise_facts(facts_plan("exercise:Ghost"), result) == {}


@pytest.fixture()
def fake_generate_real_card(monkeypatch):
    async def fake(prompt, deps, message_history=None):
        return GenerationRun(
            plan=facts_plan("exercise:Kettlebell Goblet Cyclist Squat"),
            messages_json=json.dumps([]).encode(),
            new_messages_json=json.dumps([]).encode(),
            usage=Usage(llm_calls=1, tokens_in=10, tokens_out=5),
        )

    monkeypatch.setattr("api.routes.plans.generate", fake)


def test_response_carries_facts_for_a_real_planned_card(
    client, fake_generate_real_card
) -> None:
    """The console renders tags only if the wire actually ships the facts —
    this is the end-to-end check that it does, against the live graph."""
    response = client.post(
        f"/api/members/{MEMBER}/plans", headers=COACH, json={"prompt": "legs"}
    )
    assert response.status_code == 200
    payload = PlanResponse.model_validate(response.json())
    facts = payload.exercise_facts["exercise:Kettlebell Goblet Cyclist Squat"]
    assert facts.muscles, "the card's muscles reach the sheet"
    assert "Kettlebell" in facts.equipment
