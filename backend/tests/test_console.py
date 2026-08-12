import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.console import IMMUTABLE, REVALIDATE, mount_console


@pytest.fixture
def bundle(tmp_path):
    """A stand-in for the Vite build: a shell, a hashed chunk, a loose file."""
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>console</title>")
    (tmp_path / "assets" / "Console-DmFzU5mX.js").write_text("export const a = 1")
    (tmp_path / "favicon.svg").write_text("<svg/>")
    return tmp_path


@pytest.fixture
def client(bundle):
    """The console mounted on a bare app, with no API routes to shadow it."""
    app = FastAPI()
    assert mount_console(app, bundle)
    return TestClient(app)


def test_the_shell_is_revalidated_on_every_load(client) -> None:
    """The bug a coach sees as "my change didn't deploy".

    `index.html` is the map to the hashed chunks. Without a header the browser
    applies its own heuristic, caches it, and keeps requesting the chunk names
    of whichever deploy that visitor first opened — so a returning coach gets a
    console one release behind, and nothing anywhere reports an error. It cost
    a round of "it's live, I checked" against a screenshot that disagreed.
    """
    assert client.get("/").headers["cache-control"] == REVALIDATE


def test_a_client_route_is_revalidated_too(client) -> None:
    """`/m/:id` and `/traces` serve the same shell, so they carry the same risk.

    A coach's bookmark is a deep link far more often than it is `/`.
    """
    assert client.get("/m/mbr_01HX9JORDAN").headers["cache-control"] == REVALIDATE


def test_an_unhashed_file_is_revalidated(client) -> None:
    """A favicon keeps its name across builds, so it is a moving target too."""
    assert client.get("/favicon.svg").headers["cache-control"] == REVALIDATE


def test_a_hashed_asset_is_cached_hard(client) -> None:
    """The other half: revalidating every chunk would undo the point of hashing.

    `Console-DmFzU5mX.js` can only ever hold one body, so a year is safe and
    the browser never asks about it again.
    """
    response = client.get("/assets/Console-DmFzU5mX.js")
    assert response.status_code == 200
    assert response.headers["cache-control"] == IMMUTABLE


def test_the_two_rules_disagree(client) -> None:
    """Guards the pair against being unified by a well-meaning middleware.

    One header for the whole bundle is wrong whichever value it takes: cache
    everything and the shell goes stale, revalidate everything and every chunk
    costs a round trip on every load.
    """
    assert IMMUTABLE != REVALIDATE
    assert client.get("/").headers["cache-control"] != (
        client.get("/assets/Console-DmFzU5mX.js").headers["cache-control"]
    )


def test_no_bundle_leaves_the_api_serving_json(tmp_path) -> None:
    """A local `uvicorn` with nothing built must not start answering HTML."""
    app = FastAPI()
    assert mount_console(app, tmp_path) is False
