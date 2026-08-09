import json
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from agent.prompts import EXTRACTION_SYSTEM
from agent.schemas import ExtractionResult
from settings import settings

# Extraction output is a handful of short strings. The ceiling exists to stop a
# runaway, not to shape the answer.
MAX_TOKENS = 1024


class ExtractionCase(BaseModel):
    """One labelled utterance: fixture, offline fake and eval set at once.

    The same file plays all three roles, exactly as `resolver_cases.json` does
    for the resolver, so the stand-in and the assertions cannot drift apart.
    """

    model_config = ConfigDict(frozen=True)

    prompt: str
    instructions: list[dict] = []
    emphasis: list[str] = []
    unmapped: list[str] = []
    note: str

    @property
    def expected(self) -> ExtractionResult:
        """What extraction should produce for this utterance."""
        return ExtractionResult.model_validate(
            {
                "instructions": self.instructions,
                "emphasis": self.emphasis,
                "unmapped": self.unmapped,
            }
        )


def load_cases(path: Path | None = None) -> list[ExtractionCase]:
    """Read the labelled extraction cases.

    Args:
        path: Location of `extraction_cases.json`. Defaults to the configured
            data directory.

    Returns:
        Every case, validated.

    Raises:
        FileNotFoundError: If the file is missing.
        pydantic.ValidationError: If a case is malformed.
    """
    source = path or settings.extraction_cases_path
    return [ExtractionCase.model_validate(row) for row in json.loads(source.read_text())]


class Extractor(Protocol):
    """Turns one coach utterance into structured instructions."""

    def extract(self, prompt: str) -> ExtractionResult:
        """Read what the coach asked for.

        Args:
            prompt: The coach's own words.

        Returns:
            The instructions, emphasis and anything unmapped.
        """
        ...


class ScriptedExtractor:
    """Replays the labelled cases, with no model involved.

    Not a mock in the usual sense: it answers from the same file the tests
    assert against and the live extractor is measured on. A prompt it does not
    know returns nothing mapped rather than raising, which is the honest
    behaviour for an extractor that did not understand — and keeps the no-key
    path a working system rather than a broken one.
    """

    def __init__(self, cases: list[ExtractionCase] | None = None) -> None:
        self.by_prompt = {
            case.prompt.strip().lower(): case.expected for case in (cases or load_cases())
        }

    def extract(self, prompt: str) -> ExtractionResult:
        """Look the utterance up, or report it unmapped."""
        known = self.by_prompt.get(prompt.strip().lower())
        if known is not None:
            return known
        return ExtractionResult(unmapped=[prompt] if prompt.strip() else [])


class AnthropicExtractor:
    """Extraction by one structured-output call.

    One call, no loop, no tools. The model never sees the catalogue and never
    reaches the graph — `filter.run` takes a `Composition`, so there is no
    type-checked path from anything here to a traversal. That is why this is
    the only module in the backend that imports `anthropic`.
    """

    def __init__(self, client, model: str | None = None) -> None:  # noqa: ANN001
        self.client = client
        self.model = model or settings.anthropic_model

    def extract(self, prompt: str) -> ExtractionResult:
        """Ask the model what the coach asked for.

        Thinking is disabled and effort is low: this is transcription into a
        schema, not a judgement, and the whole latency budget for a plan is
        one of these calls.

        Args:
            prompt: The coach's own words.

        Returns:
            The parsed result, schema-guaranteed by the SDK.
        """
        message = self.client.messages.parse(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=EXTRACTION_SYSTEM,
            output_format=ExtractionResult,
            output_config={"effort": "low"},
            thinking={"type": "disabled"},
            messages=[{"role": "user", "content": prompt}],
        )
        return message.parsed_output
