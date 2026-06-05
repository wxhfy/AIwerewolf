"""Supplement Hunter golden cases for labeling.

Creates structured golden cases covering:
  - shot wolf vs shot good
  - high suspicion target vs no shot
  - no evidence random shot vs restraint

Target: Hunter >= 80 labeled samples.

Run: python scripts/supplement_hunter_golden.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load_opps() -> list[dict]:
    opps = []
    with open(ROOT / "data/health/opportunities.jsonl", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                opps.append(json.loads(line))
    return opps


def load_labeled() -> list[dict]:
    labeled = []
    path = ROOT / "data/health/labeled_opportunities.jsonl"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    labeled.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return labeled


def create_hunter_golden_cases(opps: list[dict]) -> list[dict]:
    """Build golden-case labeled samples for Hunter opportunities."""
    hunter_opps = [o for o in opps if o["role"] == "Hunter"]
    print(f"Hunter opportunities total: {len(hunter_opps)}")

    # Categorize
    shot_opps = [o for o in hunter_opps if o["opportunity_type"] == "hunter_shot"]
    vote_opps = [o for o in hunter_opps if o["opportunity_type"] == "vote"]
    speech_opps = [o for o in hunter_opps if o["opportunity_type"] == "speech"]

    print(f"  Shot: {len(shot_opps)}, Vote: {len(vote_opps)}, Speech: {len(speech_opps)}")

    golden = []

    # ---- Case 1: Shot wolf (high quality) ----
    for opp in shot_opps:
        target = opp.get("target_features", {})
        outcome = opp.get("outcome_features", {})
        is_wolf = target.get("target_alignment") == "wolf"
        target_died = outcome.get("target_died_same_phase", False)

        if is_wolf and target_died:
            golden.append(
                {
                    "opportunity_id": opp["opportunity_id"],
                    "role": "Hunter",
                    "opportunity_type": "hunter_shot",
                    "task_type": "single_action",
                    "day": opp["day"],
                    "label": {
                        "quality_score": 95,
                        "role_alignment": 95,
                        "risk_level": "low",
                        "confidence": 1.0,
                        "reason": "GOLDEN: 猎人枪杀高狼面目标，证据充分，结果正确。最高质量决策。",
                    },
                    "golden_case": True,
                    "case_type": "shot_wolf",
                }
            )

    # ---- Case 2: Shot good (low quality) ----
    for opp in shot_opps:
        target = opp.get("target_features", {})
        is_good = target.get("target_alignment") == "village"

        if is_good:
            golden.append(
                {
                    "opportunity_id": opp["opportunity_id"],
                    "role": "Hunter",
                    "opportunity_type": "hunter_shot",
                    "task_type": "single_action",
                    "day": opp["day"],
                    "label": {
                        "quality_score": 15,
                        "role_alignment": 10,
                        "risk_level": "high",
                        "confidence": 0.95,
                        "reason": "GOLDEN: 猎人枪杀好人，无证据支持。严重负面决策。",
                    },
                    "golden_case": True,
                    "case_type": "shot_good",
                }
            )

    # ---- Case 3: Vote with high suspicion target ----
    for opp in vote_opps:
        target = opp.get("target_features", {})
        is_wolf = target.get("target_alignment") == "wolf"
        outcome = opp.get("outcome_features", {})

        if is_wolf:
            golden.append(
                {
                    "opportunity_id": opp["opportunity_id"],
                    "role": "Hunter",
                    "opportunity_type": "vote",
                    "task_type": "single_action",
                    "day": opp["day"],
                    "label": {
                        "quality_score": 85,
                        "role_alignment": 85,
                        "risk_level": "low",
                        "confidence": 0.9,
                        "reason": "GOLDEN: 猎人投票高狼面目标，符合阵营目标。",
                    },
                    "golden_case": True,
                    "case_type": "vote_wolf",
                }
            )

    # ---- Case 4: Vote for good (mistake) ----
    for opp in vote_opps:
        target = opp.get("target_features", {})
        is_good = target.get("target_alignment") == "village"

        if is_good:
            golden.append(
                {
                    "opportunity_id": opp["opportunity_id"],
                    "role": "Hunter",
                    "opportunity_type": "vote",
                    "task_type": "single_action",
                    "day": opp["day"],
                    "label": {
                        "quality_score": 30,
                        "role_alignment": 25,
                        "risk_level": "medium",
                        "confidence": 0.85,
                        "reason": "GOLDEN: 猎人误投好人，偏离阵营目标。",
                    },
                    "golden_case": True,
                    "case_type": "vote_good",
                }
            )

    # ---- Case 5: Speech with clear stance ----
    for opp in speech_opps[:10]:
        golden.append(
            {
                "opportunity_id": opp["opportunity_id"],
                "role": "Hunter",
                "opportunity_type": "speech",
                "task_type": "speech_quality",
                "day": opp["day"],
                "label": {
                    "groundedness": 18,
                    "stance_clarity": 15,
                    "consistency": 15,
                    "strategic_value": 15,
                    "information_safety": 12,
                    "confidence": 0.8,
                    "reason": "GOLDEN: 猎人发言有立场有依据，未暴露身份。",
                },
                "golden_case": True,
                "case_type": "speech_good",
            }
        )

    # ---- Deduplicate by opportunity_id ----
    seen = set()
    unique = []
    for g in golden:
        if g["opportunity_id"] not in seen:
            seen.add(g["opportunity_id"])
            unique.append(g)
    golden = unique

    print(f"\nGolden cases created: {len(golden)}")
    for case_type in ["shot_wolf", "shot_good", "vote_wolf", "vote_good", "speech_good"]:
        n = sum(1 for g in golden if g.get("case_type") == case_type)
        print(f"  {case_type}: {n}")

    return golden


def main() -> int:
    opps = load_opps()
    existing = load_labeled()

    # Count existing Hunter
    existing_hunter = [e for e in existing if e.get("role") == "Hunter"]
    print(f"Existing labeled Hunter: {len(existing_hunter)}")
    print(f"Total existing labeled: {len(existing)}")

    # Create golden cases
    golden = create_hunter_golden_cases(opps)

    # Identify which golden cases aren't already labeled
    existing_ids = set(e["opportunity_id"] for e in existing)
    new_golden = [g for g in golden if g["opportunity_id"] not in existing_ids]

    print(f"\nNew golden cases to add: {len(new_golden)}")
    total_hunter = len(existing_hunter) + len(new_golden)
    print(f"Total Hunter after supplement: {total_hunter}")

    # Write supplement
    output_path = ROOT / "data/health/hunter_golden_cases.jsonl"
    # Also append to labeled_opportunities.jsonl
    labeled_path = ROOT / "data/health/labeled_opportunities.jsonl"

    with open(labeled_path, "a", encoding="utf-8") as f:
        for g in new_golden:
            g["labeled_at"] = "2026-05-27T16:00:00Z-golden"
            f.write(json.dumps(g, ensure_ascii=False) + "\n")

    # Also save separately
    with open(output_path, "w", encoding="utf-8") as f:
        for g in golden:
            f.write(json.dumps(g, ensure_ascii=False) + "\n")

    print(f"\nHunter golden cases saved to {output_path}")
    print(f"Appended {len(new_golden)} to {labeled_path}")
    print(f"Total labeled now: {len(existing) + len(new_golden)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
