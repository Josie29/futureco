from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from neo4j.exceptions import AuthError, Neo4jError, ServiceUnavailable

from settings import settings


async def handle_unavailable(request: Request, exc: ServiceUnavailable) -> JSONResponse:
    """Turn an unreachable database into an answer that names the fix.

    The graph tab is the first surface that needs Neo4j running to render at
    all, so the outage has to arrive as an instruction rather than an empty
    canvas.
    """
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "detail": f"Cannot reach Neo4j at {settings.neo4j_uri}.",
            "remedy": "Start it with `docker compose up -d neo4j`, then build the graph.",
        },
    )


async def handle_auth(request: Request, exc: AuthError) -> JSONResponse:
    """Report rejected credentials as configuration, not as a server fault."""
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "detail": "Neo4j rejected the configured credentials.",
            "remedy": "Check NEO4J_USER and NEO4J_PASSWORD in .env against docker-compose.yml.",
        },
    )


async def handle_neo4j(request: Request, exc: Neo4jError) -> JSONResponse:
    """Surface a query failure with its Neo4j code instead of a bare 500."""
    return JSONResponse(
        status_code=status.HTTP_502_BAD_GATEWAY,
        content={"detail": "The graph query failed.", "code": exc.code},
    )


def register_error_handlers(app: FastAPI) -> None:
    """Attach the database-failure handlers to an app.

    Args:
        app: The application to register against.
    """
    app.add_exception_handler(ServiceUnavailable, handle_unavailable)  # type: ignore[arg-type]
    app.add_exception_handler(AuthError, handle_auth)  # type: ignore[arg-type]
    app.add_exception_handler(Neo4jError, handle_neo4j)  # type: ignore[arg-type]
