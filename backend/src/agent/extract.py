import json
import time
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


class Extraction(BaseModel):
    """What one extraction produced, and what the call cost.

    Cost travels with the result rather than being read back off the extractor
    afterwards. A `last_usage` attribute would be a race the moment two coaches
    build at once — FastAPI runs sync routes in a threadpool over one shared
    extractor — and the trace would attribute one run's tokens to another.
    """

    model_config = ConfigDict(frozen=True)

    result: ExtractionResult
    model: str | None = None
    """None when no model ran: an empty prompt, or the scripted stand-in."""

    tokens_in: int = 0
    tokens_out: int = 0
    duration_ms: float = 0.0


class Extractor(Protocol):
    """Turns one coach utterance into structured instructions."""

    def extract(self, prompt: str) -> Extraction:
        """Read what the coach asked for.

        Args:
            prompt: The coach's own words.

        Returns:
            The instructions, emphasis and anything unmapped, with the cost of
            producing them.
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

    def extract(self, prompt: str) -> Extraction:
        """Look the utterance up, or report it unmapped."""
        known = self.by_prompt.get(prompt.strip().lower())
        if known is not None:
            return Extraction(result=known)
        return Extraction(result=ExtractionResult(unmapped=[prompt] if prompt.strip() else []))


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

    def extract(self, prompt: str) -> Extraction:
        """Ask the model what the coach asked for.

        Thinking is disabled and effort is low: this is transcription into a
        schema, not a judgement, and the whole latency budget for a plan is
        one of these calls.

        Args:
            prompt: The coach's own words.

        Returns:
            The parsed result, schema-guaranteed by the SDK, with the token
            counts and wall time the trace reports.
        """
        started = time.perf_counter()
        message = self.client.messages.parse(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=EXTRACTION_SYSTEM,
            output_format=ExtractionResult,
            output_config={"effort": "low"},
            thinking={"type": "disabled"},
            messages=[{"role": "user", "content": prompt}],
        )
        # Read defensively: usage is the SDK's to shape, and a trace missing a
        # token count is a worse reason to fail a coach's build than none.
        usage = getattr(message, "usage", None)
        return Extraction(
            result=message.parsed_output,
            model=self.model,
            tokens_in=getattr(usage, "input_tokens", 0) or 0,
            tokens_out=getattr(usage, "output_tokens", 0) or 0,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
