import argparse
import sys

from graph.driver import graph_session
from resolve.resolver import Resolver
from resolve.vocabulary import Vocabulary
from safety.constraints import ConstraintKind, Op, compose
from safety.directives import Instruction, to_directives
from safety.filter import run
from safety.queries import ALL_QUERIES
from safety.standing import load_standing
from safety.trace import trace
from settings import settings

_KINDS = {
    "equipment": ConstraintKind.EQUIPMENT,
    "exercise": ConstraintKind.EXCLUDED_EXERCISE,
    "pattern": ConstraintKind.EXCLUDED_PATTERN,
    "anatomy": ConstraintKind.FLAGGED_STRUCTURE,
}


def _instruction(spec: str) -> Instruction:
    """Parse `op:kind:phrase`, e.g. `replace:equipment:dumbbells`.

    Args:
        spec: The colon-separated instruction.

    Returns:
        The parsed instruction.

    Raises:
        argparse.ArgumentTypeError: If the operation or kind is unknown.
    """
    try:
        op, kind, phrase = spec.split(":", 2)
        return Instruction(op=Op(op), kind=_KINDS[kind], phrase=phrase)
    except (ValueError, KeyError) as exc:
        raise argparse.ArgumentTypeError(
            f"{spec!r} is not op:kind:phrase — ops are "
            f"{', '.join(o.value for o in Op)}; kinds are {', '.join(_KINDS)}"
        ) from exc


def main(argv: list[str] | None = None) -> int:
    """Run the safety filter from the command line and show the working.

    Prints the constraint fold, what each instruction resolved to, the removal
    breakdown counted both ways, and the ranked verdicts with their headlines —
    the parts a passing test does not show you.

    Returns:
        0 always; a thin pool is reported, not treated as failure.
    """
    parser = argparse.ArgumentParser(prog="safety.probe", description=main.__doc__)
    parser.add_argument("--member", default="mbr_01HX9JORDAN")
    parser.add_argument("--limit", type=int, default=12, help="verdicts to print")
    parser.add_argument("--show-excluded", action="store_true")
    parser.add_argument("--show-cypher", action="store_true", help="print the queries and exit")
    parser.add_argument("instructions", nargs="*", type=_instruction, metavar="op:kind:phrase")
    args = parser.parse_args(argv)

    if args.show_cypher:
        for name, cypher in ALL_QUERIES.items():
            print(f"── {name} " + "─" * (60 - len(name)))
            print(cypher.strip())
        return 0

    with graph_session() as session:
        resolver = Resolver(Vocabulary.load(session, settings.aliases_path))
        composition = compose(
            load_standing(session, args.member), to_directives(resolver, args.instructions)
        )
        result = run(session, composition)
        rendered = trace(session, result).render()

    print(rendered)
    print("\nverdicts")
    shown = result.verdicts if args.show_excluded else result.eligible
    for verdict in shown[: args.limit]:
        print(f"  p{verdict.penalty} f{verdict.fit}  {verdict.name}")
        print(f"      {verdict.headline}")
        for signal in verdict.signals:
            print(f"      path: {signal.path.render()}")
    if len(shown) > args.limit:
        print(f"  ... {len(shown) - args.limit} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
