#!/usr/bin/env python3
"""Probe configured real LLM providers without logging secrets."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _redact(text: str) -> str:
    redacted = re.sub(r"(api[-_]?key|token|authorization|x-api-key)(['\":=\s]+)[^,\s}]+", r"\1\2***", text, flags=re.I)
    redacted = re.sub(r"(Bearer\s+)[A-Za-z0-9._\-]+", r"\1***", redacted)
    redacted = re.sub(r"(postgres(?:ql)?(?:\+\w+)?://[^:\s/@]+):([^@\s]+)@", r"\1:***@", redacted)
    return redacted[:500]


def _extract_content(response: dict[str, Any]) -> str:
    choices = response.get("choices") or []
    if choices:
        message = choices[0].get("message") or {}
        return str(message.get("content") or "")
    content = response.get("content")
    if isinstance(content, str):
        return content
    return json.dumps(response, ensure_ascii=False)[:1000]


def probe_provider(provider: str | None) -> dict[str, Any]:
    from backend.llm import create_client

    started = time.perf_counter()
    label = provider or "env_default"
    try:
        client = create_client(provider=provider, timeout=20, max_retries=0)
        base_url = str(getattr(client, "base_url", "") or "")
        result: dict[str, Any] = {
            "provider_requested": label,
            "provider": getattr(client, "provider", provider or "unknown"),
            "available": bool(getattr(client, "available", True)),
            "model": getattr(client, "model", ""),
            "base_url_host_hint": urlparse(base_url).netloc or base_url.split("/")[0],
            "latency_seconds": None,
            "content_preview": "",
            "ok": False,
        }
        if not result["available"]:
            result["error_hint"] = "client unavailable, likely missing API key"
            return result
        response = client.chat_sync(
            [
                {"role": "system", "content": "Return only the marker requested by the user."},
                {"role": "user", "content": "Reply exactly: AIWEREWOLF_REAL_LLM_OK"},
            ],
            max_tokens=32,
            temperature=0,
            thinking=False,
        )
        content = _extract_content(response)
        result["latency_seconds"] = round(time.perf_counter() - started, 3)
        result["content_preview"] = content[:160]
        result["ok"] = "AIWEREWOLF_REAL_LLM_OK" in content
        if not result["ok"]:
            result["error_hint"] = "marker missing from response"
        return result
    except Exception as exc:
        return {
            "provider_requested": label,
            "available": False,
            "ok": False,
            "latency_seconds": round(time.perf_counter() - started, 3),
            "error_type": type(exc).__name__,
            "error_hint": _redact(str(exc).splitlines()[0] if str(exc) else repr(exc)),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--providers", default="anthropic,doubao", help="Comma-separated provider list; use env_default for env."
    )
    parser.add_argument("--output", default=str(ROOT / "docs/experiments/full_project_real_audit/real_llm_probe.json"))
    args = parser.parse_args()

    providers: list[str | None] = []
    for item in args.providers.split(","):
        value = item.strip()
        if not value:
            continue
        providers.append(None if value == "env_default" else value)
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "probes": [probe_provider(provider) for provider in providers],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if any(item.get("ok") for item in payload["probes"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
