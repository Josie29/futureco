from enum import StrEnum


class GraphSource(StrEnum):
    """Which logical subgraph a node was created by.

    One physical graph holds both KGs, so every node carries its origin. See
    `docs/decisions.md`, *Integration*.
    """

    KG1 = "kg1"
    KG2 = "kg2"


class NodeLabel(StrEnum):
    """Neo4j labels. Values are the literal labels used in Cypher."""

    EXERCISE = "Exercise"
    MUSCLE = "Muscle"
    EQUIPMENT = "Equipment"
    MOVEMENT_PATTERN = "MovementPattern"
    ANATOMICAL_STRUCTURE = "AnatomicalStructure"
    INJURY = "Injury"


class RelType(StrEnum):
    """Neo4j relationship types. Values are the literal types used in Cypher."""

    TARGETS = "targets"
    STRESSES = "stresses"
    REQUIRES = "requires"
    IS_A = "is_a"
    PART_OF = "part_of"
    AFFECTS = "affects"
    CONTRAINDICATES = "contraindicates"
    CAUTIONS = "cautions"


class AnatomicalTier(StrEnum):
    """Position within the single `part_of` anatomy hierarchy.

    `stresses` only ever targets `JOINT`; see `docs/kg1-schema.md`.
    """

    REGION = "region"
    JOINT = "joint"
    SUBSTRUCTURE = "substructure"
