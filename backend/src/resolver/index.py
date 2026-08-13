from neo4j import Session

from resolver.models import Namespace, ResolvedConcept


class ConceptIndex:
    """The in-memory search structure the resolver runs against.

    Built once per process from KG1 plus the authored alias file, namespaced
    from the start: each namespace gets its own surface pool and embedding
    matrix, so a lookup never scans concepts a call site already ruled out.

    Relationship to `graph.vocabulary.Vocabulary`: that one belongs to the KG
    build (exact/alias mention scanning at seed time, no embeddings needed at
    query scale) and stays where it is. This index is the runtime, resolver-
    facing counterpart; if the two converge during the rebuild, the build one
    folds into here — not the other way around.
    """

    @classmethod
    def load(cls, session: Session, aliases_path: str) -> "ConceptIndex":
        """Build the index from the graph and the authored aliases.

        Reads every resolvable concept per namespace, normalises surfaces with
        `core.norm`, and embeds the concept labels (fastembed MiniLM, the model
        already baked into the image). Loading is the expensive step — about a
        second — so the caller owns the instance's lifetime, not this class.

        Args:
            session: An open Neo4j session onto the built graphs.
            aliases_path: Path to data/authored/aliases.json.

        Returns:
            The loaded, ready-to-query index.

        Raises:
            NotImplementedError: Scaffolding; not implemented yet.
        """
        raise NotImplementedError

    def exact(self, surface: str, namespace: Namespace) -> list[ResolvedConcept]:
        """Concepts whose canonical name or alias equals the normalised surface.

        Raises:
            NotImplementedError: Scaffolding; not implemented yet.
        """
        raise NotImplementedError

    def fuzzy(self, surface: str, namespace: Namespace) -> list[ResolvedConcept]:
        """Candidates by token-set similarity, scored, best first.

        Raises:
            NotImplementedError: Scaffolding; not implemented yet.
        """
        raise NotImplementedError

    def nearest(self, surface: str, namespace: Namespace) -> list[ResolvedConcept]:
        """Candidates by embedding cosine, scored, best first.

        Also serves the near-miss report when every pass declines: the honest
        "how far off was it" a coach sees instead of a silent no.

        Raises:
            NotImplementedError: Scaffolding; not implemented yet.
        """
        raise NotImplementedError
