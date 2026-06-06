#!/usr/bin/env python3
"""Validate human pairwise label files against the schema."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.eval.human_label_validator import validate_human_pairwise_labels


def main():
    parser = argparse.ArgumentParser(description="Validate human pairwise labels")
    parser.add_argument("--input", required=True, help="JSONL file of labels")
    parser.add_argument("--output", default="data/health/human_pairwise_validation_result.json")
    args = parser.parse_args()

    inp = Path(args.input)
    if not inp.exists():
        print(f"Input file not found: {inp}")
        return 1

    labels = []
    with open(inp) as f:
        for line in f:
            if line.strip():
                try:
                    labels.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    result = validate_human_pairwise_labels(labels)
    result["label_distribution"] = dict(Counter(l.get("label", "UNLABELED") for l in labels))

    print(f"Total: {result['total']}, Valid: {result['valid']}, Invalid: {result['invalid']}")
    print(f"Label distribution: {result['label_distribution']}")
    if result["invalid"]:
        for lid, errs in list(result["errors_by_label"].items())[:5]:
            print(f"  {lid}: {errs}")

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"Result -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
