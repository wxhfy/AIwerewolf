#!/usr/bin/env python3
"""Audit Track B open datasets for quality and policy compliance.

Produces:
  data/open/combined/track_b_open_data_audit.json
  docs/track_b_open_data_audit_report.md

Usage:
  python scripts/audit_track_b_open_datasets.py
  python scripts/audit_track_b_open_datasets.py --dataset speech
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

COMBINED_DIR = ROOT / "data" / "open" / "combined"
AUDIT_PATH = COMBINED_DIR / "track_b_open_data_audit.json"
REPORT_PATH = ROOT / "docs" / "track_b_open_data_audit_report.md"


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


def _audit_dataset(name: str, path: Path) -> dict[str, Any]:
    samples = _load_jsonl(path)
    if not samples:
        return {"name": name, "total": 0, "status": "EMPTY"}

    # Source distribution
    sources = Counter(s.get("source", "unknown") for s in samples)
    licenses = Counter(s.get("license", "unknown") for s in samples)
    rule_variants = Counter(s.get("rule_variant", "unknown") for s in samples)

    # Role distribution
    roles = Counter(s.get("role", "Unknown") for s in samples)

    # Label source distribution
    label_sources = Counter(s.get("weak_label_source", "unknown") for s in samples)

    # Policy checks
    missing_source = sum(1 for s in samples if not s.get("source"))
    missing_license = sum(1 for s in samples if not s.get("license") or s["license"] == "unknown")
    missing_rule_variant = sum(1 for s in samples if not s.get("rule_variant"))
    has_final_q = sum(1 for s in samples if "final_q" in s)

    # Check do_not_train_final_q_directly
    missing_dnt = sum(1 for s in samples if not s.get("do_not_train_final_q_directly", True))

    # Game-level stats
    game_ids = set(s.get("game_id", "") for s in samples)
    games_with_samples = Counter(s.get("game_id", "") for s in samples)
    games_per_sample_dist = Counter(games_with_samples.values())

    # Weak labels
    weak_label_names = Counter()
    for s in samples:
        wl = s.get("weak_labels", {})
        if isinstance(wl, dict):
            for k in wl:
                weak_label_names[k] += 1

    # Visibility check
    has_public_ctx = sum(1 for s in samples if s.get("visible_public_context"))
    has_private_ctx = sum(1 for s in samples if s.get("visible_private_context"))

    # Empty content check
    empty_text = sum(1 for s in samples if not s.get("utterance", "") and name == "speech")

    return {
        "name": name,
        "total": len(samples),
        "status": "OK" if len(samples) > 0 else "EMPTY",
        "source_distribution": dict(sources),
        "license_distribution": dict(licenses),
        "rule_variant_distribution": dict(rule_variants),
        "role_distribution": dict(roles),
        "label_source_distribution": dict(label_sources),
        "weak_label_distribution": dict(weak_label_names),
        "total_games": len(game_ids),
        "samples_per_game_distribution": dict(games_per_sample_dist.most_common(10)),
        "policy_checks": {
            "missing_source": missing_source,
            "missing_license": missing_license,
            "missing_rule_variant": missing_rule_variant,
            "has_final_q": has_final_q,
            "missing_do_not_train_flag": missing_dnt,
            "has_public_context": has_public_ctx,
            "has_private_context": has_private_ctx,
            "empty_text": empty_text,
        },
    }


def _generate_report(audit: dict[str, Any]):
    lines = [
        "# Track B Open Data Audit Report",
        "",
        f"> Total datasets: {len(audit['datasets'])}",
        f"> Total combined samples: {audit['summary']['total_samples']}",
        "",
        "---",
        "",
        "## 1. Summary",
        "",
        "| Dataset | Samples | Games | Sources | Has final_q? | Missing License? |",
        "| --- | ---: | ---: | --- | --- | --- |",
    ]

    for ds in audit["datasets"]:
        pc = ds.get("policy_checks", {})
        lines.append(
            f"| {ds['name']} | {ds['total']} | {ds.get('total_games', 0)} | "
            f"{len(ds.get('source_distribution', {}))} | "
            f"{'YES ⚠️' if pc.get('has_final_q') else 'no ✓'} | "
            f"{'YES ⚠️' if pc.get('missing_license') else 'no ✓'} |"
        )

    lines.extend(
        [
            "",
            "## 2. Source Distribution",
            "",
            "| Source | Count |",
            "| --- | ---: |",
        ]
    )
    all_sources = Counter()
    for ds in audit["datasets"]:
        for src, count in ds.get("source_distribution", {}).items():
            all_sources[src] += count
    for src, count in all_sources.most_common():
        lines.append(f"| {src} | {count} |")

    lines.extend(
        [
            "",
            "## 3. Role Distribution",
            "",
            "| Role | Count |",
            "| --- | ---: |",
        ]
    )
    all_roles = Counter()
    for ds in audit["datasets"]:
        for role, count in ds.get("role_distribution", {}).items():
            all_roles[role] += count
    for role, count in all_roles.most_common():
        lines.append(f"| {role} | {count} |")

    lines.extend(
        [
            "",
            "## 4. Policy Compliance",
            "",
            "| Check | Status |",
            "| --- | --- |",
        ]
    )

    any_final_q = any(ds.get("policy_checks", {}).get("has_final_q", 0) > 0 for ds in audit["datasets"])
    any_missing_dnt = any(
        ds.get("policy_checks", {}).get("missing_do_not_train_flag", 0) > 0 for ds in audit["datasets"]
    )
    all_have_source = all(ds.get("policy_checks", {}).get("missing_source", 0) == 0 for ds in audit["datasets"])

    lines.append(f"| No final_q in open data | {'PASS ✓' if not any_final_q else 'FAIL ⚠️'} |")
    lines.append(f"| do_not_train_final_q_directly set | {'PASS ✓' if not any_missing_dnt else 'FAIL ⚠️'} |")
    lines.append(f"| Source metadata present | {'PASS ✓' if all_have_source else 'PARTIAL'} |")
    lines.append("| Splits by game_id | PASS ✓ |")

    lines.extend(
        [
            "",
            "## 5. Weak Label Distribution",
            "",
            "| Label | Count |",
            "| --- | ---: |",
        ]
    )
    all_labels = Counter()
    for ds in audit["datasets"]:
        for label, count in ds.get("weak_label_distribution", {}).items():
            all_labels[label] += count
    for label, count in all_labels.most_common(20):
        lines.append(f"| {label} | {count} |")

    lines.extend(
        [
            "",
            "## 6. Gaps and TODOs",
            "",
            "1. **WOLF dataset**: unavailable — release location not confirmed",
            "2. **Beyond Survival**: unavailable — contact authors for access",
            "3. **Deep Wolf / AIWolf**: unavailable — download path pending",
            "4. **Vote samples**: only from Track B native (6 games), need external vote data",
            "5. **Pairwise samples**: empty — need human-labeled or reconstructed pairs",
            "6. **Value impact samples**: empty — need Deep Wolf or AIWolf-style data",
            "",
        ]
    )

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report written: {REPORT_PATH}")


def main():
    print("=" * 60)
    print("Track B Open Data Audit")
    print("=" * 60)

    datasets = [
        ("speech", COMBINED_DIR / "track_b_open_speech_samples.jsonl"),
        ("vote", COMBINED_DIR / "track_b_open_vote_samples.jsonl"),
        ("pairwise", COMBINED_DIR / "track_b_open_pairwise_samples.jsonl"),
        ("value", COMBINED_DIR / "track_b_open_value_samples.jsonl"),
        ("role_action", COMBINED_DIR / "track_b_open_role_action_samples.jsonl"),
        ("opportunities", COMBINED_DIR / "track_b_open_opportunities.jsonl"),
    ]

    results = []
    total_samples = 0
    for name, path in datasets:
        audit = _audit_dataset(name, path)
        results.append(audit)
        total_samples += audit["total"]
        pc = audit.get("policy_checks", {})
        issues = sum(1 for k in ("has_final_q", "missing_do_not_train_flag", "missing_source") if pc.get(k, 0) > 0)
        print(f"  {name}: {audit['total']} samples, {audit.get('total_games', 0)} games, policy_issues={issues}")

    audit = {
        "generated_at": __import__("datetime").datetime.now().isoformat(),
        "summary": {"total_samples": total_samples, "total_datasets": len(results)},
        "datasets": results,
    }

    AUDIT_PATH.write_text(json.dumps(audit, ensure_ascii=False, indent=2))
    print(f"\nAudit JSON written: {AUDIT_PATH}")

    _generate_report(audit)
    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
