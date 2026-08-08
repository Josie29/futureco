from pathlib import Path

from neo4j import Session

from graph.build.catalog import AnatomicalStructure, Exercise, load_anatomy, load_exercises
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
) -> None:
    """Create the taxonomy nodes exercises name, and the edges reaching them.

    Every muscle, equipment, and pattern node exists because some exercise
    names it, so the node and the edge to it are merged in a single statement.
    Anatomy is the exception — it is authored, so `_merge_stresses` matches
    rather than creates.

    Args:
        session: An open Neo4j session.
        label: Label to give the taxonomy nodes.
        rel: Edge type running from exercise to taxonomy node.
        pairs: `(exercise_id, term)` for every term an exercise names.
    """
    session.run(
        f"""
        UNWIND $rows AS row
        MATCH (e:{NodeLabel.EXERCISE} {{id: row.exercise_id}})
        MERGE (t:{label} {{name: row.term}})
        SET t.source = $source
        MERGE (e)-[:{rel}]->(t)
        """,
        rows=[{"exercise_id": exercise_id, "term": term} for exercise_id, term in pairs],
        source=GraphSource.KG1.value,
    )


def _merge_anatomy(session: Session, structures: list[AnatomicalStructure]) -> None:
    """Create the authored anatomy hierarchy and its `part_of` containment.

    The nine joints the catalog names are already present; merging by name
    binds those nodes and adds their SNOMED grounding rather than duplicating.

    Args:
        session: An open Neo4j session.
        structures: Every authored structure.

    Raises:
        ValueError: If a `part_of` parent names a structure that does not
            exist. A dangling parent would leave the hierarchy quietly severed,
            and a severed hierarchy returns too few exercises rather than
            erroring, so it has to fail here.
    """
    session.run(
        f"""
        UNWIND $rows AS row
        MERGE (a:{NodeLabel.ANATOMICAL_STRUCTURE} {{name: row.name}})
        SET a.tier = row.tier,
            a.snomed_code = row.snomed_code,
            a.snomed_term = row.snomed_term,
            a.source = $source
        """,
        rows=[s.model_dump(mode="json") for s in structures],
        source=GraphSource.KG1.value,
    )

    pairs = [(s.name, s.part_of) for s in structures if s.part_of]
    linked = session.run(
        f"""
        UNWIND $rows AS row
        MATCH (child:{NodeLabel.ANATOMICAL_STRUCTURE} {{name: row.child}})
        MATCH (parent:{NodeLabel.ANATOMICAL_STRUCTURE} {{name: row.parent}})
        MERGE (child)-[:{RelType.PART_OF}]->(parent)
        RETURN count(*) AS linked
        """,
        rows=[{"child": child, "parent": parent} for child, parent in pairs],
    ).single()["linked"]

    if linked != len(pairs):
        raise ValueError(
            f"part_of resolved {linked} of {len(pairs)} edges — a parent name in "
            f"anatomy.json does not match any structure"
        )


def _merge_stresses(session: Session, exercises: list[Exercise]) -> None:
    """Connect each exercise to the joints it loads.

    Matches rather than merges, and pins the match to the joint tier: anatomy
    is authored, so a term the catalog names must already exist, and `stresses`
    may only ever reach a joint.

    Args:
        session: An open Neo4j session.
        exercises: Every catalog row.

    Raises:
        ValueError: If the catalog names a joint absent from `anatomy.json`.
            Merging instead would invent an ungrounded node; matching silently
            would drop the edge and quietly widen what the injury filter allows.
    """
    named = sorted({joint for ex in exercises for joint in ex.joints_loaded})
    found = session.run(
        f"""
        MATCH (a:{NodeLabel.ANATOMICAL_STRUCTURE} {{tier: $tier}})
        WHERE a.name IN $names
        RETURN collect(a.name) AS found
        """,
        names=named,
        tier=AnatomicalTier.JOINT.value,
    ).single()["found"]

    if missing := sorted(set(named) - set(found)):
        raise ValueError(f"catalog joints missing from anatomy.json: {missing}")

    session.run(
        f"""
        UNWIND $rows AS row
        MATCH (e:{NodeLabel.EXERCISE} {{id: row.exercise_id}})
        MATCH (a:{NodeLabel.ANATOMICAL_STRUCTURE} {{name: row.term, tier: $tier}})
        MERGE (e)-[:{RelType.STRESSES}]->(a)
        """,
        rows=[
            {"exercise_id": ex.id, "term": joint}
            for ex in exercises
            for joint in ex.joints_loaded
        ],
        tier=AnatomicalTier.JOINT.value,
    )


def build_kg1(session: Session, exercises_path: Path, anatomy_path: Path) -> BuildReport:
    """Build the movement/clinical graph.

    Idempotent: every write is a `MERGE`, so re-running against a populated
    store converges rather than duplicating. Order is load-bearing — constraints
    first, or the merges degrade to full label scans; anatomy before `stresses`,
    which matches the joints it creates.

    Args:
        session: An open Neo4j session.
        exercises_path: Location of `exercises.json`.
        anatomy_path: Location of the authored `anatomy.json`.

    Returns:
        Node and edge counts read back from the store after the build.

    Raises:
        FileNotFoundError: If either source file is missing.
        pydantic.ValidationError: If a row does not match the expected shape.
        ValueError: If the anatomy hierarchy is severed, or the catalog names a
            joint that anatomy.json does not.
    """
    exercises = load_exercises(exercises_path)
    structures = load_anatomy(anatomy_path)

    _apply_constraints(session)
    _merge_exercises(session, exercises)
    _merge_anatomy(session, structures)

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
    _merge_stresses(session, exercises)

    return read_report(session)
