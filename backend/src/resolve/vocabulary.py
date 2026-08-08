import json
from functools import cached_property
from pathlib import Path

import numpy as np
from neo4j import Session
from pydantic import BaseModel, ConfigDict

from graph.schema import NodeLabel
from resolve.normalize import normalize
from settings import settings

# The labels a coach's words can name. Member, Goal, Injury and Condition are
# deliberately absent: they identify one person's records rather than terms
# anyone would type, and resolving onto them would let a phrase reach another
# member's chart.
RESOLVABLE_LABELS: frozenset[NodeLabel] = frozenset(
    {
        NodeLabel.EXERCISE,
        NodeLabel.EQUIPMENT,
        NodeLabel.MUSCLE,
        NodeLabel.MOVEMENT_PATTERN,
        NodeLabel.ANATOMICAL_STRUCTURE,
    }
)

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class Concept(BaseModel):
    """One canonical node a term can resolve to."""

    model_config = ConfigDict(frozen=True)

    name: str
    label: NodeLabel
    normalized: str


class Alias(BaseModel):
    """A lay term mapped onto a canonical name.

    Attributes:
        term: What a coach says.
        canonical: The node name it means.
        label: Which label `canonical` belongs to. Required, because the same
            words can name different things — "lower back" is a Muscle in the
            catalog and, when a coach reports pain, the lumbar spine.
        note: Why the mapping exists, for a reviewer.
    """

    model_config = ConfigDict(frozen=True)

    term: str
    canonical: str
    label: NodeLabel
    note: str


class Vocabulary:
    """Every canonical name, its aliases, and their vectors, held in memory.

    Loaded once from the graph. At 164 concepts the whole thing is a few
    hundred kilobytes, so an index would be lifecycle for nothing — and keeping
    it in process means the resolver is testable without a running database.
    """

    def __init__(self, concepts: list[Concept], aliases: list[Alias]) -> None:
        self.concepts = concepts
        self.aliases = aliases
        self._by_normalized: dict[str, list[Concept]] = {}
        for concept in concepts:
            self._by_normalized.setdefault(concept.normalized, []).append(concept)

        by_name = {(c.label, c.name): c for c in concepts}
        self._by_alias: dict[str, list[Concept]] = {}
        for alias in aliases:
            concept = by_name.get((alias.label, alias.canonical))
            if concept is None:
                raise ValueError(
                    f"alias {alias.term!r} points at {alias.label} {alias.canonical!r}, "
                    f"which is not in the graph"
                )
            self._by_alias.setdefault(normalize(alias.term).text, []).append(concept)

    @classmethod
    def load(cls, session: Session, aliases_path: Path) -> "Vocabulary":
        """Read the resolvable vocabulary from the graph and the alias file.

        Args:
            session: An open Neo4j session.
            aliases_path: Location of `aliases.json`.

        Returns:
            A loaded vocabulary.

        Raises:
            FileNotFoundError: If the alias file is missing.
            pydantic.ValidationError: If an alias row is malformed.
            ValueError: If an alias names a concept the graph does not have.
        """
        rows = session.run(
            """
            UNWIND $labels AS label
            MATCH (n) WHERE label IN labels(n) AND n.name IS NOT NULL
            RETURN labels(n)[0] AS label, n.name AS name
            """,
            labels=[label.value for label in RESOLVABLE_LABELS],
        )
        concepts = [
            Concept(
                name=row["name"],
                label=NodeLabel(row["label"]),
                normalized=normalize(row["name"]).text,
            )
            for row in rows
        ]
        aliases = [Alias.model_validate(row) for row in json.loads(aliases_path.read_text())]
        return cls(concepts, aliases)

    def pool(self, labels: frozenset[NodeLabel] | None) -> list[Concept]:
        """Concepts a call is allowed to resolve onto.

        Args:
            labels: Acceptable labels, or None for every resolvable label.

        Returns:
            The concepts to score against. Filtering here rather than after
            scoring is what stops a restricted call being dragged off by a
            high-scoring name of the wrong kind.
        """
        if labels is None:
            return self.concepts
        return [concept for concept in self.concepts if concept.label in labels]

    def exact(self, normalized: str) -> list[Concept]:
        """Concepts whose canonical name normalises to exactly this text."""
        return self._by_normalized.get(normalized, [])

    def by_alias(self, normalized: str) -> list[Concept]:
        """Concepts an alias maps this text onto."""
        return self._by_alias.get(normalized, [])

    @cached_property
    def _embedder(self):  # noqa: ANN202 - fastembed's type is an implementation detail
        """The embedding model, loaded on first vector lookup.

        Loading costs a second or so, and most terms never reach the vector
        pass, so it stays lazy — exact, alias and fuzzy resolution work with no
        model in memory at all.
        """
        from fastembed import TextEmbedding

        cache_dir = settings.model_cache_dir
        return TextEmbedding(
            model_name=EMBEDDING_MODEL,
            cache_dir=str(cache_dir) if cache_dir else None,
        )

    @cached_property
    def _matrix(self) -> np.ndarray:
        """L2-normalised embeddings of every concept, one row each.

        Normalised at build time so similarity is a plain dot product.
        """
        vectors = np.array(list(self._embedder.embed(c.normalized for c in self.concepts)))
        return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)

    def similarities(self, text: str) -> np.ndarray:
        """Cosine similarity between `text` and every concept, in order.

        Args:
            text: Normalised query text.

        Returns:
            One score per entry of `self.concepts`, aligned by index.
        """
        query = next(iter(self._embedder.embed([text])))
        query = query / np.linalg.norm(query)
        return self._matrix @ query
