import sys

from graph.driver import graph_session
from graph.schema import NodeLabel
from resolve.resolver import Resolver
from resolve.vocabulary import Vocabulary
from settings import settings


def main(argv: list[str]) -> int:
    """Resolve a term from the command line and show the working.

    Prints which pass fired, the score, and the ranked near-misses — the parts
    a passing test does not show you. Useful when adding an alias, to see what
    the automatic passes were reaching for first.

    Usage:
        python -m resolve.probe "bad lower back" [Label ...]

    Args:
        argv: Term first, then any labels to restrict to.

    Returns:
        0 if the term resolved, 1 if it did not.
    """
    if not argv:
        print('usage: python -m resolve.probe "<term>" [Label ...]', file=sys.stderr)
        return 1

    term, *label_names = argv
    try:
        labels = frozenset(NodeLabel(name) for name in label_names) or None
    except ValueError as exc:
        print(f"{exc}\nvalid labels: {', '.join(label.value for label in NodeLabel)}", file=sys.stderr)
        return 1

    with graph_session() as session:
        vocabulary = Vocabulary.load(session, settings.aliases_path)
    result = Resolver(vocabulary).resolve(term, labels)

    print(f'term        {result.term!r}')
    print(f"normalized  {result.normalized!r}" + (f"   side={result.side}" if result.side else ""))
    print(f"restricted  {sorted(label.value for label in labels) if labels else 'no'}")
    if result.match:
        print(f"\nMATCH       {result.match.name}  [{result.match.label}]")
        print(f"            via {result.match.matched_by} at {result.match.score:.3f}")
    else:
        print(f"\nNO MATCH    {result.reason}")

    if result.candidates:
        print("\ncandidates")
        for candidate in result.candidates:
            print(f"   {candidate.score:.3f}  {candidate.name:<34} [{candidate.label}]")
    return 0 if result.resolved else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
