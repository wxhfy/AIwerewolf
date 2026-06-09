#!/usr/bin/env python3
"""Preflight check for real LLM experiment providers.

The check records model resolution and client availability without exposing
API keys. It does not run a chat completion by default.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_OUTPUT = ROOT / "docs" / "evidence" / "PROJECT_PROVIDER_PREFLIGHT.json"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def redact(value: str) -> str:
    value = re.sub(r"ep-\d{14}-[A-Za-z0-9_-]+", "ep-<redacted>", value)
    value = re.sub(r"ark-[A-Za-z0-9][A-Za-z0-9-]{20,}", "ark-<redacted>", value)
    value = re.sub(r"(sk-[A-Za-z0-9_-]{8})[A-Za-z0-9_-]+", r"\1***", value)
    value = re.sub(r"([A-Za-z0-9_]*KEY=)[^\s,;]+", r"\1***", value)
    value = re.sub(r"([A-Za-z0-9_]*TOKEN=)[^\s,;]+", r"\1***", value)
    value = re.sub(r"(Bearer\s+)[A-Za-z0-9._-]+", r"\1***", value, flags=re.IGNORECASE)
    value = re.sub(r"(postgres(?:ql)?(?:\+\w+)?://[^:\s/@]+):([^@\s]+)@", r"\1:***@", value)
    return value[:500]


def build_preflight(
    raw_models: str = "",
    *,
    allow_fake: bool = False,
    skip_client_check: bool = False,
    run_chat_check: bool = False,
) -> dict[str, Any]:
    from backend.llm.env import load_env_file
    from scripts.track_bc_leaderboard_experiment import resolve_model_specs
    from scripts.track_bc_leaderboard_experiment import validate_model_specs

    load_env_file()
    result: dict[str, Any] = {
        "checked_at": now_iso(),
        "status": "unknown",
        "allow_fake": allow_fake,
        "skip_client_check": skip_client_check,
        "run_chat_check": run_chat_check,
        "raw_models_provided": bool(raw_models.strip()),
        "resolved_models": [],
        "client_checks": [],
        "chat_checks": [],
        "error": None,
        "safe_for_formal_experiment": False,
    }

    try:
        specs = resolve_model_specs(raw_models)
        result["resolved_models"] = [
            {"provider": spec.provider, "model": redact(spec.model), "label": redact(spec.label)} for spec in specs
        ]
        validate_model_specs(specs, allow_fake=allow_fake, skip_client_check=skip_client_check)

        from backend.llm import create_client

        for spec in specs:
            client = create_client(provider=spec.provider, model=spec.model)
            available = getattr(client, "available", True) is not False
            fake = spec.provider in {"fake", "fake_llm", "offline_llm"} or "fake" in spec.model.lower()
            client_row = {
                "label": redact(spec.label),
                "provider": spec.provider,
                "model": redact(spec.model),
                "available": available,
                "fake": fake,
                "client_class": type(client).__name__,
                "base_url_present": bool(str(getattr(client, "base_url", "") or "").strip()),
            }
            result["client_checks"].append(client_row)
            if run_chat_check and available and not fake:
                started = time.perf_counter()
                try:
                    response = client.chat_sync(
                        [{"role": "user", "content": "请只回复 OK"}],
                        temperature=0,
                        max_tokens=8,
                    )
                    elapsed_s = round(time.perf_counter() - started, 3)
                    response_text = ""
                    if isinstance(response, dict):
                        choices = response.get("choices") or []
                        if choices:
                            message = choices[0].get("message") or {}
                            response_text = str(message.get("content") or "")
                    else:
                        response_text = str(response)
                    result["chat_checks"].append(
                        {
                            "label": redact(spec.label),
                            "ok": bool(response_text.strip()),
                            "elapsed_s": elapsed_s,
                            "response_preview": redact(response_text.strip())[:80],
                        }
                    )
                except Exception as chat_exc:
                    result["chat_checks"].append(
                        {
                            "label": redact(spec.label),
                            "ok": False,
                            "elapsed_s": round(time.perf_counter() - started, 3),
                            "error": f"{type(chat_exc).__name__}: {redact(str(chat_exc))}",
                        }
                    )
        has_fake = any(row.get("fake") for row in result["client_checks"])
        all_available = all(row.get("available") for row in result["client_checks"])
        chat_ok = (not run_chat_check) or all(row.get("ok") for row in result["chat_checks"])
        result["safe_for_formal_experiment"] = bool(
            all_available and chat_ok and not has_fake and not skip_client_check
        )
        result["status"] = "ok" if result["safe_for_formal_experiment"] else "unsafe"
        if skip_client_check:
            result["error"] = "skip_client_check=true; not safe as formal preflight evidence"
        elif has_fake and not allow_fake:
            result["error"] = "fake/offline provider resolved while allow_fake=false"
        elif not all_available:
            result["error"] = "one or more resolved clients are unavailable"
        elif run_chat_check and not chat_ok:
            result["error"] = "one or more resolved clients failed a minimal chat check"
    except Exception as exc:
        result["status"] = "failed"
        result["error"] = f"{type(exc).__name__}: {redact(str(exc))}"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", default="", help="Explicit provider:model pool")
    parser.add_argument("--allow-fake", action="store_true", help="Allow fake provider only for smoke checks")
    parser.add_argument("--skip-client-check", action="store_true", help="Resolve models without validating client")
    parser.add_argument("--run-chat-check", action="store_true", help="Run one minimal real chat request per model")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    result = build_preflight(
        args.models,
        allow_fake=args.allow_fake,
        skip_client_check=args.skip_client_check,
        run_chat_check=args.run_chat_check,
    )
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {display_path(output)}")
    print(f"status={result['status']} safe_for_formal_experiment={result['safe_for_formal_experiment']}")
    if result.get("error"):
        print(f"error={result['error']}")
    return 0 if result["status"] in {"ok", "unsafe", "failed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
