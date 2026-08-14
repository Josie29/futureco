from datetime import date

import pytest
from neo4j import Session

from graph.driver import graph_session
from member.snapshot import MemberSnapshot, load_snapshot
from resolver.index import ConceptIndex

MEMBER = "mbr_01HX9JORDAN"


@pytest.fixture(scope="module")
def session():
    with graph_session() as s:
        yield s


@pytest.fixture(scope="module")
def snapshot(session: Session) -> MemberSnapshot:
    return load_snapshot(session, MEMBER)


def test_snapshot_reads_the_full_chart(snapshot: MemberSnapshot) -> None:
    """The whole chart arrives in one read: equipment, dislikes, the injury
    with its laterality and condition, goals, preferences.

    Any missing piece means the agent plans blind to it — wrong equipment,
    a disliked exercise, or an injury it never heard about.
    """
    assert {e.concept_id for e in snapshot.equipment} >= {
        "equipment:Kettlebell",
        "equipment:Dumbbell",
    }
    assert len(snapshot.equipment) == 5
    assert len(snapshot.disliked_exercises) == 2

    (injury,) = snapshot.injuries
    assert injury.joint == "knee"
    assert injury.joint_concept_id == "anatomy:knee"
    assert injury.side == "left"
    assert injury.status == "recovering"
    assert injury.condition == "patellofemoral pain syndrome"
    assert injury.notes

    assert len(snapshot.goals) == 3
    assert [g.priority for g in snapshot.goals] == sorted(g.priority for g in snapshot.goals)
    assert snapshot.preferred_session_minutes == 50


def test_missing_member_raises(session: Session) -> None:
    """An unknown member is an error, never an empty snapshot.

    A silently empty snapshot would plan with no equipment limit and no
    injury context — indistinguishable from a healthy member who owns
    nothing.
    """
    with pytest.raises(ValueError, match="not in the graph"):
        load_snapshot(session, "mbr_nobody")


def test_every_concept_id_is_resolver_currency(
    session: Session, snapshot: MemberSnapshot
) -> None:
    """Every snapshot concept_id is one the resolver's index actually holds.

    The snapshot, resolve_concept, and every future graph tool share one id
    currency; a snapshot id the index cannot produce (a node id, a stale
    name) would break the first tool that accepts it.
    """
    index = ConceptIndex.load(session)
    known = {
        entry.concept_id
        for namespace in index._entries  # noqa: SLF001 - contract test over the full index
        for entry in index._entries[namespace]
    }
    carried = (
        [e.concept_id for e in snapshot.equipment]
        + [d.concept_id for d in snapshot.disliked_exercises]
        + [i.joint_concept_id for i in snapshot.injuries]
        + [t.concept_id for g in snapshot.goals for t in g.target_muscles]
        + [p.concept_id for p in snapshot.pattern_history]
    )
    assert carried, "the chart should carry concept references"
    unknown = [c for c in carried if c not in known]
    assert not unknown, f"snapshot ids the resolver cannot produce: {unknown}"


def test_pattern_history_counts_completed_sessions_only(
    session: Session, snapshot: MemberSnapshot
) -> None:
    """Skipped sessions leave no trace in the training history.

    Counting a planned-but-skipped session would tell the agent a pattern
    was trained more recently than it was, skewing variety and recovery
    judgments.
    """
    row = session.run(
        "MATCH (:Member {id: $member_id})-[:has]->(s:Session)-[:trained]->() "
        "WHERE s.completed RETURN count(DISTINCT s) AS sessions",
        member_id=MEMBER,
    ).single()
    assert row is not None
    assert max(p.completed_sessions for p in snapshot.pattern_history) <= row["sessions"]

    hip_lift = next(
        p for p in snapshot.pattern_history if p.name == "lower pull - hip lift"
    )
    assert hip_lift.completed_sessions == 2


def test_condition_and_injury_id_are_not_concept_ids(snapshot: MemberSnapshot) -> None:
    """Clinical identifiers stay outside the concept-id currency.

    A condition or injury id shaped like namespace:name would read as
    resolvable, and coach text must never reach a clinical record.
    """
    for injury in snapshot.injuries:
        assert ":" not in (injury.condition or "")
        assert not injury.id.startswith(("anatomy:", "exercise:", "muscle:"))


def test_metric_goal_is_not_an_empty_husk(snapshot: MemberSnapshot) -> None:
    """A goal scored by a number still says how it is measured.

    Without the measured_by leg the sleep goal has no targets and no metric
    — a goal the snapshot can say nothing about.
    """
    sleep = next(g for g in snapshot.goals if not g.target_muscles)
    assert sleep.metric is not None


def test_dates_are_dates(snapshot: MemberSnapshot) -> None:
    """The graph's ISO strings become real dates on the model.

    Downstream constraint derivation compares dates; strings would make
    those comparisons lexicographic accidents.
    """
    assert all(isinstance(i.since, date) for i in snapshot.injuries)
    assert all(isinstance(p.last_trained, date) for p in snapshot.pattern_history)
