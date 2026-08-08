from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from neo4j.exceptions import AuthError, Neo4jError, ServiceUnavailable

from api.deps import create_driver
from api.routes import graph
from settings import settings

# The Vite dev server. Production would serve the built assets from this app
# and need no cross-origin allowance at all.
DEV_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Hold one driver for the process rather than one per request."""
    app.state.neo4j = create_driver()
    try:
        yield
    finally:
        app.state.neo4j.close()


app = FastAPI(title="futureco coach console API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=DEV_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.exception_handler(ServiceUnavailable)
async def handle_unavailable(request: Request, exc: ServiceUnavailable) -> JSONResponse:
    """Turn an unreachable database into an answer that names the fix.

    The graph tab is the first surface that needs Neo4j running to render, so
    the outage has to arrive as an instruction rather than an empty canvas.
    """
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "detail": f"Cannot reach Neo4j at {settings.neo4j_uri}.",
            "remedy": "Start it with `docker compose up -d neo4j`, then build the graph.",
        },
    )


@app.exception_handler(AuthError)
async def handle_auth(request: Request, exc: AuthError) -> JSONResponse:
    """Report rejected credentials as configuration, not as a server fault."""
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "detail": "Neo4j rejected the configured credentials.",
            "remedy": "Check NEO4J_USER and NEO4J_PASSWORD in .env against docker-compose.yml.",
        },
    )


@app.exception_handler(Neo4jError)
async def handle_neo4j(request: Request, exc: Neo4jError) -> JSONResponse:
    """Surface a query failure with its Neo4j code instead of a bare 500."""
    return JSONResponse(
        status_code=status.HTTP_502_BAD_GATEWAY,
        content={"detail": "The graph query failed.", "code": exc.code},
    )


app.include_router(graph.router, prefix="/api")
