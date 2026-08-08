from pathlib import Path

from neo4j import Session

from graph.build.catalog import Exercise, load_exercises
from graph.build.report import BuildReport, read_report
from graph.schema import AnatomicalTier, GraphSource, NodeLabel, RelType


def _apply_constraints(session: Session) -> None:
    """Declare uniqueness constraints, which also creates the backing indexes.

    Without these, `MERGE` scans every node of the label and the build is
    quadratic; they also make a duplicate key an error rather than a silent
    second node.
    """
    # Labels and property keys cannot be query parameters in Cypher, so they are
    # interpolated. Values come from the NodeLabel enum, never from input data.
    session.run(
        f"CREATE CONSTRAINT exercise_id IF NOT EXISTS "
        f"FOR (n:{NodeLabel.EXERCISE}) REQUIRE n.id IS UNIQUE"
    )
    for label in (
        NodeLabel.MUSCLE,
        NodeLabel.EQUIPMENT,
        NodeLabel.MOVEMENT_PATTERN,
        NodeLabel.ANATOMICAL_STRUCTURE,
    ):
        session.run(
            f"CREATE CONSTRAINT {label.lower()}_name IF NOT EXISTS "
            f"FOR (n:{label}) REQUIRE n.name IS UNIQUE"
        )


def _merge_exercises(session: Session, exercises: list[Exercise]) -> None:
    """Create or update one `Exercise` node per catalog row."""
    session.run(
        f"""
        UNWIND $rows AS row
        MERGE (e:{NodeLabel.EXERCISE} {{id: row.id}})
        SET e += row, e.source = $source
        """,
        rows=[ex.model_dump() for ex in exercises],
        source=GraphSource.KG1.value,
    )


def _merge_links(
    session: Session,
    label: NodeLabel,
    rel: RelType,
    pairs: list[tuple[str, str]],
    tier: AnatomicalTier | None = None,
) -> None:
    """Create the taxonomy nodes exercises name, and the edges reaching them.

    Every taxonomy node exists because some exercise names it, so the node and
    the edge to it are merged in a single statement.

    Args:
        session: An open Neo4j session.
        label: Label to give the taxonomy nodes.
        rel: Edge type running from exercise to taxonomy node.
        pairs: `(exercise_id, term)` for every term an exercise names.
        tier: Anatomical tier to record on the node. `None` leaves the property
            absent, because assigning null in Cypher sets nothing.
    """
    session.run(
        f"""
        UNWIND $rows AS row
        MATCH (e:{NodeLabel.EXERCISE} {{id: row.exercise_id}})
        MERGE (t:{label} {{name: row.term}})
        SET t.source = $source, t.tier = $tier
        MERGE (e)-[:{rel}]->(t)
        """,
        rows=[{"exercise_id": exercise_id, "term": term} for exercise_id, term in pairs],
        source=GraphSource.KG1.value,
        tier=tier.value if tier else None,
    )


def build_kg1(session: Session, exercises_path: Path) -> BuildReport:
    """Build the movement/clinical graph from the exercise catalog.

    Idempotent: every write is a `MERGE`, so re-running against a populated
    store converges rather than duplicating. Constraints are applied first, or
    the merges below degrade to full label scans.

    Args:
        session: An open Neo4j session.
        exercises_path: Location of `exercises.json`.

    Returns:
        Node and edge counts read back from the store after the build.

    Raises:
        FileNotFoundError: If the catalog is missing.
        pydantic.ValidationError: If a catalog row does not match the expected shape.
    """
    exercises = load_exercises(exercises_path)
    _apply_constraints(session)
    _merge_exercises(session, exercises)

    # These four calls are the whole of KG1 v0 — every node and edge is derived
    # from the catalog, nothing is authored yet.
    _merge_links(
        session,
        NodeLabel.MUSCLE,
        RelType.TARGETS,
        [(ex.id, term) for ex in exercises for term in ex.muscle_groups],
    )
    _merge_links(
        session,
        NodeLabel.EQUIPMENT,
        RelType.REQUIRES,
        [(ex.id, term) for ex in exercises for term in ex.equipment_required],
    )
    _merge_links(
        session,
        NodeLabel.MOVEMENT_PATTERN,
        RelType.IS_A,
        [(ex.id, term) for ex in exercises for term in ex.movement_patterns],
    )
    # The catalog only names joints, so `stresses` reaching a joint holds by
    # construction here. Once regions and sub-structures are authored, this
    # MERGE could bind a non-joint node on a name collision — it will need to
    # match on `tier` explicitly then.
    _merge_links(
        session,
        NodeLabel.ANATOMICAL_STRUCTURE,
        RelType.STRESSES,
        [(ex.id, term) for ex in exercises for term in ex.joints_loaded],
        tier=AnatomicalTier.JOINT,
    )

    return read_report(session)
