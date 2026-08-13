from functools import cached_property

import numpy as np
from neo4j import Session
from pydantic import BaseModel, ConfigDict
from rapidfuzz import fuzz, process

from graph.schema import NodeLabel
from graph.vocabulary import Pass
from resolver.core import norm
from resolver.models import (
    LABEL_TO_NAMESPACE,
    NAMESPACE_LABELS,
    Namespace,
    ResolvedConcept,
    make_concept_id,
)
from settings import settings

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class _Entry(BaseModel):
    """One indexed concept."""

    model_config = ConfigDict(frozen=True)

    concept_id: str
    name: str
    namespace: Namespace
    normalized: str


class ConceptIndex:
    """In-memory, namespaced search structure over KG1's canonical names.

    Built once per process. Vocabulary bridging ("pecs" for "chest") is the
    calling model's job, not an alias layer here.
    """

    def __init__(self, entries: list[_Entry]) -> None:
        self._entries: dict[Namespace, list[_Entry]] = {ns: [] for ns in Namespace}
        self._exact: dict[Namespace, dict[str, list[_Entry]]] = {ns: {} for ns in Namespace}
        for entry in entries:
            self._entries[entry.namespace].append(entry)
            self._exact[entry.namespace].setdefault(entry.normalized, []).append(entry)

    @classmethod
    def load(cls, session: Session) -> "ConceptIndex":
        """Build the index from the graph's resolvable concepts.

        Args:
            session: An open Neo4j session onto the built graphs.

        Returns:
            The loaded, ready-to-query index.
        """
        labels = [label.value for ns in Namespace for label in NAMESPACE_LABELS[ns]]
        rows = session.run(
            """
            UNWIND $labels AS label
            MATCH (n) WHERE label IN labels(n) AND n.name IS NOT NULL
            RETURN labels(n)[0] AS label, n.name AS name
            """,
            labels=labels,
        )
        entries = []
        for row in rows:
            namespace = LABEL_TO_NAMESPACE[NodeLabel(row["label"])]
            entries.append(
                _Entry(
                    concept_id=make_concept_id(namespace, row["name"]),
                    name=row["name"],
                    namespace=namespace,
                    normalized=norm(row["name"]),
                )
            )
        return cls(entries)

    def exact(self, surface: str, namespace: Namespace | None) -> list[ResolvedConcept]:
        """Concepts whose canonical name normalises to exactly this surface.

        Args:
            surface: Normalised query text.
            namespace: Scope, or None for every namespace.

        Returns:
            Every concept named, all at confidence 1.0 — more than one is a
            tie for the caller to decline.
        """
        return [
            self._hit(entry, Pass.EXACT, 1.0, entry.name)
            for ns in self._spaces(namespace)
            for entry in self._exact[ns].get(surface, [])
        ]

    def fuzzy(self, surface: str, namespace: Namespace | None) -> list[ResolvedConcept]:
        """Every in-scope concept scored by token-set ratio, best first.

        Args:
            surface: Normalised query text.
            namespace: Scope, or None for every namespace.

        Returns:
            All candidates, scores in [0, 1], unthresholded — the caller owns
            acceptance.
        """
        pool = [e for ns in self._spaces(namespace) for e in self._entries[ns]]
        matches = process.extract(
            surface,
            {i: entry.normalized for i, entry in enumerate(pool)},
            scorer=fuzz.token_set_ratio,
            limit=None,
        )
        scored = [
            self._hit(pool[i], Pass.FUZZY, score / 100, pool[i].normalized)
            for _, score, i in matches
        ]
        return sorted(scored, key=lambda c: c.confidence, reverse=True)

    def vector(self, surface: str, namespace: Namespace | None) -> list[ResolvedConcept]:
        """Every in-scope concept scored by embedding cosine, best first.

        Args:
            surface: Normalised query text.
            namespace: Scope, or None for every namespace.

        Returns:
            All candidates with cosine scores, unthresholded — the caller owns
            acceptance.
        """
        query = next(iter(self._embedder.embed([surface])))
        query = query / np.linalg.norm(query)
        scored: list[ResolvedConcept] = []
        for ns in self._spaces(namespace):
            entries = self._entries[ns]
            if not entries:
                continue
            similarities = self._matrix(ns) @ query
            scored.extend(
                self._hit(entry, Pass.VECTOR, float(sim), entry.normalized)
                for entry, sim in zip(entries, similarities, strict=True)
            )
        return sorted(scored, key=lambda c: c.confidence, reverse=True)

    @staticmethod
    def _spaces(namespace: Namespace | None) -> tuple[Namespace, ...]:
        return (namespace,) if namespace else tuple(Namespace)

    @staticmethod
    def _hit(entry: _Entry, method: Pass, confidence: float, via: str) -> ResolvedConcept:
        return ResolvedConcept(
            concept_id=entry.concept_id,
            label=entry.name,
            namespace=entry.namespace,
            method=method,
            confidence=round(confidence, 4),
            matched_via=via,
        )

    @cached_property
    def _embedder(self):  # noqa: ANN202 - fastembed's type is an implementation detail
        """The embedding model, loaded lazily on first vector lookup."""
        from fastembed import TextEmbedding

        cache_dir = settings.model_cache_dir
        return TextEmbedding(
            model_name=EMBEDDING_MODEL,
            cache_dir=str(cache_dir) if cache_dir else None,
        )

    def _matrix(self, namespace: Namespace) -> np.ndarray:
        """L2-normalised embeddings for one namespace, one row per concept."""
        if not hasattr(self, "_matrices"):
            self._matrices: dict[Namespace, np.ndarray] = {}
        if namespace not in self._matrices:
            vectors = np.array(
                list(self._embedder.embed(e.normalized for e in self._entries[namespace]))
            )
            self._matrices[namespace] = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
        return self._matrices[namespace]
