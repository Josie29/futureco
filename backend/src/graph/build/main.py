import sys

from graph.build.kg1 import build_kg1
from graph.build.kg2 import build_kg2
from graph.build.report import read_report
from graph.driver import graph_session
from settings import settings


def main() -> int:
    """Build every knowledge graph against the configured store.

    Returns:
        0 on success, 1 if a build could not complete.
    """
    try:
        with graph_session() as session:
            build_kg1(
                session,
                settings.exercises_path,
                settings.anatomy_path,
                settings.member_context_path,
                settings.contraindications_path,
            )
            unmatched_dislikes = build_kg2(session, settings.member_context_path)
            report = read_report(session)
    except Exception as exc:  # noqa: BLE001 - top-level CLI boundary
        print(f"graph build failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"Built: {report.node_total} nodes, {report.edge_total} edges")
    for label, count in report.nodes_by_label.items():
        print(f"  {label:<22} {count:>4}")
    for rel, count in report.edges_by_type.items():
        print(f"  {f'-[{rel}]->':<22} {count:>4}")  # inner f-string renders "-[targets]->"

    if unmatched_dislikes:
        print(
            f"\nNote: {len(unmatched_dislikes)} disliked exercises are not in the "
            f"catalog, so nothing is excluded for them: {', '.join(unmatched_dislikes)}.\n"
            f"The preference is still recorded on the node."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
