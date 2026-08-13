from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from neo4j import Driver, Session

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
from resolver.index import ConceptIndex
from settings import settings


class Runtime:
    """Everything the API builds once and reuses for every request.

    Thinner than it was: the resolver and its embedder left with the
    deterministic generator and return as part of the planning agent's tool
    layer, which will hang its own long-lived state here.
    """

    def __init__(
        self,
        driver: Driver,
        report: BuildReport,
        concept_index: ConceptIndex,
        traces: TraceStore,
        plan_runs: PlanRunStore,
        durable: bool,
    ) -> None:
        self.driver = driver
        self.report = report
        self.concept_index = concept_index
        """The resolver's in-memory index, one per process. The embedder
        inside stays lazy, so startup does not pay for it."""

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
    """Open the driver, snapshot the build report, and pick the stores."""
    driver = open_driver()
    pool = None
    try:
        with driver.session() as session:
            report = read_report(session)
            concept_index = ConceptIndex.load(session)

        if settings.database_url:
            from api.postgres import open_stores

            traces, plan_runs, pool = open_stores(settings.database_url)
            durable = True
        else:
            traces, plan_runs, durable = InMemoryTraceStore(), InMemoryPlanRunStore(), False

        app.state.runtime = Runtime(
            driver, report, concept_index, traces, plan_runs, durable
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
        "storage": "postgres" if run.durable else "memory",
    }


# Last, because its catch-all must be matched after every real endpoint.
mount_console(app, settings.console_dir)
