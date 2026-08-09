from datetime import date
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/src/settings.py -> repo root is three parents up.
REPO_ROOT: Path = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Runtime configuration, sourced from the environment."""

    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "futureco-local"

    database_url: str | None = None
    """Postgres, holding run traces and the plan-run lineage an adjustment
    refines from.

    None falls back to bounded in-memory stores, which is what `uv run pytest`
    and a bare `uvicorn` outside compose get. The consequence is scoped and
    stated on `/health`: traces vanish on restart, and a plan older than the
    ring cannot be refined. Compose always sets it."""

    data_dir: Path = Field(default=REPO_ROOT / "data")

    console_dir: Path | None = None
    """The built console, served by the API so `docker compose up` is one
    command. The image sets it; local development leaves it None and runs Vite,
    which proxies `/api` back here."""

    anthropic_api_key: str | None = None
    """Optional, and both model surfaces degrade rather than fail without it.

    The generator swaps in a scripted extractor, so its plans are identical and
    only the input shape changes. The copilot runs the same retrieval and
    renders what it found without interpreting it. Either way `docker compose
    up` still demonstrates the graph on a cold clone."""

    anthropic_model: str = "claude-opus-5"
    model_cache_dir: Path | None = None
    """Where the embedding model lives. None leaves fastembed on its own
    default, which is a directory under the system temp dir. The container sets
    this so the weights can be baked into the image at build time."""

    as_of: date | None = None
    """The date the dataset is read as "today", overriding the member's own.

    Nothing in this system means "this week" against a wall clock. The sample
    member's record ends in June 2026, so a query anchored on the real date
    returns an empty seven-day window and a copilot that says she has not
    trained. `member.reference_date` resolves this: an explicit override here,
    otherwise `coach_brief.generated_for`. Left None in normal operation, and
    exposed on the member endpoint so the frontend stops hardcoding its own
    copy — see `web/src/lib/dates.ts`."""

    @property
    def exercises_path(self) -> Path:
        """Path to the exercise catalog that KG1 is derived from."""
        return self.data_dir / "exercises.json"

    @property
    def anatomy_path(self) -> Path:
        """Path to the authored anatomy hierarchy, grounded in SNOMED CT."""
        return self.data_dir / "authored" / "anatomy.json"

    @property
    def muscles_path(self) -> Path:
        """Path to the authored muscle-to-SNOMED SKOS mappings."""
        return self.data_dir / "authored" / "muscles.json"

    @property
    def collections_path(self) -> Path:
        """Path to the authored SKOS collections over patterns and equipment."""
        return self.data_dir / "authored" / "collections.json"

    @property
    def contraindications_path(self) -> Path:
        """Path to the authored condition-to-pattern contraindication rules."""
        return self.data_dir / "authored" / "contraindications.json"

    @property
    def aliases_path(self) -> Path:
        """Path to the authored lay-term to canonical-name mappings."""
        return self.data_dir / "authored" / "aliases.json"

    @property
    def resolver_cases_path(self) -> Path:
        """Path to the labelled cases that calibrate and test the resolver."""
        return self.data_dir / "authored" / "resolver_cases.json"

    @property
    def extraction_cases_path(self) -> Path:
        """Path to the labelled cases that stand in for, and measure, the model."""
        return self.data_dir / "authored" / "extraction_cases.json"

    @property
    def member_context_path(self) -> Path:
        """Path to the sample member, which KG1 reads for injuries only."""
        return self.data_dir / "member-context.json"

    @property
    def metrics_path(self) -> Path:
        """Path to the authored metric definitions and their reference bands."""
        return self.data_dir / "authored" / "metrics.json"

    @property
    def session_patterns_path(self) -> Path:
        """Path to the map from coach shorthand onto catalog movement patterns."""
        return self.data_dir / "authored" / "session_patterns.json"

    @property
    def coaches_path(self) -> Path:
        """Path to the authored coach directory."""
        return self.data_dir / "authored" / "coaches.json"

    @property
    def roster_path(self) -> Path:
        """Path to the synthetic roster filler, which carries no clinical detail."""
        return self.data_dir / "authored" / "roster.json"


settings = Settings()
