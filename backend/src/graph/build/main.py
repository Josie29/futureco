import sys

from graph.driver import graph_session
from graph.build.kg1 import build_kg1
from settings import settings


def main() -> int:
    """Build every knowledge graph against the configured store.

    Returns:
        0 on success, 1 if the build could not complete.
    """
    try:
        with graph_session() as session:
            report = build_kg1(session, settings.exercises_path)
    except Exception as exc:  # noqa: BLE001 - top-level CLI boundary
        print(f"graph build failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"KG1 built: {report.node_total} nodes, {report.edge_total} edges")
    for label, count in report.nodes_by_label.items():
        print(f"  {label:<22} {count:>4}")
    for rel, count in report.edges_by_type.items():
        print(f"  {f'-[{rel}]->':<22} {count:>4}")  # inner f-string renders "-[targets]->"
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
