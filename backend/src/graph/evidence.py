from pydantic import BaseModel, ConfigDict

from graph.schema import NodeLabel, RelType


class Hop(BaseModel):
    """One edge in a traversal, as provenance."""

    model_config = ConfigDict(frozen=True)

    rel: RelType
    to_label: NodeLabel
    to_name: str

    def render(self) -> str:
        """One hop as prose: ``-diagnosed_as-> patellofemoral pain syndrome``."""
        return f"-{self.rel}-> {self.to_name}"


class EvidencePath(BaseModel):
    """The hop chain behind a decision — the graph traversal, verbatim.

    PROV-O aligned: the `used` entity chain of the activity that produced a
    verdict. `entry` is the identifier the traversal started from.
    """

    model_config = ConfigDict(frozen=True)

    entry: str
    hops: tuple[Hop, ...] = ()

    def render(self) -> str:
        """The whole path as one coach-readable line."""
        return " ".join([self.entry, *(hop.render() for hop in self.hops)])
