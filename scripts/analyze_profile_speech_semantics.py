#!/usr/bin/env python3
"""Profile-level speech semantic aggregation for MBTI/Profile experiments.

Takes Track B speech samples (or audit examples) and aggregates
speech act / audit feature distributions per player profile.

Usage:
  python scripts/analyze_profile_speech_semantics.py --input data/open/combined/speech_semantic_audit_examples.jsonl
  python scripts/analyze_profile_speech_semantics.py --input data/open/combined/track_b_open_speech_samples.jsonl --profile-field role
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.eval.heads.speech_semantic import SpeechSemanticScorer, AUDIT_FEATURE_MAP

AUDIT_FEATURES = list(AUDIT_FEATURE_MAP.values())
SPEECH_ACTS = ["accusation", "interrogation", "defense",
               "evidence_use", "identity_declaration", "call_for_action"]


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    items = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    items.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return items


def _top_speech_pattern(features: dict[str, float]) -> str:
    """Identify the dominant speech pattern from audit features."""
    if not features:
        return "unknown"
    return max(features, key=features.get)


def analyze_profiles(
    samples: list[dict],
    profile_field: str = "role",
    scorer: SpeechSemanticScorer | None = None,
) -> list[dict]:
    """Aggregate speech semantic features per profile (player_id or role)."""
    if scorer is None:
        scorer = SpeechSemanticScorer()

    # Check if samples already have audit features
    has_audit = any("audit_features" in s and s.get("audit_features") for s in samples[:5])

    by_profile: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))

    for s in samples:
        profile_id = s.get(profile_field, s.get("player_id", "unknown"))

        if has_audit:
            features = s.get("audit_features", {})
            probs = s.get("speech_act_probs", {})
        else:
            utterance = s.get("utterance", "")
            result = scorer.score(utterance)
            features = result.audit_features
            probs = result.speech_act_probs

        for feat, val in features.items():
            if val is not None:
                by_profile[profile_id][feat].append(float(val))

        for act, val in probs.items():
            if val is not None:
                key = f"act_{act}"
                by_profile[profile_id][key].append(float(val))

    results: list[dict] = []
    for profile_id, feat_vals in sorted(by_profile.items()):
        n_samples = len(next(iter(feat_vals.values()))) if feat_vals else 0
        if n_samples == 0:
            continue

        avg_features = {}
        for feat in AUDIT_FEATURES:
            vals = feat_vals.get(feat, [])
            avg_features[feat] = round(float(np.mean(vals)), 4) if vals else 0.0

        avg_acts = {}
        for act in SPEECH_ACTS:
            vals = feat_vals.get(f"act_{act}", [])
            avg_acts[act] = round(float(np.mean(vals)), 4) if vals else 0.0

        top_pattern = _top_speech_pattern(avg_features)

        results.append({
            "profile_id": str(profile_id),
            "profile_field": profile_field,
            "samples": n_samples,
            "avg_evidence_grounding_signal": avg_features.get("evidence_grounding_signal", 0),
            "avg_actionability_signal": avg_features.get("actionability_signal", 0),
            "avg_identity_claim_signal": avg_features.get("identity_claim_signal", 0),
            "avg_pressure_signal": avg_features.get("pressure_signal", 0),
            "avg_information_seeking_signal": avg_features.get("information_seeking_signal", 0),
            "avg_defensive_posture_signal": avg_features.get("defensive_posture_signal", 0),
            "avg_speech_act_probs": avg_acts,
            "top_speech_pattern": top_pattern,
            "audit_only": True,
            "source_model": "speech_act_classifier_v0",
        })

    return results


def main():
    parser = argparse.ArgumentParser(description="Profile-level speech semantic analysis")
    parser.add_argument("--input", required=True, help="Input speech samples or audit examples JSONL")
    parser.add_argument("--output", help="Output profile analysis JSONL")
    parser.add_argument("--profile-field", default="role",
                       help="Field to group by (role, player_id, source)")
    parser.add_argument("--limit", type=int, default=0, help="Limit samples")
    args = parser.parse_args()

    print("=" * 60)
    print("Profile Speech Semantic Analyzer")
    print("=" * 60)

    samples = _load_jsonl(Path(args.input))
    if args.limit > 0:
        samples = samples[:args.limit]
    print(f"  Loaded {len(samples)} samples")
    print(f"  Profile field: {args.profile_field}")

    scorer = SpeechSemanticScorer()
    print(f"  Scorer model available: {scorer.model_available}")

    results = analyze_profiles(samples, args.profile_field, scorer)
    print(f"  Profiles: {len(results)}")

    # Print summary
    print(f"\n{'Profile':<20} {'Samples':>8} {'Evidence':>8} {'Action':>8} "
          f"{'Identity':>8} {'Pressure':>8} {'InfoSeek':>8} {'Defense':>8} {'TopPattern':<25}")
    print("-" * 120)
    for r in sorted(results, key=lambda x: -x["samples"]):
        print(f"{r['profile_id']:<20} {r['samples']:>8} "
              f"{r['avg_evidence_grounding_signal']:>8.3f} "
              f"{r['avg_actionability_signal']:>8.3f} "
              f"{r['avg_identity_claim_signal']:>8.3f} "
              f"{r['avg_pressure_signal']:>8.3f} "
              f"{r['avg_information_seeking_signal']:>8.3f} "
              f"{r['avg_defensive_posture_signal']:>8.3f} "
              f"{r['top_speech_pattern']:<25}")

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            for r in results:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"\n  Written: {out_path}")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
