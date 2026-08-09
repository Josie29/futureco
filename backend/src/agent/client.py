from agent.extract import AnthropicExtractor, Extractor, ScriptedExtractor
from settings import settings


def build_extractor() -> tuple[Extractor, bool]:
    """Choose an extractor for this process.

    The Anthropic one when a key is configured, the scripted one otherwise.
    Not a degraded mode: with no narration pass, extraction is the entire model
    surface, so a keyless process still builds the same plans — it just needs
    the instructions handed to it rather than read out of a sentence.

    Returns:
        The extractor, and whether it is the live one.
    """
    if not settings.anthropic_api_key:
        return ScriptedExtractor(), False

    from anthropic import Anthropic

    return AnthropicExtractor(Anthropic(api_key=settings.anthropic_api_key)), True
