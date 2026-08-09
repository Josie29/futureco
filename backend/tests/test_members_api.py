import pytest
from fastapi.testclient import TestClient

from api.app import app
from graph.build.member import load_member_context
from settings import settings

# Integration: the route, the queries and the graph together, hit with a
# realistic request. Stubbing the session here would test the assembly against
# rows this file invented, which proves nothing about whether the Cypher
# matches the graph the build actually wrote.

COACH = "coach_01HXSAM"
MEMBER = "mbr_01HX9JORDAN"
HEADERS = {"X-Coach-Id": COACH}


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as open_client:
        yield open_client


@pytest.fixture(scope="module")
def member(client: TestClient) -> dict:
    response = client.get(f"/api/members/{MEMBER}", headers=HEADERS)
    assert response.status_code == 200
    return response.json()


def test_sign_in_list_needs_no_identity(client: TestClient) -> None:
    """`/api/coaches` is the screen reached before there is a coach to send.

    Requiring the header here would make signing in impossible. It returns ids
    and names only — no member data hangs off it.
    """
    response = client.get("/api/coaches")
    assert response.status_code == 200
    assert {c["id"] for c in response.json()} == {COACH}


def test_member_endpoints_refuse_an_unknown_coach(client: TestClient) -> None:
    """A member id in a URL is not authority to read that member.

    This is the whole reason `Coach -coaches-> Member` is an edge rather than a
    property. Without the check, the console's mock login is decoration and
    anyone who can guess an id reads a clinical record.
    """
    for path in (f"/api/members/{MEMBER}", f"/api/members/{MEMBER}/messages"):
        response = client.get(path, headers={"X-Coach-Id": "coach_someone_else"})
        assert response.status_code == 404, path


def test_missing_header_is_rejected(client: TestClient) -> None:
    """No coach header means no answer, rather than a default identity."""
    assert client.get(f"/api/members/{MEMBER}").status_code == 422


def test_unpopulated_member_is_404_not_an_empty_page(client: TestClient) -> None:
    """The filler roster carries no context, and says so.

    An empty `MemberView` would render a page full of zeroes that reads as
    clinical fact — no injuries, no goals, perfect adherence. 404 lets the
    console show a designed empty state instead.
    """
    roster = client.get("/api/members", headers=HEADERS).json()
    filler = next(entry for entry in roster if not entry["has_context"])
    response = client.get(f"/api/members/{filler['id']}", headers=HEADERS)
    assert response.status_code == 404


def test_roster_leads_with_the_member_needing_attention(client: TestClient) -> None:
    """Sorted by who needs work, because that is the order a coach works in.

    Jordan is the only populated member and the only one at risk. If the
    ordering reverted to alphabetical she would sit third behind two members
    with nothing wrong.
    """
    roster = client.get("/api/members", headers=HEADERS).json()
    assert roster[0]["id"] == MEMBER
    assert roster[0]["needs_attention"] is True
    assert roster[0]["has_context"] is True


def test_roster_carries_no_clinical_detail(client: TestClient) -> None:
    """The roster renders for every member at once, so it stays metadata.

    Goals, injury notes and history belong behind the per-member check. A
    joint name is the one clinical hint it carries, deliberately, so a coach
    can see who is carrying something without opening each record.
    """
    roster = client.get("/api/members", headers=HEADERS).json()
    allowed = {
        "id", "name", "initials", "has_context",
        "last_session_on", "adherence_pct", "injury_label", "needs_attention",
    }
    for entry in roster:
        assert set(entry) == allowed


def test_derived_figures_match_the_record(member: dict) -> None:
    """Everything computed agrees with `member-context.json`.

    These four are all derived rather than stored, and each is read off the
    graph by a different query. Drift in any one of them shows on the header as
    a number a coach would act on.
    """
    context = load_member_context(settings.member_context_path)
    completed = [s for s in context.workout_history if s.completed]

    assert member["as_of"] == context.coach_brief.generated_for.isoformat()
    assert member["typical_session_min"] == round(
        sum(s.duration_min for s in completed) / len(completed)
    )
    assert member["adherence_pct"] == [w.pct for w in context.adherence.weekly_completion_pct]
    assert member["sessions_planned_this_week"] == context.preferences.training_days_per_week


