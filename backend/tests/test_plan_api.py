import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.errors import register_error_handlers
from api.plan_models import FilterCause, VerdictLabel
from api.routes import plans as plan_routes
from graph.driver import open_driver
from resolve.resolver import Resolver
from resolve.vocabulary import Vocabulary
from settings import settings

MEMBER = "mbr_01HX9JORDAN"


class _Runtime:
    """The slice of the app's runtime these routes actually use."""

    def __init__(self, driver, resolver) -> None:
        self.driver = driver
        self.resolver = resolver


@pytest.fixture(scope="module")
def client():
    """A client over the plan router alone.

    Composed from the router rather than importing `api.app`, which pulls in
    the lifespan and with it an 87 MB ONNX download. Routing, projection and
    failure shapes are all true without it — the same reason
    `test_graph_api.py` does this.
    """
    driver = open_driver()
    with driver.session() as session:
        resolver = Resolver(Vocabulary.load(session, settings.aliases_path))

    app = FastAPI()
    register_error_handlers(app)
    app.include_router(plan_routes.router, prefix="/api")
    app.state.runtime = _Runtime(driver, resolver)
    try:
        yield TestClient(app)
    finally:
        driver.close()


@pytest.fixture(scope="module")
def plan(client):
    """One generated plan, at the member's preferred session length."""
    response = client.post(f"/api/members/{MEMBER}/plans", json={"duration_min": 50})
    assert response.status_code == 200, response.text
    return response.json()


class TestContract:
    """The shapes `web/src/types/index.ts` declares.

    The console is built against that file and its client is mock-backed, so
    nothing else holds these two in step. A field renamed here is a blank
    panel there, with no error anywhere in between.
    """

    def test_the_payload_carries_every_declared_field(self, plan) -> None:
        """`WorkoutPlan` in the console's types, field for field."""
        assert set(plan) == {
            "run_id",
            "parent_run_id",
            "prompt",
            "title",
            "day_label",
            "requested_minutes",
            "estimated_minutes",
            "exercises",
            "trace",
        }

    def test_every_exercise_carries_every_declared_field(self, plan) -> None:
        """`PlanExercise`, which the plan sheet renders directly."""
        for exercise in plan["exercises"]:
            assert set(exercise) == {
                "id",
                "name",
                "block",
                "sets",
                "reps",
                "duration_sec",
                "rest_sec",
                "per_side",
                "minutes",
                "muscles",
                "equipment",
                "verdict",
                "note",
                "why",
            }

    def test_the_trace_carries_every_declared_field(self, plan) -> None:
        """`ProvenanceTrace`, which the Traces tab renders."""
        assert set(plan["trace"]) == {
            "run_id",
            "generated_at",
            "catalogue_total",
            "eligible",
            "prescribed",
            "stages",
            "resolved",
            "unresolved",
            "filtered",
        }

    def test_a_reason_serialises_as_the_console_expects(self, plan) -> None:
        """`Reason` mirrors `Signal`, so a structured path travels intact.

        The console renders `detail` and opens `path` behind a disclosure. A
        pre-rendered string here would make the API compose prose for half its
        own output.
        """
        reason = plan["exercises"][0]["why"][0]
        assert set(reason) == {"kind", "detail", "path", "annotation"}
        assert set(reason["path"]) == {"entry", "hops"}


