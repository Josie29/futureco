import json
from pathlib import Path

from pydantic import BaseModel


class Exercise(BaseModel):
    """One row of `data/exercises.json`."""

    id: str
    name: str
    muscle_groups: list[str]
    joints_loaded: list[str]
    movement_patterns: list[str]
    equipment_required: list[str]
    is_bilateral: bool
    side: str | None
    priority_tier: int
    is_reps: bool
    is_duration: bool
    supports_weight: bool
    estimated_rep_duration: float
    bilateral_pair_id: str | None


def load_exercises(path: Path) -> list[Exercise]:
    """Read and validate the exercise catalog.

    Args:
        path: Location of `exercises.json`.

    Returns:
        Every catalog row, validated.

    Raises:
        FileNotFoundError: If the catalog is missing.
        pydantic.ValidationError: If a row does not match the expected shape.
    """
    rows = json.loads(path.read_text())
    return [Exercise.model_validate(row) for row in rows]
