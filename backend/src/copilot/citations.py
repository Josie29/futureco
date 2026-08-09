from pydantic import BaseModel, ConfigDict

from copilot.answer import Citation, when
from copilot.tools import RetrievedMessage

# The one place a model's output is checked against what retrieval actually
# returned. Prose figures cannot be verified this way — a model can misquote a
# number it was correctly given, and nothing here catches that. Citations can,
# because a citation is a claim about a specific stored record, and the record
# either came back from a query this run or it did not.


class CitationCheck(BaseModel):
    """What survived validation, and what did not."""

    model_config = ConfigDict(frozen=True)

    citations: list[Citation]
    dropped: list[str]
    """Message ids the answer cited that retrieval never returned.

    Non-empty means the answer referred to evidence that does not exist in this
    run — the run is degraded even though it completed, and the console says so
    rather than showing a citation that would 404 on click."""

    @property
    def is_clean(self) -> bool:
        """Whether every cited id was real."""
        return not self.dropped


def validate(
    cited_ids: list[str], retrieved: list[RetrievedMessage], member_name: str
) -> CitationCheck:
    """Keep only citations pointing at messages this run retrieved.

    The allowlist is what came back from the graph, not what exists in it: an
    answer may only cite evidence it was actually shown. A model naming a real
    message it never saw is still asserting a source it does not have, and the
    console renders citations as clickable proof.

    Args:
        cited_ids: Message ids the answer claims as evidence, in its order.
        retrieved: Every message this run's tools returned.
        member_name: Used for the citation's display name, first name only —
            "Jordan · 30 May", the form the console prints.

    Returns:
        The surviving citations, and the ids that were dropped.
    """
    by_id = {message.id: message for message in retrieved}
    first_name = member_name.split()[0] if member_name else "Member"

    citations: list[Citation] = []
    dropped: list[str] = []
    seen: set[str] = set()

    for message_id in cited_ids:
        message = by_id.get(message_id)
        if message is None:
            dropped.append(message_id)
            continue
        if message_id in seen:
            # A repeat is not a fabrication; it just renders twice.
            continue
        seen.add(message_id)
        citations.append(
            Citation(
                message_id=message.id,
                author=first_name if message.author == "member" else "You",
                when=when(message.ts),
                text=message.text,
            )
        )

    return CitationCheck(citations=citations, dropped=dropped)


def describe(check: CitationCheck) -> str | None:
    """A one-line reason for the degraded banner, or None when clean.

    Named plainly rather than softened: an invented citation is the failure
    mode this system exists to make visible, so the console says what happened.
    """
    if check.is_clean:
        return None
    count = len(check.dropped)
    return (
        f"{count} citation{'s' if count > 1 else ''} referred to a message this "
        f"answer never retrieved, and {'were' if count > 1 else 'was'} removed."
    )
