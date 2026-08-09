import ast
from pathlib import Path

import pytest

import plan.schemas
from agent.client import build_extractor
from agent.extract import ScriptedExtractor, load_cases
from agent.prompts import EXTRACTION_SYSTEM
from agent.schemas import ExtractionResult
from safety.constraints import ConstraintKind, Op
from settings import settings


@pytest.fixture(scope="module")
def cases():
    """The labelled utterances, read once."""
    return load_cases()


@pytest.fixture(scope="module")
def scripted():
    """The offline extractor, over the same cases."""
    return ScriptedExtractor()


class TestCases:
    """The file that is fixture, offline stand-in and eval set at once."""

    def test_every_case_covers_the_specs_own_examples(self, cases) -> None:
        """The four prompts `ASSESSMENT.md` names must all be represented.

        They are what the system is graded on, so an eval set that omits them
        measures something else.
        """
        prompts = " ".join(case.prompt.lower() for case in cases)
        for phrase in ("pecs", "dumbbells", "deadlifts", "knee"):
            assert phrase in prompts

    def test_every_case_explains_itself(self, cases) -> None:
        """A labelled case with no rationale is an assertion nobody can check.

        These are judgement calls about English, not facts about the graph, so
        the reasoning is the only thing distinguishing a label from a guess.
        """
        for case in cases:
            assert len(case.note) > 40, case.prompt

    def test_no_case_expects_a_waiver(self, cases) -> None:
        """Nothing in the eval set teaches the model to try waiving an injury.

        `Instruction` has no verb for it and `compose` refuses it anyway, but a
        case that rehearsed it would be teaching a request the system exists to
        refuse.
        """
        for case in cases:
            for instruction in case.expected.instructions:
                assert instruction.kind is not ConstraintKind.INJURY, case.prompt


class TestScripted:
    """The extractor that needs no key."""

    def test_it_reproduces_every_labelled_case(self, cases, scripted) -> None:
        """The stand-in must answer exactly what the cases assert.

        It reads the same file, so this is really a guard on the loader — but
        a fake that drifted from its own fixture would make every test above
        it meaningless.
        """
        for case in cases:
            assert scripted.extract(case.prompt).result == case.expected, case.prompt

    def test_an_unknown_utterance_is_reported_not_guessed(self, scripted) -> None:
        """No key must degrade to honesty, not to a crash or a fabrication.

        Returning the sentence unmapped is what an extractor that did not
        understand should say, and it keeps the whole keyless path a working
        system rather than a broken one.
        """
        extraction = scripted.extract("something nobody has labelled")
        assert extraction.result.instructions == []
        assert extraction.result.unmapped == ["something nobody has labelled"]
        # No model ran, so the trace must not claim an LLM span for this.
        assert extraction.model is None

    def test_an_empty_prompt_maps_to_nothing(self, scripted) -> None:
        """A request with no prompt is first-class, not an error."""
        assert scripted.extract("   ").result == ExtractionResult()


class TestBoundary:
    """What extraction is structurally unable to do."""

    def test_the_result_carries_no_node_ids_or_weights(self) -> None:
        """The model's whole vocabulary is operations, kinds and phrases.

        Anything else would let it reach past extraction into decisions the
        graph is supposed to make — a severity, a score, an exercise id.
        """
        assert set(ExtractionResult.model_fields) == {
            "instructions",
            "emphasis",
            "unmapped",
        }
        assert set(type(ExtractionResult().instructions)()) == set()

    def test_there_is_no_verb_for_waiving_a_clinical_constraint(self) -> None:
        """`Op` is the model's only way to act, and none of it waives anything.

        Removal exists, but `compose` checks waivability before resolution, so
        an injury cannot be dropped however the request is phrased.
        """
        assert {op.value for op in Op} == {"replace", "add", "remove"}

    def test_the_plan_package_imports_no_model_client(self) -> None:
        """The deterministic half must not be able to call a model at all.

        This is the type boundary made checkable: `filter.run` takes a
        `Composition`, and nothing under `plan/` can reach for prose to build
        one from.
        """
        for path in Path(plan.schemas.__file__).parent.glob("*.py"):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    assert all(a.name != "anthropic" for a in node.names), path.name
                if isinstance(node, ast.ImportFrom):
                    assert node.module != "anthropic", path.name

    def test_the_system_prompt_is_stable(self) -> None:
        """Built from no f-strings, so prompt caching keys on an exact prefix.

        Interpolating a member id or a date would miss the cache on every
        request, invisibly and expensively.
        """
        assert "{" not in EXTRACTION_SYSTEM
        assert EXTRACTION_SYSTEM == EXTRACTION_SYSTEM.strip()


@pytest.mark.live
def test_the_live_extractor_agrees_with_every_labelled_case(cases) -> None:
    """What stops the offline stand-in becoming fiction.

    The scripted extractor answers from the same file these cases assert, so
    on its own it proves nothing about the model. This is the only test that
    holds the two together, and it is why the cases are labelled with reasoning
    rather than with whatever the model happened to return.
    """
    if not settings.anthropic_api_key:
        pytest.skip("no ANTHROPIC_API_KEY configured")

    extractor, live = build_extractor()
    assert live
    mismatched = [
        case.prompt for case in cases if extractor.extract(case.prompt).result != case.expected
    ]
    assert not mismatched
