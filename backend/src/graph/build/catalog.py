import json
from pathlib import Path

from pydantic import BaseModel

from graph.schema import AnatomicalTier


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


class AnatomicalStructure(BaseModel):
    """One row of `data/authored/anatomy.json`.

    Authored rather than derived: `name`, `tier`, and `part_of` are editorial
    choices, while the SNOMED fields are resolved by `scripts/verify_snomed.py`
    and frozen into the file so no build or request depends on a live ontology
    service.
    """

    name: str
    tier: AnatomicalTier
    part_of: str | None
    snomed_query: str
    snomed_code: str
    snomed_term: str


def load_anatomy(path: Path) -> list[AnatomicalStructure]:
    """Read and validate the authored anatomy hierarchy.

    Args:
        path: Location of `anatomy.json`.

    Returns:
        Every structure, validated.

    Raises:
        FileNotFoundError: If the file is missing.
        pydantic.ValidationError: If a row is malformed, which includes a row
            whose SNOMED code was never resolved.
    """
    rows = json.loads(path.read_text())
    return [AnatomicalStructure.model_validate(row) for row in rows]
