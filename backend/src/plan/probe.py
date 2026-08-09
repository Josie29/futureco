import argparse
import sys

from graph.driver import graph_session
from resolve.resolver import Resolver
from resolve.vocabulary import Vocabulary
from safety.constraints import ConstraintKind, Op
from safety.directives import Instruction
from settings import settings

from plan.pipeline import GeneratedPlan, generate
from plan.schemas import Section

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


def render(generated: GeneratedPlan, paths: bool) -> str:
    """Render a plan the way a coach and a reviewer each need to read it.

    Args:
        generated: The plan and its provenance.
        paths: Whether to print the traversal behind every reason.

    Returns:
        The whole run as plain text.
    """
    plan = generated.plan
    budget = plan.budget
    lines = [
        generated.trace.render(),
        "",
        f"session         {budget.scheduled_seconds // 60}m"
        f"{budget.scheduled_seconds % 60:02d}s of {budget.requested_seconds // 60}m "
        f"requested ({budget.fill_ratio:.0%})",
    ]
    for resolution in generated.focus:
        landed = resolution.match.name if resolution.match else f"no match ({resolution.reason})"
        lines.append(f"emphasis        {resolution.term!r} -> {landed}")

    for section in Section:
        blocks = plan.section(section)
        allotted = budget.allotted(section)
        spent = sum(block.prescription.total_seconds for block in blocks)
        lines += ["", f"{section.value.upper()}  {spent}s of {allotted}s allotted"]
        for block in blocks:
            flag = "  <- anchored on a goal" if block.anchored else ""
            lines.append(
                f"  {block.prescription.render():<24} {block.prescription.total_seconds:>4}s  "
                f"{block.name}{flag}"
            )
            for reason in block.reasons:
                lines.append(f"      {reason.kind.value:<18} {reason.detail}")
                if paths:
                    lines.append(f"      {'':<18} {reason.path.render()}")

    offered = [s for s in generated.substitutions if s.satisfied]
    missing = [s for s in generated.substitutions if not s.satisfied]
    lines += ["", f"substitutions   {len(offered)} offered, {len(missing)} with no stand-in"]
    for substitution in offered:
        lines.append(
            f"  {substitution.dropped_name} -> {substitution.replacement_name} "
            f"({substitution.shared_pattern})"
        )

    if plan.shortfalls:
        lines += ["", "shortfalls"]
        for shortfall in plan.shortfalls:
            cause = f"  [{shortfall.cause}]" if shortfall.cause else ""
            lines.append(f"  {shortfall.kind.value:<22} {shortfall.detail}{cause}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Build a plan from the command line and show the working.

    The whole generator with no language model in it: instructions go in as
    `op:kind:phrase` rather than prose, which is the same path the API serves
    when a request arrives with no prompt. That is what makes the worked
    examples in the README reproducible without an API key.

    Returns:
        0 always; a thin plan is reported, not treated as failure.
    """
    parser = argparse.ArgumentParser(prog="plan.probe", description=main.__doc__)
    parser.add_argument("--member", default="mbr_01HX9JORDAN")
    parser.add_argument("--minutes", type=int, default=50)
    parser.add_argument("--emphasis", action="append", default=[], metavar="MUSCLE")
    parser.add_argument("--paths", action="store_true", help="print the traversal per reason")
    parser.add_argument("instructions", nargs="*", type=_instruction, metavar="op:kind:phrase")
    args = parser.parse_args(argv)

    with graph_session() as session:
        resolver = Resolver(Vocabulary.load(session, settings.aliases_path))
        generated = generate(
            session,
            resolver,
            args.member,
            args.minutes,
            tuple(args.instructions),
            tuple(args.emphasis),
        )
        print(render(generated, args.paths))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
