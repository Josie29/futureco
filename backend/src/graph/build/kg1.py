from pathlib import Path

from neo4j import Session

from graph.build.catalog import Exercise, distinct_values, load_exercises
from graph.build.report import BuildReport, read_report
from graph.schema import AnatomicalTier, GraphSource, NodeLabel, RelType

# Which exercise field feeds which node label and edge type. This table is the
# whole of KG1 v0 — every node and edge is derived from the catalog, nothing is
# authored yet.
_CATALOG_EDGES: tuple[tuple[str, NodeLabel, RelType], ...] = (
    ("muscle_groups", NodeLabel.MUSCLE, RelType.TARGETS),
    ("joints_loaded", NodeLabel.ANATOMICAL_STRUCTURE, RelType.STRESSES),
    ("equipment_required", NodeLabel.EQUIPMENT, RelType.REQUIRES),
    ("movement_patterns", NodeLabel.MOVEMENT_PATTERN, RelType.IS_A),
)


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


def _merge_taxonomy(session: Session, exercises: list[Exercise]) -> None:
    """Create the name-keyed taxonomy nodes the catalog references.

    Anatomical structures land at the joint tier, because that is the only tier
    the catalog names; regions and sub-structures are authored separately.
    """
    for field, label, _ in _CATALOG_EDGES:
        names = distinct_values(exercises, field)
        if label is NodeLabel.ANATOMICAL_STRUCTURE:
            session.run(
                f"""
                UNWIND $names AS name
                MERGE (n:{label} {{name: name}})
                SET n.source = $source, n.tier = $tier
                """,
                names=names,
                source=GraphSource.KG1.value,
                tier=AnatomicalTier.JOINT.value,
            )
        else:
            session.run(
                f"""
                UNWIND $names AS name
                MERGE (n:{label} {{name: name}})
                SET n.source = $source
                """,
                names=names,
                source=GraphSource.KG1.value,
            )


def _merge_catalog_edges(session: Session, exercises: list[Exercise]) -> None:
    """Connect each exercise to the taxonomy nodes its row names."""
    for field, label, rel in _CATALOG_EDGES:
        pairs = [
            {"exercise_id": ex.id, "target": value}
            for ex in exercises
            for value in getattr(ex, field)
        ]
        # `stresses` is constrained to the joint tier in the MATCH rather than
        # checked afterwards, so the schema invariant lives in the query itself.
        target_pattern = (
            f"(t:{label} {{name: row.target, tier: '{AnatomicalTier.JOINT}'}})"
            if rel is RelType.STRESSES
            else f"(t:{label} {{name: row.target}})"
        )
        session.run(
            f"""
            UNWIND $rows AS row
            MATCH (e:{NodeLabel.EXERCISE} {{id: row.exercise_id}})
            MATCH {target_pattern}
            MERGE (e)-[:{rel}]->(t)
            """,
            rows=pairs,
        )


def build_kg1(session: Session, exercises_path: Path) -> BuildReport:
    """Build the movement/clinical graph from the exercise catalog.

    Idempotent: every write is a `MERGE`, so re-running against a populated
    store converges rather than duplicating.

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
    _merge_taxonomy(session, exercises)
    _merge_catalog_edges(session, exercises)
    return read_report(session)
