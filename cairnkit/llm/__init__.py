from cairnkit.llm.base import ChatModel
from cairnkit.llm.errors import ClassifiedError, FailoverReason, ModelAPIError, classify_error
from cairnkit.llm.fallback import FallbackModel
from cairnkit.llm.openai_compat import OpenAICompatModel, openrouter
from cairnkit.llm.scripted import ScriptedModel

__all__ = [
    "ChatModel",
    "ClassifiedError",
    "FailoverReason",
    "FallbackModel",
    "ModelAPIError",
    "OpenAICompatModel",
    "ScriptedModel",
    "classify_error",
    "openrouter",
]
