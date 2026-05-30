#!/usr/bin/env python3
"""Generate speech semantic audit examples for Track B reports.

Reads combined speech samples, runs SpeechSemanticScorer on each,
and outputs structured audit examples with probabilities and features.

Usage:
  python scripts/generate_speech_semantic_audit_examples.py
  python scripts/generate_speech_semantic_audit_examples.py --limit 500
  python scripts/generate_speech_semantic_audit_examples.py --input data/open/track_b_native/track_b_real_speech_samples.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.eval.heads.speech_semantic import SpeechSemanticScorer

COMBINED_DIR = ROOT / "data" / "open" / "combined"
DEFAULT_INPUT = COMBINED_DIR / "track_b_open_speech_samples.jsonl"
DEFAULT_OUTPUT = COMBINED_DIR / "speech_semantic_audit_examples.jsonl"


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


def _save_jsonl(items: list[dict], path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def generate_examples(
    samples: list[dict],
    scorer: SpeechSemanticScorer,
    limit: int = 0,
) -> list[dict]:
    """Run SpeechSemanticScorer on each sample and attach audit features."""
    results: list[dict] = []
    samples_to_process = samples[:limit] if limit > 0 else samples

    for s in samples_to_process:
        utterance = s.get("utterance", "")
        result = scorer.score(utterance)

        audit_entry = {
            "sample_id": s.get("sample_id", ""),
            "source": s.get("source", ""),
            "game_id": s.get("game_id", ""),
            "role": s.get("role", "Unknown"),
            "utterance": utterance[:500],
            "speech_act_probs": result.speech_act_probs,
            "audit_features": result.audit_features,
            "audit_only": result.audit_only,
            "source_model": result.source_model,
            "model_available": result.model_available,
        }
        results.append(audit_entry)

    return results


def main():
    parser = argparse.ArgumentParser(description="Generate speech semantic audit examples")
    parser.add_argument("--input", default=str(DEFAULT_INPUT),
                       help="Input speech samples JSONL")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT),
                       help="Output audit examples JSONL")
    parser.add_argument("--limit", type=int, default=0,
                       help="Limit number of samples to process")
    parser.add_argument("--top-n", type=int, default=10,
                       help="Show top-N representative examples for each label")
    args = parser.parse_args()

    print("=" * 60)
    print("Speech Semantic Audit Example Generator")
    print("=" * 60)

    # Load scorer
    print("\nLoading SpeechSemanticScorer...")
    scorer = SpeechSemanticScorer()
    print(f"  Model available: {scorer.model_available}")

    # Load samples
    input_path = Path(args.input)
    samples = _load_jsonl(input_path)
    print(f"  Loaded {len(samples)} samples")

    if args.limit > 0:
        samples = samples[:args.limit]

    # Generate
    print(f"\nGenerating audit examples for {len(samples)} samples...")
    results = generate_examples(samples, scorer, limit=args.limit)

    # Save
    output_path = Path(args.output)
    _save_jsonl(results, output_path)
    print(f"  Written: {output_path} ({len(results)} examples)")

    # Summary stats
    if results:
        # Aggregate by role
        role_features: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        for r in results:
            role = r["role"]
            for feat, val in r["audit_features"].items():
                role_features[role][feat].append(val)

        print("\n--- Per-Role Speech Pattern Summary ---")
        for role in sorted(role_features):
            feats = role_features[role]
            n = len(next(iter(feats.values())))
            print(f"\n  {role} (n={n}):")
            for feat, vals in sorted(feats.items()):
                avg = sum(vals) / len(vals) if vals else 0
                bar = "█" * int(avg * 20)
                print(f"    {feat:30s}: {avg:.3f} {bar}")

        # Top-N examples per label
        print(f"\n--- Top-{args.top_n} Examples Per Speech Act ---")
        speech_acts = ["accusation", "interrogation", "defense",
                       "evidence_use", "identity_declaration", "call_for_action"]
        for act in speech_acts:
            # Sort by probability of this act
            ranked = sorted(results, key=lambda r: r["speech_act_probs"].get(act, 0), reverse=True)
            top = ranked[:args.top_n]
            if top and top[0]["speech_act_probs"].get(act, 0) > 0.01:
                print(f"\n  [{act}]")
                for item in top[:3]:
                    prob = item["speech_act_probs"].get(act, 0)
                    print(f"    prob={prob:.2f} role={item['role']}: {item['utterance'][:100]}")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
