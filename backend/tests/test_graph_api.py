from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from neo4j.exceptions import ServiceUnavailable

from api.deps import get_session
from api.main import app

_EDGE_RECORDS: list[dict[str, str]] = [
    {
        "from_id": "ex1",
        "from_label": "Exercise",
        "rel": "requires",
        "to_id": "eq_db",
        "to_label": "Equipment",
    },
    {
        "from_id": "ex2",
        "from_label": "Exercise",
        "rel": "requires",
        "to_id": "eq_bb",
        "to_label": "Equipment",
    },
    {
        "from_id": "mem1",
        "from_label": "Member",
        "rel": "has",
        "to_id": "eq_db",
        "to_label": "Equipment",
    },
    # A label outside the schema enums, as a hand-edited store would hold.
    {
        "from_id": "x1",
        "from_label": "Sponsor",
        "rel": "has",
        "to_id": "eq_db",
        "to_label": "Equipment",
    },
]


class _FakeResult:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self._records = records

    def __iter__(self):
        return iter(self._records)

    def single(self) -> dict[str, Any] | None:
        return self._records[0] if self._records else None


class _FakeSession:
    """Stands in for a Neo4j session, answering the two queries by shape."""

    def __init__(self, node_total: int = 5) -> None:
        self._node_total = node_total

    def run(self, query: str, **_: Any) -> _FakeResult:
        if "count(n)" in query:
            return _FakeResult([{"c": self._node_total}])
        return _FakeResult(_EDGE_RECORDS)


class _UnreachableSession:
    def run(self, query: str, **_: Any) -> _FakeResult:
        raise ServiceUnavailable("Unable to retrieve routing information")


@pytest.fixture
def client() -> Iterator[TestClient]:
    def override() -> Iterator[_FakeSession]:
        yield _FakeSession()

    app.dependency_overrides[get_session] = override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_scope_narrows_the_counts(client: TestClient):
    """The three tabs must return three different answers.

    Equipment is 2 in the catalog and 1 once scoped to what the member owns.
    If the scope parameter were ignored the tab would silently show KG1 under
    every label.
    """
    kg1 = client.get("/api/graph/schema", params={"scope": "kg1"}).json()
    kg2 = client.get("/api/graph/schema", params={"scope": "kg2"}).json()

    def equipment(payload: dict[str, Any]) -> int:
        return next(n["count"] for n in payload["node_types"] if n["label"] == "Equipment")

    assert equipment(kg1) == 2
    assert equipment(kg2) == 1
    assert kg1["totals"]["edges"] == 2
    assert kg2["totals"]["edges"] == 1


def test_default_scope_is_the_union(client: TestClient):
    """Opening the tab with no scope should show the whole graph rather than
    an arbitrary half of it.
    """
    payload = client.get("/api/graph/schema").json()

    assert payload["scope"] == "both"
    assert payload["totals"]["edges"] == 3


def test_rows_outside_the_schema_enums_are_skipped(client: TestClient):
    """The wire contract types labels to the enum, so an unknown one has
    nowhere to go. It must not crash the endpoint — a store with one stray
    node would otherwise take the whole tab down.
    """
    payload = client.get("/api/graph/schema").json()

    assert all(n["label"] != "Sponsor" for n in payload["node_types"])
    assert payload["totals"]["edges"] == 3


def test_unreachable_database_answers_with_the_fix(client: TestClient):
    """This is the first surface that needs Neo4j running to render anything.

    A bare 500 leaves a reviewer staring at an empty canvas; the response has
    to name the command that fixes it.
    """

    def override() -> Iterator[_UnreachableSession]:
        yield _UnreachableSession()

    app.dependency_overrides[get_session] = override
    response = client.get("/api/graph/schema")

    assert response.status_code == 503
    assert "docker compose up" in response.json()["remedy"]
