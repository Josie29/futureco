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
    data_dir: Path = Field(default=REPO_ROOT / "data")

    @property
    def exercises_path(self) -> Path:
        """Path to the exercise catalog that KG1 is derived from."""
        return self.data_dir / "exercises.json"

    @property
    def anatomy_path(self) -> Path:
        """Path to the authored anatomy hierarchy, grounded in SNOMED CT."""
        return self.data_dir / "authored" / "anatomy.json"

    @property
    def contraindications_path(self) -> Path:
        """Path to the authored condition-to-pattern contraindication rules."""
        return self.data_dir / "authored" / "contraindications.json"

    @property
    def member_context_path(self) -> Path:
        """Path to the sample member, which KG1 reads for injuries only."""
        return self.data_dir / "member-context.json"


settings = Settings()
