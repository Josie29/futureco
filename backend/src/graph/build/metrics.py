import json
from datetime import date, timedelta
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from graph.build.member import MemberContext
from graph.schema import MetricCategory, MetricDirection

# Panel field name -> metric id. Explicit rather than derived from the field
# names, because the two vocabularies answer to different owners: the field
# names are the shape of the provided data, the metric ids are ours. A rename on
# either side should be a visible edit here, not a silent miss.
_BLOOD_PANEL_METRICS: dict[str, str] = {
    "ldl_mg_dl": "ldl",
    "hdl_mg_dl": "hdl",
    "triglycerides_mg_dl": "triglycerides",
    "hba1c_pct": "hba1c",
    "vitamin_d_ng_ml": "vitamin_d",
    "ferritin_ng_ml": "ferritin",
    "crp_mg_l": "crp",
}

_DEXA_METRICS: dict[str, str] = {
    "body_fat_pct": "body_fat_pct",
    "lean_mass_kg": "lean_mass",
    "fat_mass_kg": "fat_mass",
    "bone_density_z_score": "bone_density_z",
    "visceral_fat_cm2": "visceral_fat",
}

BLOOD_PANEL = "blood_panel"
DEXA_SCAN = "dexa_scan"


class MetricDefinition(BaseModel):
    """One measurable quantity, and the band a value is read against.

    The band lives here rather than in code so that "is this value concerning"
    is a graph fact. A second member with age- or sex-adjusted ranges — HDL and
    body fat percentage both have them — needs different data, not a different
    branch.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    unit: str
    category: MetricCategory
    direction: MetricDirection
    optimal_low: float | None = None
    optimal_high: float | None = None
    reference: str

    def is_outside_band(self, value: float) -> bool:
        """Whether a value sits outside this metric's reference band.

        `TREND` metrics have no band, so nothing is ever outside one — that is
        the whole meaning of the direction. Reporting a bare "outside range"
        without consulting `direction` is the mistake resting heart rate is in
        the file to prevent: 58 bpm is below the adult band and favourable.

        Args:
            value: The observed value.

        Returns:
            True when the value falls outside the authored band.
        """
        if self.direction is MetricDirection.TREND:
            return False
        if self.optimal_low is not None and value < self.optimal_low:
            return True
        return self.optimal_high is not None and value > self.optimal_high


class Observation(BaseModel):
    """One measurement of one metric, on one date.

    Every biomarker, lab value and adherence week reduces to this shape, which
    is the point: the JSON holds four different flattenings of the same thing —
    a bare scalar, an undated list, a dated list, and a panel — and one uniform
    retrieval reads all four once they are un-flattened.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    metric_id: str
    value: float
    observed_on: date
    panel: str | None = None
    """Which report this came from, where several values share one draw.

    A property rather than a node: a panel groups observations that already
    share a date, so it carries no relationship a date does not.
    """


def load_metrics(path: Path) -> dict[str, MetricDefinition]:
    """Read the authored metric definitions.

    Args:
        path: Location of `metrics.json`.

    Returns:
        Definitions keyed by id.

    Raises:
        FileNotFoundError: If the file is missing.
        pydantic.ValidationError: If a definition is malformed.
        ValueError: If two definitions share an id, or a band is inverted.
    """
    rows = json.loads(path.read_text())["metrics"]
    definitions = [MetricDefinition.model_validate(row) for row in rows]

    by_id: dict[str, MetricDefinition] = {}
    for definition in definitions:
        if definition.id in by_id:
            raise ValueError(f"duplicate metric id {definition.id!r}")
        low, high = definition.optimal_low, definition.optimal_high
        if low is not None and high is not None and low > high:
            raise ValueError(
                f"metric {definition.id!r} has an inverted band: {low} > {high}"
            )
        by_id[definition.id] = definition
    return by_id


def _observation(metric_id: str, value: float, on: date, panel: str | None = None) -> Observation:
    """Build one observation with its derived id."""
    return Observation(
        id=f"obs_{metric_id}_{on:%Y%m%d}",
        metric_id=metric_id,
        value=float(value),
        observed_on=on,
        panel=panel,
    )


def _from_panel(block: BaseModel | None, mapping: dict[str, str], panel: str) -> list[Observation]:
    """Flatten a dated panel of several values into one observation each."""
    if block is None:
        return []
    observed_on = getattr(block, "date")
    return [
        _observation(metric_id, value, observed_on, panel)
        for field, metric_id in mapping.items()
        if (value := getattr(block, field, None)) is not None
    ]


def observations(context: MemberContext, as_of: date) -> list[Observation]:
    """Flatten every measurement in the member's record onto one timeline.

    Four irregular shapes, read explicitly rather than through a descriptor in
    the JSON: a mini-DSL for four cases would be harder to follow than four
    named readers, and these are the only shapes the format has.

    Two dating decisions are made here, both because the source omits what it
    needs. `sleep_hours_last_7_days` is an undated list, so it is dated backwards
    from `as_of` with the last element as the most recent — the reading its own
    field name implies. `resting_hr_bpm` and `hrv_ms` are bare scalars where
    every sibling is dated, so they are stamped `as_of`; an undated observation
    cannot be plotted, compared, or asked about by window.

    Args:
        context: The member's validated context.
        as_of: The date the dataset is read as "today".

    Returns:
        Every observation, ordered by metric then date.
    """
    rows: list[Observation] = []
    biomarkers = context.biomarkers

    nights = biomarkers.sleep_hours_last_7_days
    rows += [
        _observation("sleep_hours", hours, as_of - timedelta(days=len(nights) - 1 - offset))
        for offset, hours in enumerate(nights)
    ]

    for metric_id, value in (
        ("resting_hr", biomarkers.resting_hr_bpm),
        ("hrv", biomarkers.hrv_ms),
    ):
        if value is not None:
            rows.append(_observation(metric_id, value, as_of))

    rows += [
        _observation("body_weight", point.kg, point.date) for point in biomarkers.weight_trend_kg
    ]
    rows += [
        _observation("weekly_adherence", week.pct, week.week_of)
        for week in context.adherence.weekly_completion_pct
    ]
    rows += _from_panel(context.labs.blood_panel, _BLOOD_PANEL_METRICS, BLOOD_PANEL)
    rows += _from_panel(context.labs.dexa_scan, _DEXA_METRICS, DEXA_SCAN)

    return sorted(rows, key=lambda row: (row.metric_id, row.observed_on))


def check_against(
    rows: list[Observation], definitions: dict[str, MetricDefinition]
) -> list[str]:
    """Cross-check the observations against the authored definitions.

    Args:
        rows: The flattened observations.
        definitions: Metric definitions keyed by id.

    Returns:
        Metric ids that are defined but observed nowhere. Reported rather than
        raised: a member who has never had a DEXA scan is not a build failure,
        and the definitions are shared across members.

    Raises:
        ValueError: If an observation names a metric with no definition. That
            direction *is* fatal — the value would land in the graph with no
            unit and no band, and read as if it had been checked.
    """
    undefined = sorted({row.metric_id for row in rows} - set(definitions))
    if undefined:
        raise ValueError(f"observations name undefined metrics: {undefined}")
    return sorted(set(definitions) - {row.metric_id for row in rows})
