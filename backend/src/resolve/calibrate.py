import sys
from itertools import product

from pydantic import BaseModel, ConfigDict

from graph.driver import graph_session
from resolve.cases import ResolverCase, load_cases
from resolve.resolver import Resolver, Thresholds
from resolve.vocabulary import Vocabulary
from settings import settings

# Swept in hundredths across the range where either pass could plausibly sit.
_FUZZY_RANGE = [round(0.80 + 0.01 * step, 2) for step in range(20)]
_VECTOR_RANGE = [round(0.40 + 0.01 * step, 2) for step in range(50)]


class Outcome(BaseModel):
    """How one threshold pair fared against the labelled cases."""

    model_config = ConfigDict(frozen=True)

    thresholds: Thresholds
    correct: int
    total: int
    false_positives: list[str]
    misses: list[str]

    @property
    def passes(self) -> bool:
        """Whether every case behaved as labelled."""
        return self.correct == self.total


def evaluate(resolver: Resolver, cases: list[ResolverCase]) -> Outcome:
    """Run every case against one resolver configuration.

    Args:
        resolver: A resolver built with the thresholds under test.
        cases: The labelled cases.

    Returns:
        The tally, with failures split by kind. False positives are the ones
        that matter: resolving a term that has no correct answer is a wrong
        answer delivered confidently, while a miss merely declines to help.
    """
    false_positives: list[str] = []
    misses: list[str] = []
    for case in cases:
        result = resolver.resolve(case.term, case.labels)
        got = result.match.name if result.match else None
        side_ok = case.expects_side is None or result.side == case.expects_side
        if got == case.expects and side_ok:
            continue
        if case.must_decline or (got is not None and got != case.expects):
            false_positives.append(f"{case.term!r} -> {got!r}")
        else:
            misses.append(f"{case.term!r} expected {case.expects!r}")
    return Outcome(
        thresholds=resolver.thresholds,
        correct=len(cases) - len(false_positives) - len(misses),
        total=len(cases),
        false_positives=false_positives,
        misses=misses,
    )


def main() -> int:
    """Sweep both thresholds against the labelled cases and report the range.

    Prints every pair that passes cleanly, so the committed constants can be
    chosen from the middle of a working band rather than from its edge — a
    threshold sitting one hundredth from failure is not calibrated, it is lucky.

    Returns:
        0 if any threshold pair passes every case, 1 if none does.
    """
    cases = load_cases(settings.resolver_cases_path)
    with graph_session() as session:
        vocabulary = Vocabulary.load(session, settings.aliases_path)

    # Warm the model once; every configuration reuses the same vectors.
    vocabulary.similarities("warm")

    passing: list[Thresholds] = []
    for fuzzy, vector in product(_FUZZY_RANGE, _VECTOR_RANGE):
        thresholds = Thresholds(fuzzy=fuzzy, vector=vector)
        if evaluate(Resolver(vocabulary, thresholds), cases).passes:
            passing.append(thresholds)

    if not passing:
        print(f"no threshold pair passes all {len(cases)} cases", file=sys.stderr)
        worst = evaluate(Resolver(vocabulary), cases)
        for failure in worst.false_positives + worst.misses:
            print(f"  {failure}", file=sys.stderr)
        return 1

    fuzzies = sorted({t.fuzzy for t in passing})
    vectors = sorted({t.vector for t in passing})
    print(f"{len(passing)} of {len(_FUZZY_RANGE) * len(_VECTOR_RANGE)} pairs pass all {len(cases)} cases")
    print(f"  fuzzy  {fuzzies[0]:.2f} .. {fuzzies[-1]:.2f}   midpoint {(fuzzies[0] + fuzzies[-1]) / 2:.3f}")
    print(f"  vector {vectors[0]:.2f} .. {vectors[-1]:.2f}   midpoint {(vectors[0] + vectors[-1]) / 2:.3f}")
    print(f"\ncommitted: fuzzy={Thresholds().fuzzy}  vector={Thresholds().vector}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
