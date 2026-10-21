import json

from cairnkit import ModelResponse, ToolCall


def call(name: str, args: dict | str, call_id: str = "c1") -> ModelResponse:
    arguments = args if isinstance(args, str) else json.dumps(args)
    return ModelResponse(content=None, tool_calls=[ToolCall(call_id, name, arguments)])


def say(text: str) -> ModelResponse:
    return ModelResponse(content=text)
