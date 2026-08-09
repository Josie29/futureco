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
    CONDITION = "Condition"
    MEMBER = "Member"
    GOAL = "Goal"
    COACH = "Coach"
    SESSION = "Session"
    MESSAGE = "Message"
    OBSERVATION = "Observation"
    METRIC = "Metric"


class RelType(StrEnum):
    """Neo4j relationship types. Values are the literal types used in Cypher."""

    TARGETS = "targets"
    STRESSES = "stresses"
    REQUIRES = "requires"
    IS_A = "is_a"
    PART_OF = "part_of"
    AFFECTS = "affects"
    DIAGNOSED_AS = "diagnosed_as"
    CONTRAINDICATES = "contraindicates"
    CAUTIONS = "cautions"
    HAS = "has"
    DISLIKES = "dislikes"
    COACHES = "coaches"
    TRAINED = "trained"
    MENTIONS = "mentions"
    MEASURES = "measures"
    MEASURED_BY = "measured_by"


class AnatomicalTier(StrEnum):
    """Position within the single `part_of` anatomy hierarchy.

    `stresses` only ever targets `JOINT`; see `docs/kg1-schema.md`.
    """

    REGION = "region"
    JOINT = "joint"
    SUBSTRUCTURE = "substructure"


class MetricCategory(StrEnum):
    """What kind of measurement a `Metric` describes.

    Coarse on purpose: it exists so a copilot can ask for "her biomarkers"
    without naming seven metrics, not to carry clinical taxonomy.
    """

    BIOMARKER = "biomarker"
    LAB = "lab"
    BODY_COMPOSITION = "body_composition"
    ADHERENCE = "adherence"


class MetricDirection(StrEnum):
    """Which way is favourable, for a metric that has a reference band.

    Separate from the band itself because the two answer different questions.
    `optimal_low`/`optimal_high` say whether a value is inside the band;
    direction says what being outside it means. Resting heart rate is the case
    that forces the split: 58 bpm sits below the 60–100 adult band and that is
    a good thing, so a bare "outside the range" reading would be wrong.
    """

    HIGHER_BETTER = "higher_better"
    LOWER_BETTER = "lower_better"
    BAND = "band"
    """Favourable inside the band, unfavourable either side of it."""

    TREND = "trend"
    """No reference band exists. Only movement over time is meaningful."""
