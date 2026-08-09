from datetime import date

import pytest

from graph.build.member import MemberContext, load_member_context, reference_date
from graph.build.metrics import (
    BLOOD_PANEL,
    DEXA_SCAN,
    MetricDefinition,
    check_against,
    load_metrics,
    observations,
)
from graph.schema import MetricCategory, MetricDirection
from settings import settings

# Pure: flattening and band arithmetic are properties of the data and the code,
# not of the store. Nothing here needs Neo4j.


@pytest.fixture(scope="module")
def context() -> MemberContext:
    return load_member_context(settings.member_context_path)


@pytest.fixture(scope="module")
def definitions() -> dict[str, MetricDefinition]:
    return load_metrics(settings.metrics_path)


def test_low_resting_heart_rate_is_not_flagged(definitions: dict[str, MetricDefinition]) -> None:
    """58 bpm sits below the adult band and must read as favourable.

    This is the case the whole `MetricDirection` split exists for. Read as a
    two-sided range, 60-100 makes her athletic resting heart rate "out of
    range", and a copilot repeating that to a coach is worse than saying
    nothing. If this fails, the band is being applied without consulting the
    direction.
    """
    resting_hr = definitions["resting_hr"]
    assert resting_hr.direction is MetricDirection.LOWER_BETTER
    assert not resting_hr.is_outside_band(58.0)
    assert resting_hr.is_outside_band(104.0)


def test_trend_metrics_never_report_a_breach(definitions: dict[str, MetricDefinition]) -> None:
    """A metric with no authored band cannot have a value outside it.

    HRV and body weight have no defensible population range, so they carry
    none. Treating a missing bound as zero would make every reading a breach.
    """
    for metric_id in ("hrv", "body_weight", "lean_mass"):
        definition = definitions[metric_id]
        assert definition.direction is MetricDirection.TREND
        assert not definition.is_outside_band(0.0)
        assert not definition.is_outside_band(10_000.0)


def test_two_sided_band_catches_both_ends(definitions: dict[str, MetricDefinition]) -> None:
    """Ferritin is genuinely two-sided; deficiency and overload both matter.

    Neither HIGHER_BETTER nor LOWER_BETTER can express this, which is why BAND
    is a separate direction rather than a default.
    """
    ferritin = definitions["ferritin"]
    assert ferritin.direction is MetricDirection.BAND
    assert ferritin.is_outside_band(9.0)
    assert ferritin.is_outside_band(300.0)
    assert not ferritin.is_outside_band(41.0)


def test_sleep_nights_run_forwards_to_the_reference_date(context: MemberContext) -> None:
    """The last element of the undated sleep list is the most recent night.

    `sleep_hours_last_7_days` carries no dates, so the order is the only thing
    saying which night is which. Reversed, her sleep trend inverts while every
    count and average stays identical — a defect no total would reveal.
    """
    as_of = reference_date(context)
    nights = [row for row in observations(context, as_of) if row.metric_id == "sleep_hours"]
    assert [row.observed_on for row in nights] == sorted(row.observed_on for row in nights)
    assert nights[-1].observed_on == as_of
    assert nights[-1].value == context.biomarkers.sleep_hours_last_7_days[-1]
    assert nights[0].value == context.biomarkers.sleep_hours_last_7_days[0]


def test_undated_scalars_are_stamped_with_the_reference_date(context: MemberContext) -> None:
    """Resting HR and HRV carry no date in the source and must acquire one.

    Every sibling in the block is dated. An undated observation cannot be
    plotted, compared against last month, or returned by a windowed query — it
    would exist in the graph and be invisible to every question asked of it.
    """
    as_of = reference_date(context)
    rows = {row.metric_id: row for row in observations(context, as_of)}
    assert rows["resting_hr"].observed_on == as_of
    assert rows["hrv"].observed_on == as_of


def test_panel_values_keep_the_panel_date(context: MemberContext) -> None:
    """Lab values are dated by their draw, not by when the graph was built.

    Her blood panel is six weeks older than her DEXA scan, and both are older
    than everything else on the record. Stamping them `as_of` would present
    April's cholesterol as today's.
    """
    as_of = reference_date(context)
    rows = observations(context, as_of)
    blood = {row.observed_on for row in rows if row.panel == BLOOD_PANEL}
    dexa = {row.observed_on for row in rows if row.panel == DEXA_SCAN}

    assert blood == {context.labs.blood_panel.date}
    assert dexa == {context.labs.dexa_scan.date}
    assert blood != dexa
    assert as_of not in blood | dexa


def test_every_measurement_in_the_file_is_flattened(context: MemberContext) -> None:
    """All four measurement blocks reach the timeline.

    The blocks have four different shapes and are read by four different code
    paths, so one can stop contributing without any other failing. Counted from
    the file rather than hardcoded, so this stays true if the sample changes.
    """
    biomarkers, labs = context.biomarkers, context.labs
    expected = (
        len(biomarkers.sleep_hours_last_7_days)
        + len(biomarkers.weight_trend_kg)
        + sum(value is not None for value in (biomarkers.resting_hr_bpm, biomarkers.hrv_ms))
        + len(context.adherence.weekly_completion_pct)
        + sum(1 for field, value in labs.blood_panel if field != "date" and value is not None)
        + sum(1 for field, value in labs.dexa_scan if field != "date" and value is not None)
    )
    assert len(observations(context, reference_date(context))) == expected


def test_observation_ids_are_unique(context: MemberContext) -> None:
    """Ids key the MERGE, so a collision silently overwrites a reading.

    One metric can only be observed once per day by construction. If that ever
    stops holding, this fails instead of the graph quietly losing a value.
    """
    rows = observations(context, reference_date(context))
    assert len({row.id for row in rows}) == len(rows)


def test_undefined_metric_is_fatal(context: MemberContext) -> None:
    """An observation with no definition stops the build.

    Without a definition a value lands with no unit and no band, and reads as
    though it had been checked against one. That direction is fatal; the
    reverse — a definition nobody measured — is merely reported.
    """
    rows = observations(context, reference_date(context))
    with pytest.raises(ValueError, match="undefined metrics"):
        check_against(rows, {"sleep_hours": load_metrics(settings.metrics_path)["sleep_hours"]})


def test_unobserved_definitions_are_reported_not_raised(
    context: MemberContext, definitions: dict[str, MetricDefinition]
) -> None:
    """A member who never had a DEXA scan is not a build failure.

    Definitions are shared across members; observations are not. This member
    happens to be measured on all seventeen, so the report is empty — the
    assertion that matters is that a gap returns rather than raising.
    """
    assert check_against(observations(context, reference_date(context)), definitions) == []

    extra = definitions | {
        "unmeasured": MetricDefinition(
            id="unmeasured",
            name="Never taken",
            unit="x",
            category=MetricCategory.LAB,
            direction=MetricDirection.TREND,
            reference="test fixture",
        )
    }
    assert check_against(observations(context, reference_date(context)), extra) == ["unmeasured"]


def test_reference_date_comes_from_the_brief_not_the_clock(context: MemberContext) -> None:
    """Windows are relative to the dataset, never to today.

    The record ends in June 2026. Anchored on a wall clock, "the last seven
    nights" is empty and the copilot reports that she has stopped training.
    """
    assert reference_date(context) == context.coach_brief.generated_for
    assert reference_date(context) != date.today()
