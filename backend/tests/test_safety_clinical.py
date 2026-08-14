import pytest
from neo4j import Session

from constraints.models import Effect, Origin
from graph.driver import graph_session
from safety.clinical import _constraints, load_clinical

MEMBER = "mbr_01HX9JORDAN"


@pytest.fixture(scope="module")
def session():
    with graph_session() as s:
        yield s


def test_sample_member_yields_one_block_and_five_cautions(session: Session) -> None:
    """The recovering knee activates exactly the authored rule set.

    A missing rule silently widens what the agent may plan; an extra one
    excludes work the clinician never restricted.
    """
    envelope = load_clinical(session, MEMBER)
    blocks = envelope.of(Effect.BLOCK)
    cautions = envelope.of(Effect.CAUTION)
    assert [b.target for b in blocks] == ["movement_pattern:cardio - plyometric"]
    assert len(cautions) == 5
    assert all(c.origin is Origin.CLINICAL for c in envelope.constraints)
    assert all(c.reason for c in envelope.constraints), "rationales arrive verbatim"


def test_evidence_path_names_injury_condition_and_pattern(session: Session) -> None:
    """Every clinical constraint carries the full traversal that produced it.

    The rendered path is the defensible 'why' — injury to condition to the
    clinician's verb to the pattern.
    """
    envelope = load_clinical(session, MEMBER)
    (block,) = envelope.of(Effect.BLOCK)
    assert block.evidence is not None
    assert block.evidence.render() == (
        "inj_knee_left -diagnosed_as-> patellofemoral pain syndrome "
        "-contraindicates-> cardio - plyometric"
    )


def test_unknown_member_raises(session: Session) -> None:
    """An unknown member is an error, never an empty envelope.

    A silently empty envelope would validate every plan against nothing —
    the least safe possible failure of a safety component.
    """
    with pytest.raises(ValueError, match="not in the graph"):
        load_clinical(session, "mbr_nobody")


def test_resolved_status_rows_are_dropped() -> None:
    """A resolved injury constrains nothing.

    Otherwise a healed injury would contraindicate forever, with nothing
    saying why. The row was still retrieved — the drop is inspectable.
    """
    rows = [
        {"injury_id": "inj_old", "injury_status": "resolved",
         "condition": "c", "relation": "contraindicates", "rationale": "r",
         "pattern": "p"},
        {"injury_id": "inj_live", "injury_status": "active",
         "condition": "c", "relation": "cautions", "rationale": "r",
         "pattern": "p"},
    ]
    envelope = _constraints(rows)
    assert len(envelope.constraints) == 1
    assert envelope.constraints[0].effect is Effect.CAUTION


def test_member_with_no_rules_yields_empty_set() -> None:
    """A member with no injuries gets an empty envelope, not an error.

    The query returns one all-null row for them — a real member with
    nothing to constrain.
    """
    rows = [{"injury_id": None, "injury_status": None, "condition": None,
             "relation": None, "rationale": None, "pattern": None}]
    assert _constraints(rows).constraints == ()
