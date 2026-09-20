from __future__ import annotations

from typing import Any

from backend.agent_harness.contracts import ActionSelection
from backend.agent_harness.contracts import DecisionRequest
from backend.agent_harness.contracts import ResolvedAction


class ActionValidationError(ValueError):
    pass


def resolve_action(request: DecisionRequest, selection: ActionSelection) -> ResolvedAction:
    option = next(
        (candidate for candidate in request.action_space.options if candidate.option_id == selection.option_id),
        None,
    )
    if option is None:
        raise ActionValidationError(f"Illegal action option: {selection.option_id}")
    _validate_response(selection.response, option.response_schema)
    return ResolvedAction(
        option_id=option.option_id,
        action_type=option.action_type,
        parameters=dict(option.parameters),
        response=dict(selection.response),
        reasoning=selection.reasoning,
        metadata=dict(selection.metadata),
    )


def _validate_response(response: dict[str, Any], schema: dict[str, Any] | None) -> None:
    if schema is None:
        if response:
            raise ActionValidationError("Selected action does not accept a response payload")
        return
    if schema.get("type", "object") != "object":
        raise ActionValidationError("Only object response schemas are supported")

    properties = schema.get("properties", {})
    required = schema.get("required", [])
    missing = [name for name in required if name not in response]
    if missing:
        raise ActionValidationError(f"Missing response fields: {', '.join(sorted(missing))}")
    if schema.get("additionalProperties") is False:
        unknown = sorted(set(response) - set(properties))
        if unknown:
            raise ActionValidationError(f"Unknown response fields: {', '.join(unknown)}")

    for name, value in response.items():
        property_schema = properties.get(name)
        if property_schema is None:
            continue
        expected_type = property_schema.get("type")
        if expected_type and not _matches_type(value, expected_type):
            raise ActionValidationError(f"Response field {name!r} must be {expected_type}")
        if isinstance(value, str):
            min_length = property_schema.get("minLength")
            max_length = property_schema.get("maxLength")
            if min_length is not None and len(value) < int(min_length):
                raise ActionValidationError(f"Response field {name!r} is too short")
            if max_length is not None and len(value) > int(max_length):
                raise ActionValidationError(f"Response field {name!r} is too long")


def _matches_type(value: Any, expected_type: str) -> bool:
    type_map = {
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
        "null": lambda item: item is None,
    }
    validator = type_map.get(expected_type)
    if validator is None:
        raise ActionValidationError(f"Unsupported response schema type: {expected_type}")
    return validator(value)
