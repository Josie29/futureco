import json
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from graph.schema import AnatomicalTier, RelType


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


class InjuryStatus(StrEnum):
    """Where an injury sits in its recovery, which gates how hard it filters."""

    ACTIVE = "active"
    RECOVERING = "recovering"
    RESOLVED = "resolved"


class InjurySeverity(StrEnum):
    """Clinical severity, used to weight a caution rather than to exclude."""

    MILD = "mild"
    MODERATE = "moderate"
    SEVERE = "severe"


class Injury(BaseModel):
    """One entry of `injuries[]` in `data/member-context.json`.

    `condition` is an explicit structured field standing in for extraction from
    the free-text `notes`, following the precedent set by `goals[].targets` in
    `docs/decisions.md`. It is what joins an injury to the authored
    contraindication rules for its clinical condition.
    """

    id: str
    region: str
    joint: str
    status: InjuryStatus
    severity: InjurySeverity
    since: date
    notes: str
    condition: str

    @property
    def side(self) -> str | None:
        """Laterality, as the part of `region` that is not the joint.

        `region: "left knee"` against `joint: "knee"` gives `"left"`; an
        unlateralised region gives None.
        """
        return self.region.replace(self.joint, "").strip() or None


class ContraindicationRule(BaseModel):
    """One condition-to-pattern rule, and why it exists."""

    pattern: str
    relation: Literal[RelType.CONTRAINDICATES, RelType.CAUTIONS]
    rationale: str


class Condition(BaseModel):
    """One row of `data/authored/contraindications.json`.

    Keyed by clinical condition rather than by injury, so the same rules apply
    to any member presenting with it.
    """

    condition: str
    snomed_query: str
    source_note: str
    rules: list[ContraindicationRule]
    snomed_code: str
    snomed_term: str


def load_injuries(path: Path) -> list[Injury]:
    """Read and validate the member's injuries.

    Args:
        path: Location of `member-context.json`.

    Returns:
        Every injury recorded for the member.

    Raises:
        FileNotFoundError: If the file is missing.
        pydantic.ValidationError: If an injury is malformed.
    """
    rows = json.loads(path.read_text())["injuries"]
    return [Injury.model_validate(row) for row in rows]


def load_conditions(path: Path) -> list[Condition]:
    """Read and validate the authored contraindication rules.

    Args:
        path: Location of `contraindications.json`.

    Returns:
        Every condition and its rules.

    Raises:
        FileNotFoundError: If the file is missing.
        pydantic.ValidationError: If a row is malformed, which includes a row
            whose SNOMED code was never resolved.
    """
    rows = json.loads(path.read_text())
    return [Condition.model_validate(row) for row in rows]
