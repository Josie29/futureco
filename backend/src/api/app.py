from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from neo4j import Driver, Session

from agent.client import build_extractor
from agent.extract import Extractor
from api.console import mount_console
from api.errors import register_error_handlers
from api.routes import copilot as copilot_routes
from api.routes import graph as graph_routes
from api.routes import members as member_routes
from api.routes import plans as plan_routes
from api.runs import InMemoryPlanRunStore, PlanRunStore
from api.traces import InMemoryTraceStore, TraceStore
from graph.build.report import BuildReport, read_report
from graph.driver import open_driver
from graph.schema import NodeLabel
from resolve.resolver import Resolution, Resolver
from resolve.vocabulary import Vocabulary
from settings import settings


class Runtime:
    """Everything the API builds once and reuses for every request.

    The embedder is the reason this exists. Loading the ONNX model and
    embedding all 164 concepts costs about a second, and paying that per
    request would spend the whole latency budget before any work started.
    """

    def __init__(
        self,
        driver: Driver,
        resolver: Resolver,
        report: BuildReport,
        extractor: Extractor,
        live_extraction: bool,
        traces: TraceStore,
        plan_runs: PlanRunStore,
        durable: bool,
    ) -> None:
        self.driver = driver
        self.resolver = resolver
        self.report = report
        self.extractor = extractor
        self.live_extraction = live_extraction
        """False when no API key is configured. Not a degraded mode for the
        generator: extraction is the entire model surface there, so the plans
        are the same — they just have to be asked for as instructions rather
        than as a sentence. The copilot degrades differently, because synthesis
        *is* its output; it says so on every answer it returns."""

        self.traces = traces
        """Every run both surfaces have recorded, generator and copilot."""

        self.plan_runs = plan_runs
        """What each generation was asked for, so an adjustment refines its
        parent rather than rebuilding from the adjustment alone."""

        self.durable = durable
        """Whether both stores are Postgres-backed. False means bounded
        in-memory ones: traces are lost on restart and an old plan cannot be
        refined. Reported on `/health` rather than inferred, because the
        difference is invisible until the moment it costs something."""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open the driver, load the vocabulary, and warm the embedder.

    Warming happens here rather than lazily so the first coach request is as
    fast as the hundredth, and so a container that cannot reach its model fails
    at startup rather than mid-request.
    """
    driver = open_driver()
    pool = None
    try:
        with driver.session() as session:
            vocabulary = Vocabulary.load(session, settings.aliases_path)
            report = read_report(session)
        # Touching the matrix forces the model load and the concept embed now.
        vocabulary.similarities("warm")
        extractor, live = build_extractor()

        if settings.database_url:
            from api.postgres import open_stores

            traces, plan_runs, pool = open_stores(settings.database_url)
            durable = True
        else:
            traces, plan_runs, durable = InMemoryTraceStore(), InMemoryPlanRunStore(), False

        app.state.runtime = Runtime(
            driver, Resolver(vocabulary), report, extractor, live, traces, plan_runs, durable
        )
        yield
    finally:
        if pool is not None:
            pool.close()
        driver.close()


app = FastAPI(title="FutureCo coach API", lifespan=lifespan)

# The Vite dev server runs on another origin. In the container the app serves
# the built assets itself, so this allowance is development-only.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    # `X-Coach-Id` is a request header the console sends on every member call,
    # so the wildcard here is load-bearing rather than convenience.
    allow_headers=["*"],
)


register_error_handlers(app)
app.include_router(graph_routes.router, prefix="/api")
app.include_router(member_routes.router, prefix="/api")
app.include_router(plan_routes.router, prefix="/api")
app.include_router(copilot_routes.router, prefix="/api")
# Mounted now that both surfaces emit spans. It was held back while only the
# copilot did, because a run list showing half the runs would have been worse
# than the fixture it replaced — see docs/decisions.md, *Observability*.
app.include_router(copilot_routes.traces_router, prefix="/api")


def runtime() -> Runtime:
    """The process-wide runtime built during startup."""
    return app.state.runtime


def graph(run: Runtime = Depends(runtime)) -> Iterator[Session]:
    """A Neo4j session scoped to one request."""
    with run.driver.session() as session:
        yield session


@app.get("/health")
def health(run: Runtime = Depends(runtime), session: Session = Depends(graph)) -> dict:
    """Liveness plus what the process is actually serving.

    The counts come from a live query rather than the startup snapshot, so a
    graph that emptied out after boot reports honestly.
    """
    live = read_report(session)
    return {
        "status": "ok",
        "graph": {"nodes": live.node_total, "edges": live.edge_total},
        "vocabulary": {"concepts": len(run.resolver.vocabulary.concepts)},
        "extraction": "live" if run.live_extraction else "scripted",
        "storage": "postgres" if run.durable else "memory",
    }


@app.get("/api/resolve")
def resolve(
    term: str = Query(min_length=1),
    label: NodeLabel | None = None,
    run: Runtime = Depends(runtime),
) -> Resolution:
    """Resolve one coach phrase onto a canonical concept.

    Exposed on its own because it is the deterministic half of the system a
    reviewer can exercise without a language model, and because it is what
    proves the embedding model is present in the image.

    Args:
        term: What the coach typed.
        label: Restrict the search to one label, as a call site that knows its
            own intent would. Omit to search everything resolvable.
        run: The process-wide runtime.

    Returns:
        The match and its near-misses, or no match and the reason why. A label
        with nothing resolvable behind it is not an error — the resolver
        reports it as `no_pool`, which is the same shape as any other decline.
    """
    labels = frozenset({label}) if label else None
    return run.resolver.resolve(term, labels)


# Last, because its catch-all must be matched after every real endpoint.
mount_console(app, settings.console_dir)
