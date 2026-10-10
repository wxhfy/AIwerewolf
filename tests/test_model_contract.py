from __future__ import annotations

import pytest

from backend.agent_harness.model import ModelCallError
from backend.agent_harness.model import classify_model_error
from backend.agent_harness.model import complete_chat


def test_model_errors_have_provider_neutral_categories() -> None:
    assert classify_model_error(TimeoutError("ReadTimeout")) == "timeout"
    assert classify_model_error(RuntimeError("HTTP 429 throttled")) == "rate_limit"
    assert classify_model_error(RuntimeError("connection reset")) == "transport"


def test_complete_chat_wraps_provider_failure() -> None:
    class BrokenClient:
        def complete(self, messages, **kwargs):
            raise TimeoutError("upstream timeout")

    with pytest.raises(ModelCallError) as captured:
        complete_chat(BrokenClient(), [])
    assert captured.value.category == "timeout"
    assert "TimeoutError" in str(captured.value)
