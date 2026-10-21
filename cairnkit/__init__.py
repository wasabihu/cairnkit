"""cairnkit: a small agent runtime for business applications.

Design and several algorithms are ported from Hermes Agent v0.22.2 (MIT, Nous Research);
see NOTICE.md. Public API:
"""

from cairnkit.agents import AgentConfigError, AgentSpec, load_agent, load_agents, validate_persona
from cairnkit.compression import (
    LATEST_MESSAGE_MARKER,
    SUMMARY_PREFIX,
    CompressionConfig,
    CompressionResult,
    CompressionState,
    ContextCompressor,
    estimate_tokens,
)
from cairnkit.curator import (
    CuratorPolicy,
    CuratorReport,
    SkillActivity,
    Suggestion,
    Transition,
    plan_transitions,
    should_run,
    suggest_consolidation,
)
from cairnkit.delegate import make_delegate_tool
from cairnkit.guardrails import GuardrailConfig
from cairnkit.llm import (
    ChatModel,
    ClassifiedError,
    FailoverReason,
    FallbackModel,
    ModelAPIError,
    OpenAICompatModel,
    ScriptedModel,
    classify_error,
    openrouter,
)
from cairnkit.loop import Agent, RunEvent, RunResult, ToolRecord
from cairnkit.memory import (
    MemoryItem,
    MemoryStore,
    make_memory_tool,
    render_snapshot,
    screen_memory_write,
)
from cairnkit.memory_ops import MemoryChange, MemoryPlan, MemoryPlanError, plan_operations
from cairnkit.pricing import Price, cost_of, estimate_cost
from cairnkit.prompt import PromptParts, build_system_prompt
from cairnkit.review import REVIEW_INSTRUCTION, review_conversation
from cairnkit.search import SearchBackend, SearchHit, SearchItem, make_search_tool
from cairnkit.security import first_threat_message, scan_for_threats
from cairnkit.skills import Skill, SkillError, SkillLibrary, make_skill
from cairnkit.titles import can_replace, derive_title, generate_title
from cairnkit.tools import (
    ToolContext,
    ToolError,
    ToolOutcome,
    ToolRegistry,
    ToolSpec,
    tool_error,
    tool_result,
)
from cairnkit.types import Message, ModelResponse, ToolCall, Usage

__all__ = [
    "Agent",
    "AgentConfigError",
    "AgentSpec",
    "build_system_prompt",
    "can_replace",
    "ChatModel",
    "ClassifiedError",
    "classify_error",
    "CompressionConfig",
    "CompressionResult",
    "CompressionState",
    "ContextCompressor",
    "CuratorPolicy",
    "CuratorReport",
    "SkillActivity",
    "Suggestion",
    "Transition",
    "plan_transitions",
    "should_run",
    "suggest_consolidation",
    "make_skill",
    "validate_persona",
    "LATEST_MESSAGE_MARKER",
    "cost_of",
    "derive_title",
    "estimate_cost",
    "estimate_tokens",
    "FailoverReason",
    "FallbackModel",
    "first_threat_message",
    "generate_title",
    "GuardrailConfig",
    "load_agent",
    "load_agents",
    "make_delegate_tool",
    "make_memory_tool",
    "make_search_tool",
    "MemoryChange",
    "MemoryItem",
    "MemoryPlan",
    "MemoryPlanError",
    "MemoryStore",
    "Message",
    "ModelAPIError",
    "ModelResponse",
    "OpenAICompatModel",
    "openrouter",
    "plan_operations",
    "Price",
    "PromptParts",
    "render_snapshot",
    "review_conversation",
    "REVIEW_INSTRUCTION",
    "RunEvent",
    "RunResult",
    "scan_for_threats",
    "screen_memory_write",
    "ScriptedModel",
    "SearchBackend",
    "SearchHit",
    "SearchItem",
    "Skill",
    "SkillError",
    "SkillLibrary",
    "SUMMARY_PREFIX",
    "tool_error",
    "tool_result",
    "ToolCall",
    "ToolContext",
    "ToolError",
    "ToolOutcome",
    "ToolRecord",
    "ToolRegistry",
    "ToolSpec",
    "Usage",
]
