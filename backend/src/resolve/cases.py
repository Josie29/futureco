import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from graph.schema import NodeLabel
from resolve.normalize import Side


class ResolverCase(BaseModel):
    """One labelled resolution case.

    The same file drives threshold calibration and the test suite, so a
    threshold cannot be tuned against one set of expectations while the tests
    assert another.

    Attributes:
        term: What a coach would type.
        labels: Labels the call accepts, or None for an unrestricted call.
        expects: The canonical name it must reach, or None if it must decline.
        expects_side: Laterality that must survive normalisation, if any.
        note: Why this case is in the set.
    """

    model_config = ConfigDict(frozen=True)

    term: str
    labels: frozenset[NodeLabel] | None
    expects: str | None
    expects_side: Side | None = None
    note: str

    @property
    def must_decline(self) -> bool:
        """Whether resolving this term at all is the failure."""
        return self.expects is None


def load_cases(path: Path) -> list[ResolverCase]:
    """Read the labelled resolution cases.

    Args:
        path: Location of `resolver_cases.json`.

    Returns:
        Every case, validated.

    Raises:
        FileNotFoundError: If the file is missing.
        pydantic.ValidationError: If a case is malformed.
    """
    return [ResolverCase.model_validate(row) for row in json.loads(path.read_text())]
