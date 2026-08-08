import json
from datetime import date
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel

# A preference value is whatever the coach recorded: a duration, a note, a list
# of days. Neo4j stores all three as-is, so no narrowing is needed.
PreferenceValue = int | str | list[str]


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
    """One entry of `injuries[]`.

    Read by KG1, not KG2: the injury is where clinical filtering starts, so it
    lives in the movement graph even though the member's chart is what records
    it. `condition` is an explicit structured field standing in for extraction
    from the free-text `notes` — see `docs/decisions.md`, *Data cleanup*.
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


class Goal(BaseModel):
    """One entry of `goals[]`.

    `targets` names muscles from KG1's vocabulary. It may be empty — not every
    goal is muscular (*"Average 7+ hours of sleep"*), and an empty list is a
    valid goal rather than a resolution failure.
    """

    id: str
    text: str
    priority: int
    target_date: date | None
    targets: list[str]


class Member(BaseModel):
    """The `profile` block — who the member is."""

    id: str
    name: str
    age: int
    sex: str
    height_cm: int
    weight_kg: float
    timezone: str
    member_since: date
    coach_id: str
    tier: str


class MemberContext(BaseModel):
    """The slices of `member-context.json` that either graph builds from.

    The file also carries workout history, adherence, biomarkers, labs, chat,
    and the coach brief. Those are the copilot's retrieval surface rather than
    graph structure, so they are not modelled here.
    """

    profile: Member
    goals: list[Goal]
    preferences: dict[str, PreferenceValue]
    equipment_available: list[str]
    injuries: list[Injury]


def load_member_context(path: Path) -> MemberContext:
    """Read and validate the member's context.

    Args:
        path: Location of `member-context.json`.

    Returns:
        The validated slices both graphs build from.

    Raises:
        FileNotFoundError: If the file is missing.
        pydantic.ValidationError: If any modelled block is malformed.
    """
    return MemberContext.model_validate(json.loads(path.read_text()))
