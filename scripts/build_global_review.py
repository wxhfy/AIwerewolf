#!/usr/bin/env python3
"""Build the global review data artifact for leaderboard reporting."""

from __future__ import annotations

import json

from leaderboard_common import ROOT
from leaderboard_common import build_global_review_payload

OUT_DIR = ROOT / "outputs" / "leaderboard"
OUT_PATH = OUT_DIR / "global_review.json"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = build_global_review_payload()
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUT_PATH.relative_to(ROOT)}")
    print(
        "Global review: "
        f"{payload['source']['game_count']} games; "
        f"{len(payload['role_performance'])} roles; "
        f"{payload['track_c_evolution_effect']['experiment_count']} Track C experiments"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
