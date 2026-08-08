from pathlib import Path

from neo4j import Session

from graph.build.catalog import (
    AnatomicalStructure,
    Condition,
    load_anatomy,
    load_conditions,
    load_exercises,
)
from graph.build.member import Injury, load_member_context
from graph.build.writes import EdgeWrite, NodeMatch, link_required, merge_nodes
from graph.schema import AnatomicalTier, GraphSource, NodeLabel, RelType

_ANATOMY = NodeMatch(label=NodeLabel.ANATOMICAL_STRUCTURE)
_JOINT = NodeMatch(label=NodeLabel.ANATOMICAL_STRUCTURE, tier=AnatomicalTier.JOINT)
_EXERCISE = NodeMatch(label=NodeLabel.EXERCISE, key="id")
_INJURY = NodeMatch(label=NodeLabel.INJURY, key="id")
_CONDITION = NodeMatch(label=NodeLabel.CONDITION)
_PATTERN = NodeMatch(label=NodeLabel.MOVEMENT_PATTERN)

_PART_OF = EdgeWrite(rel=RelType.PART_OF, source=_ANATOMY, target=_ANATOMY)
_STRESSES = EdgeWrite(rel=RelType.STRESSES, source=_EXERCISE, target=_JOINT)
_DIAGNOSED_AS = EdgeWrite(rel=RelType.DIAGNOSED_AS, source=_INJURY, target=_CONDITION)
_AFFECTS = EdgeWrite(rel=RelType.AFFECTS, source=_INJURY, target=_JOINT)


def _apply_constraints(session: Session) -> None:
    """Declare uniqueness constraints, which also creates the backing indexes.

    Without these, `MERGE` scans every node of the label and the build is
    quadratic; they also make a duplicate key an error rather than a silent
    second node.
    """
    # Labels and property keys cannot be query parameters in Cypher, so they are
    # interpolated. Values come from the NodeLabel enum, never from input data.
    for label in (NodeLabel.EXERCISE, NodeLabel.INJURY):
        session.run(
            f"CREATE CONSTRAINT {label.lower()}_id IF NOT EXISTS "
            f"FOR (n:{label}) REQUIRE n.id IS UNIQUE"
        )
    for label in (
        NodeLabel.MUSCLE,
        NodeLabel.EQUIPMENT,
        NodeLabel.MOVEMENT_PATTERN,
        NodeLabel.ANATOMICAL_STRUCTURE,
        NodeLabel.CONDITION,
    ):
        session.run(
            f"CREATE CONSTRAINT {label.lower()}_name IF NOT EXISTS "
            f"FOR (n:{label}) REQUIRE n.name IS UNIQUE"
        )


