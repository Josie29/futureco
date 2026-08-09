import pytest
from neo4j import Session

from graph.build.kg2 import _build_sessions, build_kg2, load_session_patterns
from graph.build.member import MemberContext, load_member_context
from graph.build.report import read_report
from graph.driver import graph_session
from settings import settings

# These need a seeded Neo4j: they assert what the build actually wrote, and a
# stub that returned the right rows would only be asserting itself.


@pytest.fixture(scope="module")
def session() -> Session:
    with graph_session() as open_session:
        yield open_session


@pytest.fixture(scope="module")
def context() -> MemberContext:
    return load_member_context(settings.member_context_path)


def test_every_recorded_movement_reaches_a_pattern(session: Session, context: MemberContext) -> None:
    """All nine movements in her history land on a movement pattern.

    None of them matches a catalog exercise — not one, not even as a substring —
    so `trained` is the only edge that connects what she actually did to the
    graph. A movement that quietly maps to nothing produces a session that looks
    identical to a skipped one, and "what has she been training" silently
    under-reports.
    """
    recorded = {movement for entry in context.workout_history for movement in entry.exercises}
    linked = session.run(
        "MATCH (:Session)-[t:trained]->(:MovementPattern) RETURN collect(DISTINCT t.movement) AS m"
    ).single()["m"]
    assert recorded - set(linked) == set()


def test_skipped_session_trained_nothing(session: Session) -> None:
    """A session she did not do carries no `trained` edges.

    The distinction has to live in the graph's shape, not in a property a query
    must remember to filter on. Otherwise the skipped full-body session counts
    as full-body work and her adherence problem disappears into the totals.
    """
    row = session.run(
        """
        MATCH (s:Session {completed: false})
        OPTIONAL MATCH (s)-[t:trained]->()
        RETURN s.title AS title, count(t) AS trained
        """
    ).single()
    assert row["title"] == "Full Body"
    assert row["trained"] == 0


def test_equipment_constraint_has_a_citation(session: Session) -> None:
    """Her "no barbell" constraint traces to the message where she said it.

    This is what `mentions` is for. Without it the copilot can report that she
    has no barbell but cannot show why it believes that, and a grounded answer
    becomes an asserted one.
    """
    row = session.run(
        """
        MATCH (:Member)-[:has]->(m:Message)-[r:mentions]->(e:Equipment {name: 'Barbell'})
        RETURN m.text AS text, m.author AS author, r.surface AS surface
        """
    ).single()
    assert row is not None, "no message mentions the barbell"
    assert row["author"] == "member"
    assert "barbell" in row["text"].lower()


def test_member_shorthand_reaches_the_canonical_equipment(session: Session) -> None:
    """"DBs" reaches Dumbbell, through the alias rather than by luck.

    Three characters with no lexical overlap: no automatic pass gets there. If
    the alias is dropped, this message stops naming two of the three pieces of
    kit she owns and the citation above becomes half a citation.
    """
    row = session.run(
        """
        MATCH (:Message)-[r:mentions]->(e:Equipment {name: 'Dumbbell'})
        RETURN r.surface AS surface, r.matched_by AS matched_by
        """
    ).single()
    assert row is not None
    assert row["matched_by"] == "alias"


def test_sleep_goal_is_answerable_through_the_graph(session: Session) -> None:
    """The one goal with no muscles reaches its readings via `measured_by`.

    Before this edge existed, `goal_sleep` was the single goal the graph could
    say nothing about, and the console compensated with a hardcoded target and a
    "no target date means measured" heuristic. This traversal is what replaces
    both — and it is what stops the observation subgraph being a leaf nothing
    walks into.
    """
    row = session.run(
        """
        MATCH (:Member)-[:has]->(g:Goal)-[:measured_by]->(m:Metric)<-[:measures]-(o:Observation)
        RETURN g.id AS goal, m.optimal_low AS target, count(o) AS readings,
               sum(CASE WHEN o.value < m.optimal_low THEN 1 ELSE 0 END) AS under
        """
    ).single()
    assert row["goal"] == "goal_sleep"
    assert row["readings"] == 7
    assert row["under"] == 5


def test_every_observation_is_joined_to_exactly_one_metric(session: Session) -> None:
    """No observation floats without a unit and a band.

    An observation reachable from the member but not from a metric would be
    returned by a retrieval tool as a bare number, and read as though it had
    been checked against a reference range.
    """
    orphans = session.run(
        """
        MATCH (o:Observation)
        WITH o, count { (o)-[:measures]->(:Metric) } AS metrics,
                count { (:Member)-[:has]->(o) } AS owners
        WHERE metrics <> 1 OR owners <> 1
        RETURN collect(o.id) AS bad
        """
    ).single()["bad"]
    assert orphans == []


def test_coach_edge_backs_the_authorization_check(session: Session) -> None:
    """The member is reachable from her coach.

    Mock auth is acceptable (ASSESSMENT.md:72) but it still has to mean
    something. This edge is what the read endpoints consult, so holding a member
    id in a URL is not by itself authority to read that member.
    """
    row = session.run(
        "MATCH (c:Coach)-[:coaches]->(m:Member) RETURN c.id AS coach, m.id AS member"
    ).single()
    assert row["coach"] == "coach_01HXSAM"
    assert row["member"] == "mbr_01HX9JORDAN"


def test_rebuilding_converges(session: Session) -> None:
    """A second build writes the same graph, not a doubled one.

    `docker compose up` runs the seed every time, so this is the normal path
    rather than an edge case. Every write is a MERGE; this proves the keys are
    actually stable, which is the part MERGE does not give you for free.
    """
    before = read_report(session)
    build_kg2(session, settings.member_context_path)
    after = read_report(session)
    assert (after.node_total, after.edge_total) == (before.node_total, before.edge_total)


def test_unmapped_movement_stops_the_build(session: Session, context: MemberContext) -> None:
    """A movement with no pattern mapping fails loudly and writes nothing.

    The alternative is a session node with no `trained` edges, which reads as a
    session she skipped. Reported as an error naming the file to edit, because
    the fix is authoring a mapping and the message should say so.
    """
    doctored = context.model_copy(deep=True)
    doctored.workout_history[0].exercises = ["Zercher Squat Jump"]
    before = read_report(session)

    with pytest.raises(ValueError, match="no pattern mapping"):
        _build_sessions(session, doctored)

    after = read_report(session)
    assert (after.node_total, after.edge_total) == (before.node_total, before.edge_total)


def test_pattern_mappings_reach_real_patterns(session: Session) -> None:
    """Every authored mapping names a pattern KG1 actually has.

    The mapping file is hand-written against the catalog's taxonomy, so a typo
    produces a build failure at seed time — but only for movements this member
    happens to have done. This checks all of them, including mappings no session
    currently exercises.
    """
    mapped = {
        pattern
        for patterns in load_session_patterns(settings.session_patterns_path).values()
        for pattern in patterns
    }
    known = set(
        session.run("MATCH (p:MovementPattern) RETURN collect(p.name) AS names").single()["names"]
    )
    assert mapped - known == set()
