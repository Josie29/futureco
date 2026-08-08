import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class Side(StrEnum):
    """Laterality a coach named, which the graph records on `Injury.side`."""

    LEFT = "left"
    RIGHT = "right"


# Words that describe how a body part feels, or whose body it is, rather than
# which part it is. None of them is a token of any canonical name, so removing
# them cannot destroy a match — checked against the vocabulary in the tests.
_FILLER = frozenset(
    {
        "a", "an", "the", "some", "very", "really", "quite",
        "my", "his", "her", "their", "its",
        "bad", "sore", "tight", "painful", "achy", "stiff", "weak",
        "pain", "pains", "issue", "issues", "problem", "problems",
        "bothering", "hurting", "hurts", "niggle", "flare",
        # Copulas and prepositions that survive an otherwise clean strip and
        # leave debris like "knee is" behind.
        "is", "are", "was", "were", "am", "be", "been", "it", "that", "this",
        "feels", "feeling", "felt", "in", "on", "at", "with", "and", "of", "for",
    }
)

_SIDES = {"left": Side.LEFT, "l": Side.LEFT, "right": Side.RIGHT, "r": Side.RIGHT}

# Hyphens and slashes join words in canonical names ("Resistance Band - Loop",
# "Push-Up to Knee-Drive"), so they become spaces rather than being deleted —
# deleting would fuse tokens and defeat token-set matching.
_SEPARATORS = re.compile(r"[-–—/,()]+")
_NON_WORD = re.compile(r"[^a-z0-9\s]+")
_WHITESPACE = re.compile(r"\s+")


class NormalizedTerm(BaseModel):
    """A coach's words, reduced to something comparable with canonical names."""

    model_config = ConfigDict(frozen=True)

    original: str
    text: str
    side: Side | None = None

    @property
    def is_empty(self) -> bool:
        """Whether normalisation removed everything, leaving nothing to match."""
        return not self.text


def normalize(term: str) -> NormalizedTerm:
    """Reduce free text to a comparable form, keeping the laterality.

    Laterality is extracted rather than discarded because it is clinically
    load-bearing downstream: a left-knee complaint matches the recorded
    `inj_knee_left`, a right-knee one does not. Plurals are deliberately left
    alone — most muscle names are already plural (`quads`, `triceps`), so
    stripping a trailing `s` would break more than it fixed. Fuzzy matching
    handles `dumbbells` reaching `dumbbell` instead.

    Args:
        term: What the coach typed, such as "her left knee is bothering her".

    Returns:
        The normalised text, any side found, and the original for the trace.
    """
    lowered = _SEPARATORS.sub(" ", term.lower())
    lowered = _NON_WORD.sub("", lowered)

    side: Side | None = None
    kept: list[str] = []
    for token in _WHITESPACE.split(lowered):
        if not token:
            continue
        if token in _SIDES:
            # First side named wins; "left knee, right ankle" is two terms and
            # should be split by the caller before it reaches here.
            side = side or _SIDES[token]
            continue
        if token in _FILLER:
            continue
        kept.append(token)

    return NormalizedTerm(original=term, text=" ".join(kept), side=side)
