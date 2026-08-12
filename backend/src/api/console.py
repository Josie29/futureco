from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

# Serving the console from the API container is what makes `docker compose up`
# the one command ASSESSMENT.md:119 grades. It also removes the CORS story
# entirely in the container: same origin, so `X-Coach-Id` is a plain header on
# a same-site request rather than a preflighted cross-origin one.
#
# Nothing here runs in development. `npm run dev` still proxies /api to the
# backend, and this module no-ops when the bundle is absent.

# Paths the console must never answer for. Everything else falls through to
# index.html, because the router owns `/m/:id`, `/traces` and `/admin/graph`
# and a deep link to one of those has to survive a reload.
API_PREFIXES: tuple[str, ...] = ("api/", "health", "docs", "redoc", "openapi.json")

# A content-hashed filename cannot change meaning, so a year is safe and the
# browser never asks about it again. Vite names every asset that way.
IMMUTABLE = "public, max-age=31536000, immutable"

# Everything else is unhashed and names a moving target — above all
# `index.html`, which is the map to the hashed chunks. Left to the browser's
# own heuristics it gets cached, and a returning coach is pinned to the chunk
# graph of whichever deploy they first opened: a console one release behind,
# with no error anywhere to say so. `no-cache` means revalidate, not never
# store, so the ETag turns the check into a 304 and costs nothing.
REVALIDATE = "no-cache"


class HashedAssets(StaticFiles):
    """`/assets`, cached for a year because every name carries its own hash.

    The class exists only to add the header — Starlette has no hook for it, and
    a middleware would have to re-derive which requests were assets from the
    path, which is the routing decision already made here.
    """

    def file_response(self, *args: Any, **kwargs: Any) -> Response:
        """Serve a file, cached hard.

        Args and returns are passed through untouched. They are untyped because
        the signature is Starlette's and has gained arguments across versions;
        this override decorates the result and has no business restating it.
        """
        response = super().file_response(*args, **kwargs)
        response.headers["cache-control"] = IMMUTABLE
        return response


def mount_console(app: FastAPI, directory: Path | None) -> bool:
    """Serve the built console alongside the API, if it was built.

    Args:
        app: The application to mount on.
        directory: The Vite build output. None or missing leaves the API
            serving only JSON, which is what a local `uvicorn` does.

    Returns:
        Whether a bundle was found and mounted.
    """
    if directory is None or not (directory / "index.html").is_file():
        return False

    index = directory / "index.html"

    # Hashed filenames, so they are safe to cache hard and are the only thing
    # in the bundle that should be.
    app.mount("/assets", HashedAssets(directory=directory / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def console(path: str) -> FileResponse:
        """Serve a bundled file, or the shell for a client-side route.

        Registered last, so every real endpoint is matched before this one. The
        API prefixes are refused explicitly rather than left to fall through:
        an unknown `/api/...` path returning the HTML shell would turn a typo
        in a fetch into a JSON parse error three layers away from its cause.

        Raises:
            HTTPException: 404 for an unknown path under an API prefix.
        """
        if path.startswith(API_PREFIXES):
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No such endpoint: /{path}")

        candidate = directory / path
        # `resolve()` on both sides, so `..` in a request path cannot escape
        # the bundle and read the image's filesystem.
        if path and candidate.is_file():
            if candidate.resolve().is_relative_to(directory.resolve()):
                return FileResponse(candidate, headers={"cache-control": REVALIDATE})
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such file")

        return FileResponse(index, headers={"cache-control": REVALIDATE})

    return True
