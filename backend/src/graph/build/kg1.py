from pathlib import Path

from neo4j import Session

from graph.build.catalog import (
    AnatomicalStructure,
    Condition,
    Exercise,
    Injury,
    load_anatomy,
    load_conditions,
    load_exercises,
    load_injuries,
)
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
    session.run(
        f"CREATE CONSTRAINT injury_id IF NOT EXISTS "
        f"FOR (n:{NodeLabel.INJURY}) REQUIRE n.id IS UNIQUE"
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


def _merge_conditions(session: Session, conditions: list[Condition]) -> None:
    """Create clinical conditions and the movement rules that attach to them.

    The rules hang off the condition rather than off any member's injury: what
    patellofemoral pain rules out is true of the condition, so it is stated
    once and every case of it inherits the same edges.

    Args:
        session: An open Neo4j session.
        conditions: Authored conditions and their rules.

    Raises:
        ValueError: If a rule names a movement pattern the catalog does not
            have. An unresolved contraindication is this graph's worst failure:
            the build looks healthy, and the filter silently permits a movement
            a clinician ruled out.
    """
    session.run(
        f"""
        UNWIND $rows AS row
        MERGE (c:{NodeLabel.CONDITION} {{name: row.name}})
        SET c.snomed_code = row.snomed_code,
            c.snomed_term = row.snomed_term,
            c.source_note = row.source_note,
            c.source = $source
        """,
        rows=[
            {
                "name": condition.condition,
                "snomed_code": condition.snomed_code,
                "snomed_term": condition.snomed_term,
                "source_note": condition.source_note,
            }
            for condition in conditions
        ],
        source=GraphSource.KG1.value,
    )

    # One statement per relation, because a relationship type cannot be a query
    # parameter. Both carry the authored rationale onto the edge, which is what
    # a provenance trace reads to explain a filtered exercise.
    for relation in (RelType.CONTRAINDICATES, RelType.CAUTIONS):
        rows = [
            {
                "condition": condition.condition,
                "pattern": rule.pattern,
                "rationale": rule.rationale,
            }
            for condition in conditions
            for rule in condition.rules
            if rule.relation == relation
        ]
        if not rows:
            continue
        linked = session.run(
            f"""
            UNWIND $rows AS row
            MATCH (c:{NodeLabel.CONDITION} {{name: row.condition}})
            MATCH (p:{NodeLabel.MOVEMENT_PATTERN} {{name: row.pattern}})
            MERGE (c)-[r:{relation}]->(p)
            SET r.rationale = row.rationale
            RETURN count(*) AS linked
            """,
            rows=rows,
        ).single()["linked"]

        if linked != len(rows):
            raise ValueError(
                f"{relation} resolved {linked} of {len(rows)} rules — a rule names a "
                f"movement pattern the catalog does not have"
            )


def _link_injuries(
    session: Session,
    rel: RelType,
    target_label: NodeLabel,
    pairs: list[tuple[str, str]],
    tier: AnatomicalTier | None = None,
) -> None:
    """Link injuries to nodes that already exist, failing if any does not.

    Args:
        session: An open Neo4j session.
        rel: Edge type running from injury to target.
        target_label: Label of the node being linked to.
        pairs: `(injury_id, target_name)` for every edge to create.
        tier: When given, the target must sit at this anatomical tier.

    Raises:
        ValueError: If any pair fails to resolve. A missing edge here is silent
            in the graph and permissive in the filter, so it cannot pass.
    """
    # Interpolated from a variable, so the braces are literal Cypher rather
    # than f-string placeholders.
    props = "{name: row.target, tier: $tier}" if tier else "{name: row.target}"
    linked = session.run(
        f"""
        UNWIND $rows AS row
        MATCH (i:{NodeLabel.INJURY} {{id: row.id}})
        MATCH (t:{target_label} {props})
        MERGE (i)-[:{rel}]->(t)
        RETURN count(*) AS linked
        """,
        rows=[{"id": injury_id, "target": name} for injury_id, name in pairs],
        tier=tier.value if tier else None,
    ).single()["linked"]

    if linked != len(pairs):
        raise ValueError(
            f"{rel} resolved {linked} of {len(pairs)} edges — an injury names a "
            f"{target_label} that does not exist"
        )


def _merge_injuries(session: Session, injuries: list[Injury]) -> None:
    """Create injuries, and link each to its condition and the joint it sits at.

    An injury carries only what is true of this member's case — laterality,
    status, severity, when it started. What the condition implies for movement
    lives on the `Condition` it is diagnosed as.

    Args:
        session: An open Neo4j session.
        injuries: Injuries recorded for the member.

    Raises:
        ValueError: If an injury names a condition with no authored rules, or
            sits at a joint absent from the anatomy hierarchy.
    """
    session.run(
        f"""
        UNWIND $rows AS row
        MERGE (i:{NodeLabel.INJURY} {{id: row.id}})
        SET i += row, i.source = $source
        """,
        rows=[
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
        source=GraphSource.KG1.value,
    )

    _link_injuries(
        session,
        RelType.DIAGNOSED_AS,
        NodeLabel.CONDITION,
        [(injury.id, injury.condition) for injury in injuries],
    )
    _link_injuries(
        session,
        RelType.AFFECTS,
        NodeLabel.ANATOMICAL_STRUCTURE,
        [(injury.id, injury.joint) for injury in injuries],
        tier=AnatomicalTier.JOINT,
    )


def build_kg1(
    session: Session,
    exercises_path: Path,
    anatomy_path: Path,
    member_context_path: Path,
    contraindications_path: Path,
) -> BuildReport:
    """Build the movement/clinical graph.

    Idempotent: every write is a `MERGE`, so re-running against a populated
    store converges rather than duplicating. Order is load-bearing — constraints
    first, or the merges degrade to full label scans; anatomy before `stresses`,
    which matches the joints it creates.

    Args:
        session: An open Neo4j session.
        exercises_path: Location of `exercises.json`.
        anatomy_path: Location of the authored `anatomy.json`.
        member_context_path: Location of `member-context.json`, read for its
            injuries only — the rest of the member is KG2's.
        contraindications_path: Location of the authored rules.

    Returns:
        Node and edge counts read back from the store after the build.

    Raises:
        FileNotFoundError: If a source file is missing.
        pydantic.ValidationError: If a row does not match the expected shape.
        ValueError: If the anatomy hierarchy is severed, the catalog names a
            joint anatomy.json does not, a contraindication rule names an
            unknown movement pattern, or an injury names an unknown condition
            or joint.
    """
    exercises = load_exercises(exercises_path)
    structures = load_anatomy(anatomy_path)
    injuries = load_injuries(member_context_path)
    conditions = load_conditions(contraindications_path)

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
    # Last, and in this order: the rules need the patterns, and an injury needs
    # both the condition it is diagnosed as and the joint it affects.
    _merge_stresses(session, exercises)
    _merge_conditions(session, conditions)
    _merge_injuries(session, injuries)

    return read_report(session)
