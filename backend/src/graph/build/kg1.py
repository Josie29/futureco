from collections.abc import Callable
from pathlib import Path

from neo4j import Session
from pydantic import BaseModel, ConfigDict

from graph.build.catalog import Exercise, load_exercises
from graph.build.report import BuildReport, read_report
from graph.schema import AnatomicalTier, GraphSource, NodeLabel, RelType


class _CatalogEdge(BaseModel):
    """One catalog field, and the nodes and edge type its values become."""

    model_config = ConfigDict(frozen=True)

    terms: Callable[[Exercise], list[str]]
    label: NodeLabel
    rel: RelType


# This table is the whole of KG1 v0 — every node and edge is derived from the
# catalog, nothing is authored yet.
_CATALOG_EDGES: tuple[_CatalogEdge, ...] = (
    _CatalogEdge(
        terms=lambda ex: ex.muscle_groups,
        label=NodeLabel.MUSCLE,
        rel=RelType.TARGETS,
    ),
    _CatalogEdge(
        terms=lambda ex: ex.joints_loaded,
        label=NodeLabel.ANATOMICAL_STRUCTURE,
        rel=RelType.STRESSES,
    ),
    _CatalogEdge(
        terms=lambda ex: ex.equipment_required,
        label=NodeLabel.EQUIPMENT,
        rel=RelType.REQUIRES,
    ),
    _CatalogEdge(
        terms=lambda ex: ex.movement_patterns,
        label=NodeLabel.MOVEMENT_PATTERN,
        rel=RelType.IS_A,
    ),
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
    for edge in _CATALOG_EDGES:
        # Sorted so a build writes taxonomy nodes in a stable order.
        names = sorted({term for ex in exercises for term in edge.terms(ex)})
        if edge.label is NodeLabel.ANATOMICAL_STRUCTURE:
            session.run(
                f"""
                UNWIND $names AS name
                MERGE (n:{edge.label} {{name: name}})
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
                MERGE (n:{edge.label} {{name: name}})
                SET n.source = $source
                """,
                names=names,
                source=GraphSource.KG1.value,
            )


def _merge_catalog_edges(session: Session, exercises: list[Exercise]) -> None:
    """Connect each exercise to the taxonomy nodes its row names."""
    for edge in _CATALOG_EDGES:
        pairs = [
            {"exercise_id": ex.id, "target": term}
            for ex in exercises
            for term in edge.terms(ex)
        ]
        # `stresses` is constrained to the joint tier in the MATCH rather than
        # checked afterwards, so the schema invariant lives in the query itself.
        target_pattern = (
            f"(t:{edge.label} {{name: row.target, tier: '{AnatomicalTier.JOINT}'}})"
            if edge.rel is RelType.STRESSES
            else f"(t:{edge.label} {{name: row.target}})"
        )
        session.run(
            f"""
            UNWIND $rows AS row
            MATCH (e:{NodeLabel.EXERCISE} {{id: row.exercise_id}})
            MATCH {target_pattern}
            MERGE (e)-[:{edge.rel}]->(t)
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
