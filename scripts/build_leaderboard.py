#!/usr/bin/env python3
"""Build the static leaderboard data artifact."""

from __future__ import annotations

import json

from leaderboard_common import ROOT
from leaderboard_common import build_leaderboard_payload

OUT_DIR = ROOT / "outputs" / "leaderboard"
OUT_PATH = OUT_DIR / "leaderboard_data.json"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = build_leaderboard_payload()
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUT_PATH.relative_to(ROOT)}")
    print(
        "Models: "
        f"{len(payload['model_rankings'])}; "
        f"games: {payload['source']['game_count']}; "
        f"player samples: {payload['source']['player_samples']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
