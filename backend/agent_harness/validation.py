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
    _validate_schema_value(response, schema, "response", root=True)


def _validate_schema_value(value: Any, schema: dict[str, Any], path: str, *, root: bool = False) -> None:
    if not isinstance(schema, dict):
        raise ActionValidationError(f"Schema for {path!r} must be an object")

    expected_type = schema.get("type")
    if expected_type and not _matches_type(value, str(expected_type)):
        if root:
            raise ActionValidationError("Only object response schemas are supported")
        raise ActionValidationError(f"Response field {path!r} must be {expected_type}")

    if "enum" in schema and value not in schema.get("enum", []):
        allowed = ", ".join(repr(item) for item in schema.get("enum", []))
        raise ActionValidationError(f"Response field {path!r} must be one of: {allowed}")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and value < minimum:
            raise ActionValidationError(f"Response field {path!r} must be at least {minimum}")
        if maximum is not None and value > maximum:
            raise ActionValidationError(f"Response field {path!r} must be at most {maximum}")

    if isinstance(value, str):
        min_length = schema.get("minLength")
        max_length = schema.get("maxLength")
        if min_length is not None and len(value) < int(min_length):
            raise ActionValidationError(_length_error(path, "too short"))
        if max_length is not None and len(value) > int(max_length):
            raise ActionValidationError(_length_error(path, "too long"))

    if isinstance(value, list):
        min_items = schema.get("minItems")
        max_items = schema.get("maxItems")
        if min_items is not None and len(value) < int(min_items):
            raise ActionValidationError(f"Response field {path!r} must contain at least {int(min_items)} items")
        if max_items is not None and len(value) > int(max_items):
            raise ActionValidationError(f"Response field {path!r} must contain at most {int(max_items)} items")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                _validate_schema_value(item, item_schema, f"{path}[{index}]")

    if isinstance(value, dict):
        properties = schema.get("properties") or {}
        required = schema.get("required") or []
        missing = [name for name in required if name not in value]
        if missing:
            if root:
                raise ActionValidationError(f"Missing response fields: {', '.join(sorted(missing))}")
            raise ActionValidationError(f"Response field {path!r} is missing: {', '.join(sorted(missing))}")
        if schema.get("additionalProperties") is False:
            unknown = sorted(set(value) - set(properties))
            if unknown:
                if root:
                    raise ActionValidationError(f"Unknown response fields: {', '.join(unknown)}")
                raise ActionValidationError(f"Response field {path!r} has unknown fields: {', '.join(unknown)}")
        for name, item in value.items():
            child_schema = properties.get(name)
            if isinstance(child_schema, dict):
                _validate_schema_value(item, child_schema, str(name) if root else f"{path}.{name}")


def _length_error(path: str, message: str) -> str:
    return f"Response field {path!r} is {message}"


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
