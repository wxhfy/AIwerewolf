from backend.agent_harness.response import content_text
from backend.agent_harness.response import tool_arguments
from backend.agent_harness.response import tool_calls


def test_content_text_accepts_provider_content_blocks() -> None:
    response = {
        "choices": [
            {
                "message": {
                    "content": [
                        {"type": "text", "text": "{\"option_id\":"},
                        {"type": "text", "text": "\"vote:P2\"}"},
                    ]
                }
            }
        ]
    }
    assert content_text(response) == '{"option_id":"vote:P2"}'


def test_tool_arguments_accepts_already_parsed_objects() -> None:
    response = {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {"function": {"name": "submit_action", "arguments": {"option_id": "vote:P2"}}}
                    ]
                }
            }
        ]
    }
    calls = tool_calls(response)
    assert tool_arguments(calls[0]) == '{"option_id": "vote:P2"}'