def _merge_taxonomy(
    session: Session,
    label: NodeLabel,
    rel: RelType,
    pairs: list[tuple[str, str]],
) -> None:
    """Create the taxonomy nodes exercises name, and the edges reaching them.

    Every muscle, equipment, and pattern node exists because some exercise
    names it, so the node and the edge to it are merged in a single statement.
    Anatomy is the exception — it is authored, so `stresses` matches an
    existing node rather than creating one.

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


def _build_anatomy(session: Session, structures: list[AnatomicalStructure]) -> None:
    """Create the authored anatomy hierarchy and its `part_of` containment.

    The nine joints the catalog names are already present; merging by name
    binds those nodes and adds their SNOMED grounding rather than duplicating.
    `snomed_query` and `part_of` stay off the node: the first is authoring
    metadata, and the second is the edge written below.
    """
    merge_nodes(
        session,
        NodeLabel.ANATOMICAL_STRUCTURE,
        "name",
        [
            {
                "name": structure.name,
                "tier": structure.tier.value,
                "snomed_code": structure.snomed_code,
                "snomed_term": structure.snomed_term,
            }
            for structure in structures
        ],
        GraphSource.KG1,
    )
    link_required(
        session,
        _PART_OF,
        [
            {"source": structure.name, "target": structure.part_of}
            for structure in structures
            if structure.part_of
        ],
    )


def _build_conditions(session: Session, conditions: list[Condition]) -> None:
    """Create clinical conditions and the movement rules that attach to them.

    The rules hang off the condition rather than off any member's injury: what
    patellofemoral pain rules out is true of the condition, so it is stated
    once and every case of it inherits the same edges.
    """
    merge_nodes(
        session,
        NodeLabel.CONDITION,
        "name",
        [
            {
                "name": condition.condition,
                "snomed_code": condition.snomed_code,
                "snomed_term": condition.snomed_term,
                "source_note": condition.source_note,
            }
            for condition in conditions
        ],
        GraphSource.KG1,
    )
    # One call per relation, because a relationship type cannot be a query
    # parameter. Both carry the authored rationale onto the edge, which is what
    # a provenance trace reads to explain a filtered exercise.
    for relation in (RelType.CONTRAINDICATES, RelType.CAUTIONS):
        link_required(
            session,
            EdgeWrite(
                rel=relation,
                source=_CONDITION,
                target=_PATTERN,
                properties=("rationale",),
            ),
            [
                {
                    "source": condition.condition,
                    "target": rule.pattern,
                    "rationale": rule.rationale,
                }
                for condition in conditions
                for rule in condition.rules
                if rule.relation == relation
            ],
        )


def _build_injuries(session: Session, injuries: list[Injury]) -> None:
    """Create injuries, and link each to its condition and the joint it sits at.

    An injury carries only what is true of this member's case — laterality,
    status, severity, when it started. What the condition implies for movement
    lives on the `Condition` it is diagnosed as.
    """
    merge_nodes(
        session,
        NodeLabel.INJURY,
        "id",
        [
            {
                "id": injury.id,
                "region": injury.region,
                "joint": injury.joint,
                "side": injury.side,
                "status": injury.status.value,
                "severity": injury.severity.value,
                "since": injury.since.isoformat(),
                "notes": injury.notes,
            }
            for injury in injuries
        ],
        GraphSource.KG1,
    )
    link_required(
        session,
        _DIAGNOSED_AS,
        [{"source": injury.id, "target": injury.condition} for injury in injuries],
    )
    link_required(
        session,
        _AFFECTS,
        [{"source": injury.id, "target": injury.joint} for injury in injuries],
    )


def build_kg1(
    session: Session,
    exercises_path: Path,
    anatomy_path: Path,
    member_context_path: Path,
    contraindications_path: Path,
) -> None:
    """Build the movement/clinical graph.

    Idempotent: every write is a `MERGE`, so re-running against a populated
    store converges rather than duplicating. Order is load-bearing — constraints
    first, or the merges degrade to full label scans; anatomy before `stresses`,
    which matches the joints it creates; patterns before the rules naming them;
    conditions before the injuries diagnosed as them.

    Args:
        session: An open Neo4j session.
        exercises_path: Location of `exercises.json`.
        anatomy_path: Location of the authored `anatomy.json`.
        member_context_path: Location of `member-context.json`, read for its
            injuries only — the rest of the member is KG2's.
        contraindications_path: Location of the authored rules.

    Raises:
        FileNotFoundError: If a source file is missing.
        pydantic.ValidationError: If a row does not match the expected shape.
        ValueError: If any edge fails to resolve — a severed anatomy hierarchy,
            a joint the catalog names but anatomy.json lacks, a rule naming an
            unknown pattern, or an injury naming an unknown condition.
    """
    exercises = load_exercises(exercises_path)
    structures = load_anatomy(anatomy_path)
    conditions = load_conditions(contraindications_path)
    injuries = load_member_context(member_context_path).injuries

    _apply_constraints(session)
    merge_nodes(
        session,
        NodeLabel.EXERCISE,
        "id",
        [exercise.model_dump() for exercise in exercises],
        GraphSource.KG1,
    )
    _build_anatomy(session, structures)

    for label, rel, terms in (
        (NodeLabel.MUSCLE, RelType.TARGETS, lambda ex: ex.muscle_groups),
        (NodeLabel.EQUIPMENT, RelType.REQUIRES, lambda ex: ex.equipment_required),
        (NodeLabel.MOVEMENT_PATTERN, RelType.IS_A, lambda ex: ex.movement_patterns),
    ):
        _merge_taxonomy(
            session,
            label,
            rel,
            [(ex.id, term) for ex in exercises for term in terms(ex)],
        )

    link_required(
        session,
        _STRESSES,
        [
            {"source": ex.id, "target": joint}
            for ex in exercises
            for joint in ex.joints_loaded
        ],
    )
    _build_conditions(session, conditions)
    _build_injuries(session, injuries)