class TestContent:
    """That the numbers on the wire are the ones the graph produced."""

    def test_the_counts_reconcile(self, plan) -> None:
        """The sheet prints "50 in the library, 17 today, 13 in this session".

        Three numbers a coach can check against each other, so they have to
        come from one arithmetic rather than three.
        """
        trace = plan["trace"]
        assert trace["catalogue_total"] == 50
        assert trace["eligible"] == 17
        assert trace["prescribed"] == len(plan["exercises"])

    def test_the_funnel_ends_where_the_plan_does(self, plan) -> None:
        """A stage list that does not land on the prescribed count is fiction.

        Built from the attributed removals rather than the per-reason ones,
        which overlap — a funnel from those would end below zero.
        """
        stages = plan["trace"]["stages"]
        assert stages[0]["remaining"] == 50
        assert stages[-1]["remaining"] == plan["trace"]["prescribed"]
        assert [s["remaining"] for s in stages] == sorted(
            (s["remaining"] for s in stages), reverse=True
        )

    def test_every_dropped_movement_is_listed_with_its_cause(self, plan) -> None:
        """"Every dropped movement, not a sample. Counts must reconcile."

        The console groups these into five buckets and shows the totals beside
        the builder's. A truncated list makes the two disagree.
        """
        filtered = plan["trace"]["filtered"]
        assert len(filtered) == 50 - plan["trace"]["eligible"]
        assert {row["cause"] for row in filtered} <= {c.value for c in FilterCause}

    def test_no_scheduled_movement_is_marked_excluded(self, plan) -> None:
        """`EXCLUDED` labels the dropped list, never a block in the session."""
        assert {e["verdict"] for e in plan["exercises"]} <= {
            VerdictLabel.CLEARED.value,
            VerdictLabel.CAUTION.value,
        }

    def test_a_cautioned_block_carries_a_note(self, plan) -> None:
        """A down-ranked movement in the plan needs its reason on the surface.

        `note` is what the sheet shows without expanding anything, so a
        cautioned block with none reads as unremarkable.
        """
        cautioned = [e for e in plan["exercises"] if e["verdict"] == VerdictLabel.CAUTION.value]
        assert cautioned
        assert all(e["note"] for e in cautioned)

    def test_goal_muscles_are_flagged(self, plan) -> None:
        """The sheet marks which muscles a movement trains toward a goal."""
        tags = [tag for e in plan["exercises"] for tag in e["muscles"]]
        assert any(tag["is_goal_target"] for tag in tags)


class TestDisabled:
    """The builder's per-item switches."""

    def test_switching_off_equipment_narrows_the_pool(self, client) -> None:
        """A switch that changes nothing is a broken control.

        The builder tells the coach whether an item affects the pool or only
        the ranking, so an equipment switch has to move the count.
        """
        before = client.get(f"/api/members/{MEMBER}/eligibility").json()
        after = client.get(
            f"/api/members/{MEMBER}/eligibility",
            params={"disabled": ["equipment:Dumbbell"]},
        ).json()
        assert after["available"] < before["available"]

    def test_an_injury_cannot_be_switched_off(self, client) -> None:
        """The console renders injury items locked; the API must refuse them too.

        A client that ignored the flag, or a hand-made request, must not get a
        plan built around a waived contraindication. `injury` is not in the
        accepted map at all, so the request cannot even name it.
        """
        response = client.post(
            f"/api/members/{MEMBER}/plans",
            json={"duration_min": 50, "disabled": ["injury:inj_knee_left"]},
        )
        assert response.status_code == 422
        assert "switched off" in response.json()["detail"]

    def test_a_switched_off_item_is_reported_as_an_exclusion(self, client) -> None:
        """The console groups resolved phrases by intent.

        "Only dumbbells" narrows toward the dumbbell; switching the dumbbell
        off removes everything needing one. Same constraint kind, opposite
        effect — reading intent off the kind alone filed both under focus.
        """
        response = client.post(
            f"/api/members/{MEMBER}/plans",
            json={"duration_min": 50, "disabled": ["equipment:Yoga Mat"]},
        )
        resolved = response.json()["trace"]["resolved"]
        assert [row["phrase"] for row in resolved] == ["Yoga Mat"]
        assert resolved[0]["intent"] == "exclude"
        assert resolved[0]["pass"] == "exact"

    def test_an_unknown_member_is_a_404(self, client) -> None:
        """Only Jordan has context. An empty plan would look like a thin one."""
        response = client.post("/api/members/nobody/plans", json={"duration_min": 50})
        assert response.status_code == 404


def test_eligibility_matches_the_plans_own_trace(client, plan) -> None:
    """The builder's count and the sheet's funnel must agree.

    They are computed by different endpoints from the same filter, and the
    console shows them on the same screen.
    """
    counts = client.get(f"/api/members/{MEMBER}/eligibility").json()
    assert counts["total"] == plan["trace"]["catalogue_total"]
    assert counts["available"] == plan["trace"]["eligible"]
    assert sum(counts["excluded_by"].values()) == len(plan["trace"]["filtered"])


def test_a_plan_needs_no_prompt_and_no_api_key(client) -> None:
    """The whole generator runs with no language model in it.

    This is the demo insurance policy and the path the CLI probe and the
    README's worked examples take: instructions in, plan out, nothing
    generated.
    """
    response = client.post(f"/api/members/{MEMBER}/plans", json={"duration_min": 30})
    assert response.status_code == 200
    assert response.json()["prompt"] == ""
    assert response.json()["exercises"]
