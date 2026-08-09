import json
from pathlib import Path

from neo4j import Session

from graph.build.catalog import (
    AnatomicalStructure,
    Condition,
    Muscle,
    load_anatomy,
    load_conditions,
    load_exercises,
    load_muscles,
)
from graph.build.member import Injury, load_member_context
from graph.build.writes import EdgeWrite, NodeMatch, link_required, merge_nodes
from graph.schema import AnatomicalTier, GraphSource, NodeLabel, RelType
from graph.skos import SCHEME_OF, Collection, MatchType, Scheme, collection_of, load_collections
from resolve.vocabulary import Alias

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


def _apply_skos(
    session: Session,
    muscles: list[Muscle],
    structures: list[AnatomicalStructure],
    conditions: list[Condition],
    collections: dict[NodeLabel, list[Collection]],
    aliases_path: Path,
) -> None:
    """Write the SKOS layer onto the taxonomy nodes that already exist.

    Properties only — no new nodes, no new edges. Most of this is naming what
    the graph already had: the catalogue name becomes `pref_label`, the alias
    file becomes `alt_labels`, and the SNOMED columns become a typed mapping
    with the relation that was authored beside them.

    Every concept gets a scheme. Only the two clinically meaningful taxonomies
    get an external mapping; patterns and equipment get a collection instead,
    for the reason `docs/ontologies.md` gives.

    Args:
        session: An open Neo4j session.
        muscles: Authored muscle mappings.
        structures: The anatomy hierarchy, which carries its own SNOMED codes.
        conditions: Clinical conditions, likewise.
        collections: Authored collections over patterns and equipment.
        aliases_path: Location of `aliases.json`, the altLabel set.

    Raises:
        ValueError: If a collection places one concept twice, or if the
            authored members do not exactly cover the taxonomy in the graph. A
            partition that has drifted from the catalogue is worse than none:
            it reads as complete while silently omitting a concept.
    """
    aliases = [Alias.model_validate(row) for row in json.loads(aliases_path.read_text())]
    alt_labels: dict[tuple[str, str], list[str]] = {}
    for alias in aliases:
        alt_labels.setdefault((alias.label, alias.canonical), []).append(alias.term)

    def rows(label: NodeLabel, names: list[str]) -> list[dict]:
        return [
            {
                "name": name,
                "pref_label": name,
                "alt_labels": sorted(alt_labels.get((label.value, name), [])),
                "in_scheme": SCHEME_OF[label].value,
            }
            for name in names
        ]

    # The externally grounded half: muscles, anatomy and conditions.
    mapped: list[tuple[NodeLabel, list[dict]]] = [
        (
            NodeLabel.MUSCLE,
            [
                {**row, "match_type": muscle.match.value, "match_code": muscle.snomed_code,
                 "match_term": muscle.snomed_term, "match_scheme": Scheme.SNOMED.value}
                for muscle, row in zip(
                    muscles, rows(NodeLabel.MUSCLE, [m.name for m in muscles]), strict=True
                )
            ],
        ),
        (
            NodeLabel.ANATOMICAL_STRUCTURE,
            [
                # Anatomy rows predate the `match` field and are all direct
                # structure lookups, so they default to exactMatch. The one
                # row that is not — patellar tendon, which SNOMED calls a
                # ligament — is called out in docs/ontologies.md rather than
                # given a column the other 26 rows would leave empty.
                {**row, "match_type": MatchType.EXACT.value, "match_code": structure.snomed_code,
                 "match_term": structure.snomed_term, "match_scheme": Scheme.SNOMED.value}
                for structure, row in zip(
                    structures,
                    rows(NodeLabel.ANATOMICAL_STRUCTURE, [s.name for s in structures]),
                    strict=True,
                )
            ],
        ),
        (
            NodeLabel.CONDITION,
            [
                {**row, "match_type": MatchType.EXACT.value, "match_code": condition.snomed_code,
                 "match_term": condition.snomed_term, "match_scheme": Scheme.SNOMED.value}
                for condition, row in zip(
                    conditions,
                    rows(NodeLabel.CONDITION, [c.condition for c in conditions]),
                    strict=True,
                )
            ],
        ),
    ]

    for label, payload in mapped:
        session.run(
            f"""
            UNWIND $rows AS row
            MATCH (n:{label} {{name: row.name}})
            SET n.pref_label = row.pref_label,
                n.alt_labels = row.alt_labels,
                n.in_scheme = row.in_scheme,
                n.match_type = row.match_type,
                n.match_scheme = row.match_scheme,
                n.match_code = row.match_code,
                n.match_term = row.match_term
            """,
            rows=payload,
        )

    # The locally scoped half: patterns and equipment, grouped rather than mapped.
    for label, groups in collections.items():
        placed = collection_of(groups)
        present = {
            record["name"]
            for record in session.run(f"MATCH (n:{label}) RETURN n.name AS name")
        }
        if missing := present - set(placed):
            raise ValueError(f"{label} concepts in no collection: {sorted(missing)}")
        if unknown := set(placed) - present:
            raise ValueError(f"collections name absent {label} concepts: {sorted(unknown)}")

        session.run(
            f"""
            UNWIND $rows AS row
            MATCH (n:{label} {{name: row.name}})
            SET n.pref_label = row.pref_label,
                n.alt_labels = row.alt_labels,
                n.in_scheme = row.in_scheme,
                n.collection = row.collection
            """,
            rows=[
                {**row, "collection": placed[row["name"]]}
                for row in rows(label, sorted(present))
            ],
        )


def build_kg1(
    session: Session,
    exercises_path: Path,
    anatomy_path: Path,
    member_context_path: Path,
    contraindications_path: Path,
    muscles_path: Path,
    collections_path: Path,
    aliases_path: Path,
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
        muscles_path: Location of the authored muscle-to-SNOMED mappings.
        collections_path: Location of the authored SKOS collections.
        aliases_path: Location of `aliases.json`, read here as the altLabel set.

    Raises:
        FileNotFoundError: If a source file is missing.
        pydantic.ValidationError: If a row does not match the expected shape.
        ValueError: If any edge fails to resolve — a severed anatomy hierarchy,
            a joint the catalog names but anatomy.json lacks, a rule naming an
            unknown pattern, or an injury naming an unknown condition. Also if
            the authored collections have drifted from the catalogue.
    """
    exercises = load_exercises(exercises_path)
    structures = load_anatomy(anatomy_path)
    conditions = load_conditions(contraindications_path)
    muscles = load_muscles(muscles_path)
    collections = load_collections(collections_path)
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
    # Last, because it annotates concepts every step above creates. Nothing
    # downstream reads these properties to make a decision — they are the
    # vocabulary's own description of itself.
    _apply_skos(session, muscles, structures, conditions, collections, aliases_path)