def test_measured_goal_reports_progress_the_graph_derived(member: dict) -> None:
    """The sleep goal carries a measure, and the dated goals carry countdowns.

    Before `measured_by`, this field was computed in the console from a
    hardcoded seven-hour target. It now comes from the metric's own band, which
    is why a second member with a different target needs no code change.
    """
    by_id = {goal["id"]: goal for goal in member["goals"]}
    sleep = by_id["goal_sleep"]
    assert sleep["days_left"] is None
    assert sleep["measure"] is not None and sleep["measure"].startswith("6.3 h")
    assert sleep["shortfall"] == "0.7 h short"

    dated = by_id["goal_strength"]
    assert dated["days_left"] is not None and dated["measure"] is None


def test_injury_summary_is_read_from_the_clinical_edges(member: dict) -> None:
    """The constraint panel says what the graph rules out, not authored copy.

    Authored text drifts: it would keep describing the old rules after a
    contraindication changed, and the panel would then describe a graph it no
    longer matches.
    """
    injuries = next(c for c in member["constraints"] if c["kind"] == "injuries")
    assert "cardio - plyometric" in injuries["summary"]
    assert all(item["locked"] for item in injuries["items"])


def test_churn_is_derived_and_carries_its_reasons(member: dict) -> None:
    """The level and both supportable reasons, not the stored conclusion."""
    context = load_member_context(settings.member_context_path)
    churn = member["churn_risk"]
    assert churn["level"] == context.coach_brief.churn_risk.level
    assert len(churn["reasons"]) == 2
    assert "login" not in " ".join(churn["reasons"]).lower()


def test_messages_are_oldest_first_with_attachments(client: TestClient) -> None:
    """Reading order, and the attachment survives the round trip through Neo4j.

    Attachments are stored as parallel arrays because Neo4j properties hold
    primitives; if the zip went wrong they would silently vanish rather than
    error, and the Messages tab would lose the photo she sent.
    """
    messages = client.get(f"/api/members/{MEMBER}/messages", headers=HEADERS).json()
    assert [m["ts"] for m in messages] == sorted(m["ts"] for m in messages)
    # `from`, not `author` — the console and the source data both use that key,
    # and Python's keyword is the only reason the field is named differently.
    assert {m["from"] for m in messages} == {"member", "coach"}

    with_files = [m for m in messages if m["attachments"]]
    assert len(with_files) == 1
    assert with_files[0]["attachments"][0]["caption"].startswith("Home setup photo")
    assert with_files[0]["attachments"][0]["url"] is None


def test_copilot_thread_opens_on_the_brief(client: TestClient) -> None:
    """The thread arrives already answered, so retrieval runs before any typing.

    frontend-spec.md cut the brief as a dashboard panel because ASSESSMENT.md:71
    assigns it to the copilot. Delivered as the opening turn it proves the graph
    on first paint rather than describing it — if this returns an empty thread,
    the console's most-read surface starts blank.
    """
    thread = client.get(f"/api/members/{MEMBER}/copilot", headers=HEADERS)
    assert thread.status_code == 200
    turns = thread.json()
    assert len(turns) == 1
    assert turns[0]["from"] == "copilot"
    assert turns[0]["paragraphs"], "the brief must carry content"


def test_copilot_refuses_a_member_off_this_roster(client: TestClient) -> None:
    """The copilot reads a clinical record, so it takes the same check as the rest."""
    for call in (
        lambda h: client.get(f"/api/members/{MEMBER}/copilot", headers=h),
        lambda h: client.post(f"/api/members/{MEMBER}/copilot", headers=h, json={"prompt": "hi"}),
    ):
        assert call({"X-Coach-Id": "coach_someone_else"}).status_code == 404
