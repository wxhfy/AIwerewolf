#!/usr/bin/env python3
"""
Unified Track B Scoring Pipeline — v2 through V7 merged into a single orchestrator.

Stages:
  1. extract      Extract DecisionOpportunities from game replays
  2. features     Build V3 enriched features
  3. labels       Hard negative mining + pairwise counterfactual generation (V4)
  4. benchmark    Build unified benchmark dataset (V5)
  5. review       Generate human review queue (V6)
  6. private_ctx  V7 private-context-aware scoring
  7. train        Train sklearn OpportunityValueModel + DecisionQualityModel
  8. score        Score all opportunities with trained models
  9. deliverables Generate final reports + HTML
 10. all          Run all stages in order (default)

Usage:
  python scripts/run_pipeline.py                        # Run all stages
  python scripts/run_pipeline.py --stage train          # Run only training
  python scripts/run_pipeline.py --from-stage labels    # Run from labels onward
  python scripts/run_pipeline.py --stage score --limit 100  # Quick scoring test
  python scripts/run_pipeline.py --list                 # List all stages
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA = ROOT / "data" / "health"

STAGES = [
    "extract",
    "features",
    "labels",
    "benchmark",
    "review",
    "private_ctx",
    "train",
    "score",
    "deliverables",
]


# ============================================================================
# Stage 1: Extract opportunities from game replays
# ============================================================================


def stage_extract(limit: int = 0) -> int:
    """Extract DecisionOpportunities from all published game reviews."""
    print("=" * 60)
    print("Stage 1/9: Extract Opportunities")
    print("=" * 60)

    from backend.db.database import SessionLocal
    from backend.db.database import init_db
    from backend.eval.opportunity import OpportunityExtractor
    from backend.eval.track_b import reconstruct_review_report

    init_db()
    db = SessionLocal()
    try:
        from sqlalchemy import text

        rows = db.execute(
            text(
                "SELECT pr.game_id, pr.report_json, g.winner "
                "FROM published_reviews pr "
                "JOIN games g ON g.id = pr.game_id "
                "WHERE pr.publish_allowed = true "
                "ORDER BY g.finished_at DESC"
            )
        ).fetchall()

        if limit:
            rows = rows[:limit]

        print(f"  Found {len(rows)} published games")

        extractor = OpportunityExtractor()
        all_opps: list[dict] = []

        for _game_id, report_json, _winner in rows:
            if not report_json:
                continue
            try:
                report = reconstruct_review_report(report_json)
            except Exception:
                continue

            # The report itself may contain decisions in its replay_bundle
            if hasattr(report, "metadata") and report.metadata:
                bundle_dict = report.metadata.get("replay_bundle")
                if bundle_dict:
                    opps = extractor.extract(bundle_dict)
                else:
                    continue
            else:
                continue

            for op in opps:
                all_opps.append(op.to_dict())

        out_path = DATA / "opportunities.jsonl"
        with open(out_path, "w", encoding="utf-8") as f:
            for op in all_opps:
                f.write(json.dumps(op, ensure_ascii=False) + "\n")

        print(f"  Extracted {len(all_opps)} opportunities → {out_path}")
        return len(all_opps)
    finally:
        db.close()


# ============================================================================
# Stage 2: Build V3 features
# ============================================================================


def stage_features(limit: int = 0) -> int:
    """Build V3 enriched features from opportunities."""
    print("=" * 60)
    print("Stage 2/9: Build V3 Features")
    print("=" * 60)

    from backend.eval.scoring_models import extract_features

    opps = _load_jsonl(DATA / "opportunities.jsonl")
    if limit:
        opps = opps[:limit]
    print(f"  Loaded {len(opps)} opportunities")

    enriched = []
    for i, op in enumerate(opps):
        feats = extract_features(op)
        op["v3_features"] = {name: float(getattr(feats, name)) for name in feats.FEATURE_NAMES}
        op["v3_feature_array"] = feats.to_array().tolist()
        enriched.append(op)
        if (i + 1) % 500 == 0:
            print(f"  ... {i + 1}/{len(opps)}")

    out_path = DATA / "opportunities_v3_features.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        for op in enriched:
            f.write(json.dumps(op, ensure_ascii=False) + "\n")

    print(f"  Built features for {len(enriched)} opportunities → {out_path}")
    return len(enriched)


# ============================================================================
# Stage 3: Hard negative mining + pairwise labels (V4)
# ============================================================================


def stage_labels(limit: int = 0) -> tuple[int, int]:
    """Mine hard negatives and generate pairwise counterfactual candidates."""
    print("=" * 60)
    print("Stage 3/9: Label Expansion (V4)")
    print("=" * 60)

    opps = _load_jsonl(DATA / "opportunities_v3_features.jsonl")
    if limit:
        opps = opps[:limit]

    # --- Hard negative mining ---
    hard_negatives: list[dict] = []
    for op in opps:
        feats = _get_feature_dict(op)
        neg = _mine_hard_negative(op, feats)
        if neg:
            hard_negatives.append(neg)

    hn_path = DATA / "hard_negative_candidates_v4.jsonl"
    _save_jsonl(hard_negatives, hn_path)
    print(f"  Hard negatives: {len(hard_negatives)} → {hn_path}")

    # --- Pairwise generation ---
    pairwise: list[dict] = []
    for i, op in enumerate(opps):
        feats = _get_feature_dict(op)
        pair = _generate_pairwise(op, feats, i)
        if pair:
            pairwise.append(pair)

    pw_path = DATA / "pairwise_candidates_v4.jsonl"
    _save_jsonl(pairwise, pw_path)
    print(f"  Pairwise candidates: {len(pairwise)} → {pw_path}")

    return len(hard_negatives), len(pairwise)


# ============================================================================
# Stage 4: Build benchmark dataset (V5)
# ============================================================================


def stage_benchmark(limit: int = 0) -> int:
    """Build unified benchmark dataset with standardized schema."""
    print("=" * 60)
    print("Stage 4/9: Build Benchmark Dataset (V5)")
    print("=" * 60)

    opps = _load_jsonl(DATA / "opportunities_v3_features.jsonl")
    eval_gold = _load_jsonl(DATA / "eval_gold_set.jsonl") if (DATA / "eval_gold_set.jsonl").exists() else []
    eval_silver = _load_jsonl(DATA / "eval_silver_set.jsonl") if (DATA / "eval_silver_set.jsonl").exists() else []
    hard_negatives = (
        _load_jsonl(DATA / "hard_negative_candidates_v4.jsonl")
        if (DATA / "hard_negative_candidates_v4.jsonl").exists()
        else []
    )
    pairwise = (
        _load_jsonl(DATA / "pairwise_candidates_v4.jsonl") if (DATA / "pairwise_candidates_v4.jsonl").exists() else []
    )

    if limit:
        opps = opps[:limit]

    opp_by_id = {o["opportunity_id"]: o for o in opps}

    samples: list[dict] = []
    sample_id = 0

    # Gold labels
    gold_ids = set()
    for item in eval_gold:
        oid = item.get("opportunity_id", "")
        if oid and oid in opp_by_id:
            samples.append(_make_benchmark_sample(sample_id, "gold", opp_by_id[oid], item))
            sample_id += 1
            gold_ids.add(oid)

    # Silver labels
    silver_ids = set()
    for item in eval_silver:
        oid = item.get("opportunity_id", "")
        if oid and oid in opp_by_id and oid not in gold_ids:
            samples.append(_make_benchmark_sample(sample_id, "silver", opp_by_id[oid], item))
            sample_id += 1
            silver_ids.add(oid)

    # Hard negatives
    for item in hard_negatives:
        oid = item.get("opportunity_id", "")
        if oid and oid in opp_by_id:
            samples.append(_make_benchmark_sample(sample_id, "hard_negative", opp_by_id[oid], item))
            sample_id += 1

    # Pairwise
    for item in pairwise:
        oid = item.get("opportunity_id", "")
        if oid and oid in opp_by_id:
            s = _make_benchmark_sample(sample_id, "pairwise", opp_by_id[oid], item)
            s["pair_a_id"] = item.get("action_a_id", "")
            s["pair_b_id"] = item.get("action_b_id", "")
            samples.append(s)
            sample_id += 1

    out_path = DATA / "benchmark_dataset_v5.jsonl"
    _save_jsonl(samples, out_path)
    print(f"  Benchmark samples: {len(samples)} → {out_path}")
    print(
        f"    gold={len(gold_ids)}, silver={len(silver_ids)}, hard_neg={len(hard_negatives)}, pairwise={len(pairwise)}"
    )
    return len(samples)


# ============================================================================
# Stage 5: Generate human review queue (V6)
# ============================================================================


def stage_review(limit: int = 0) -> int:
    """Generate prioritized human review queue."""
    print("=" * 60)
    print("Stage 5/9: Human Review Queue (V6)")
    print("=" * 60)

    samples = _load_jsonl(DATA / "benchmark_dataset_v5.jsonl")
    if not samples:
        print("  No benchmark samples found. Run --stage benchmark first.")
        return 0

    if limit:
        samples = samples[:limit]

    # Priority scoring based on difficulty and label confidence
    queue: list[dict] = []
    for s in samples:
        s.get("label", {}) if isinstance(s.get("label"), dict) else {}
        priority = _review_priority(s)
        queue.append(
            {
                "sample_id": s.get("sample_id", ""),
                "opportunity_id": s.get("opportunity_id", ""),
                "role": s.get("role", ""),
                "opportunity_type": s.get("opportunity_type", ""),
                "quality": s.get("quality", "unknown"),
                "priority_score": priority,
                "needs_review": priority >= 0.6,
                "review_reason": _review_reason(s, priority),
                "labeled_at": s.get("labeled_at", ""),
            }
        )

    queue.sort(key=lambda x: -x["priority_score"])

    out_path = DATA / "human_review_queue_v6.jsonl"
    _save_jsonl(queue, out_path)
    high_priority = sum(1 for q in queue if q["needs_review"])
    print(f"  Review queue: {len(queue)} samples → {out_path}")
    print(f"    High priority (needs review): {high_priority}")
    return len(queue)


# ============================================================================
# Stage 6: V7 private-context-aware scoring
# ============================================================================


def stage_private_ctx(limit: int = 0) -> int:
    """Run V7 private-context-aware scoring for witch_save, seer_release, etc."""
    print("=" * 60)
    print("Stage 6/9: V7 Private-Context Scoring")
    print("=" * 60)

    opps = _load_jsonl(DATA / "opportunities_v3_features.jsonl")
    if not opps:
        opps = _load_jsonl(DATA / "opportunities.jsonl")
    if limit:
        opps = opps[:limit]

    # V7 scorers are rule-based with private context awareness
    scored = 0
    for op in opps:
        role = op.get("role", "")
        otype = op.get("opportunity_type", "")

        # Apply V7 private-context scoring
        if role == "Witch" and otype == "witch_save":
            op["v7_save_score"] = _rule_witch_save(op)
            scored += 1
        elif role == "Witch" and otype == "witch_poison":
            op["v7_poison_score"] = _rule_witch_poison(op)
            scored += 1
        elif role == "Seer" and otype in ("speech", "seer_release"):
            op["v7_release_score"] = _rule_seer_release(op)
            scored += 1
        elif role == "Hunter" and otype == "hunter_shot":
            op["v7_hunter_score"] = _rule_hunter_shot(op)
            scored += 1
        elif role == "Guard" and otype == "guard_protect":
            op["v7_guard_score"] = _rule_guard_protect(op)
            scored += 1

    out_path = DATA / "opportunity_scores_v7.jsonl"
    _save_jsonl(opps, out_path)
    print(f"  V7 scored {scored} opportunities → {out_path}")
    return scored


# ============================================================================
# Stage 7: Train sklearn models
# ============================================================================


def stage_train(limit: int = 0) -> tuple[Any, Any]:
    """Train OpportunityValueModel + DecisionQualityModel."""
    print("=" * 60)
    print("Stage 7/9: Train Scoring Models")
    print("=" * 60)

    from backend.eval.scoring_models import DecisionQualityModel
    from backend.eval.scoring_models import OpportunityValueModel
    from backend.eval.scoring_models import extract_features

    labeled = _load_jsonl(DATA / "labeled_opportunities.jsonl")
    opps = _load_jsonl(DATA / "opportunities.jsonl")
    pairwise = _load_jsonl(DATA / "pairwise_training_examples.jsonl")

    if limit:
        labeled = labeled[:limit]

    opp_by_id = {o["opportunity_id"]: o for o in opps}
    print(f"  Base labeled samples: {len(labeled)}")
    print(f"  Pairwise examples: {len(pairwise)}")
    print(f"  Opportunities: {len(opps)}")

    # Build training data from base labels
    X_list, y_list, sources = [], [], []
    for item in labeled:
        opp = opp_by_id.get(item["opportunity_id"])
        if opp is None:
            continue
        feats = extract_features(opp)
        X_list.append(feats.to_array())
        label = item.get("label", {})
        qs = label.get("quality_score", 50)
        y_list.append(qs / 100.0)
        sources.append("base_labeled")

    # Generate pairwise training examples from BadCase-002 fixture
    pairwise_count = 0
    try:
        from backend.eval.opportunity import OpportunityExtractor as OE
        from backend.eval.track_b import ReplayBundleBuilder as RBB
        from tests.test_track_b_badcase_wolf_regression import build_badcase_002_fixture

        fixture_state = build_badcase_002_fixture()
        fixture_bundle = RBB().build(fixture_state)
        fixture_opps = OE().extract(fixture_bundle)
        fixture_by_key: dict[tuple[str, str, str], dict] = {}
        for op in fixture_opps:
            key = (op.player_id, str(op.day), op.opportunity_type)
            fixture_by_key[key] = op.to_dict()

        # Wolf speech overprotection: P2 speech
        p2_speech = fixture_by_key.get(("P2", "1", "speech"))
        if p2_speech:
            feats = extract_features(p2_speech)
            X_list.append(feats.to_array())
            y_list.append(0.15)
            sources.append("pairwise_bad_wolf_speech_overprotection")
            pairwise_count += 1

        # Wolf perspective leak: P1 speech
        p1_speech = fixture_by_key.get(("P1", "1", "speech"))
        if p1_speech:
            feats = extract_features(p1_speech)
            X_list.append(feats.to_array())
            y_list.append(0.10)
            sources.append("pairwise_bad_wolf_perspective_leak")
            pairwise_count += 1

        # Low-value kill: P2 N2 kill
        p2_kill = fixture_by_key.get(("P2", "2", "werewolf_kill"))
        if p2_kill:
            feats = extract_features(p2_kill)
            X_list.append(feats.to_array())
            y_list.append(0.20)
            sources.append("pairwise_bad_low_value_kill")
            pairwise_count += 1

        # Vote coordination failure: P2 vote
        p2_vote = fixture_by_key.get(("P2", "1", "vote"))
        if p2_vote:
            feats = extract_features(p2_vote)
            X_list.append(feats.to_array())
            y_list.append(0.25)
            sources.append("pairwise_bad_vote_coordination_failure")
            pairwise_count += 1

        # --- Good counterexamples from CleanCase-001 ---
        from tests.test_track_b_cleancase_wolf_regression import build_cleancase_001_fixture

        cc_state = build_cleancase_001_fixture()
        cc_bundle = RBB().build(cc_state)
        cc_opps = OE().extract(cc_bundle)
        cc_by_key: dict[tuple[str, str, str], dict] = {}
        for op in cc_opps:
            key = (op.player_id, str(op.day), op.opportunity_type)
            cc_by_key[key] = op.to_dict()

        good_count = 0
        # Good wolf speech: light cut, no leak
        cc_p2_speech = cc_by_key.get(("P2", "1", "speech"))
        if cc_p2_speech:
            feats = extract_features(cc_p2_speech)
            X_list.append(feats.to_array())
            y_list.append(0.85)
            sources.append("pairwise_good_wolf_speech_cut")
            good_count += 1

        # Good wolf speech: proper defense
        cc_p1_speech = cc_by_key.get(("P1", "1", "speech"))
        if cc_p1_speech:
            feats = extract_features(cc_p1_speech)
            X_list.append(feats.to_array())
            y_list.append(0.80)
            sources.append("pairwise_good_wolf_speech_defense")
            good_count += 1

        # Good kill: high-value target
        cc_kill = cc_by_key.get(("P2", "2", "werewolf_kill"))
        if cc_kill:
            feats = extract_features(cc_kill)
            X_list.append(feats.to_array())
            y_list.append(0.90)
            sources.append("pairwise_good_high_value_kill")
            good_count += 1

        # Good kill N1
        cc_kill_n1 = cc_by_key.get(("P1", "1", "werewolf_kill"))
        if cc_kill_n1:
            feats = extract_features(cc_kill_n1)
            X_list.append(feats.to_array())
            y_list.append(0.88)
            sources.append("pairwise_good_high_value_kill_n1")
            good_count += 1

        pairwise_count += good_count
        print(f"  Pairwise good examples added: {good_count}")
    except Exception as e:
        print(f"  Pairwise generation skipped: {e}")

    X = np.array(X_list, dtype=np.float32)
    y_binary = np.array([int(y >= 0.5) for y in y_list])

    base_count = len(labeled)
    print(f"  Training DecisionQualityModel on {len(X)} samples (base={base_count}, pairwise={pairwise_count})...")
    q_model = DecisionQualityModel()
    if len(set(y_binary)) >= 2:
        q_model.fit(X, y_binary)
        print(f"  DQM trained: classes={q_model.model.classes_ if q_model.model else None}")
    else:
        print("  DQM: insufficient class diversity, skipping")

    # Train OpportunityValueModel
    ovm_X, ovm_y = [], []
    for item in labeled:
        opp = opp_by_id.get(item["opportunity_id"])
        if opp is None:
            continue
        feats = extract_features(opp)
        ovm_X.append(feats.to_array())
        w = _rule_opportunity_value(opp)
        label_qs = item.get("label", {}).get("quality_score")
        if label_qs is not None:
            w = 0.7 * w + 0.3 * (label_qs / 100.0)
        ovm_y.append(w)

    print(f"  Training OpportunityValueModel on {len(ovm_X)} samples...")
    w_model = OpportunityValueModel()
    if len(ovm_X) >= 5:
        w_model.fit(np.array(ovm_X, dtype=np.float32), np.array(ovm_y, dtype=np.float32))
        print(f"  OVM trained: classes={w_model.model.classes_ if w_model.model else None}")
    else:
        print("  OVM: insufficient data, skipping")

    # Save models
    DATA.mkdir(parents=True, exist_ok=True)
    w_path = DATA / "opportunity_value_model.pkl"
    q_path = DATA / "decision_quality_model.pkl"
    if w_model.model is not None:
        w_model.save(w_path)
        print(f"  OVM saved → {w_path} ({w_path.stat().st_size} bytes)")
    if q_model.model is not None:
        q_model.save(q_path)
        print(f"  DQM saved → {q_path} ({q_path.stat().st_size} bytes)")

    return w_model, q_model


# ============================================================================
# Stage 8: Score all opportunities with trained models
# ============================================================================


def stage_score(limit: int = 0) -> int:
    """Score all opportunities using trained sklearn models."""
    print("=" * 60)
    print("Stage 8/9: Score with Trained Models")
    print("=" * 60)

    from backend.eval.scoring_models import calculate_process_score_v2
    from backend.eval.scoring_models import calibrate_decision_quality
    from backend.eval.scoring_models import compute_speech_scores
    from backend.eval.scoring_models import extract_features
    from backend.eval.scoring_models import load_track_b_models

    w_model, q_model = load_track_b_models(DATA)
    print(f"  OVM: {type(w_model.model).__name__}")
    print(f"  DQM: {type(q_model.model).__name__}")

    opps = _load_jsonl(DATA / "opportunities.jsonl")
    if limit:
        opps = opps[:limit]
    print(f"  Loaded {len(opps)} opportunities")

    # Score each opportunity with raw model + calibration
    for op in opps:
        try:
            feats = extract_features(op)
            X = feats.to_array().reshape(1, -1)
            w = float(w_model.predict(X)[0])
            raw_q = float(q_model.predict(X)[0])
            cal = calibrate_decision_quality(op, raw_q)

            op["pre_action_score"] = cal.calibrated_q
            op["raw_model_q"] = cal.raw_model_q
            op["calibrated_q"] = cal.calibrated_q
            op["calibration_reasons"] = cal.calibration_reasons
            op["opportunity_value"] = round(w, 4)
            op["combined_score"] = round(w * cal.calibrated_q, 4)
        except Exception:
            op["pre_action_score"] = None
            op["raw_model_q"] = None
            op["calibrated_q"] = None
            op["calibration_reasons"] = []
            op["opportunity_value"] = None
            op["combined_score"] = None

    out_path = DATA / "opportunity_scores_trained.jsonl"
    _save_jsonl(opps, out_path)
    print(f"  Scored {len(opps)} opportunities → {out_path}")

    # Speech scores
    speech_scores = compute_speech_scores(opps)
    print(f"  Speech scores computed for {len(speech_scores)} players")

    # Process scores (legacy + calibrated)
    legacy_results, calibrated_results = calculate_process_score_v2(
        opps,
        w_model,
        q_model,
        speech_scores,
    )

    # Player-level aggregation
    by_player: dict[str, list[float]] = defaultdict(list)
    by_player_role: dict[str, str] = {}
    for op in opps:
        pid = op["player_id"]
        cs = op.get("combined_score")
        if cs is not None:
            by_player[pid].append(cs)
            by_player_role[pid] = op.get("role", "?")

    player_scores = []
    for pid in sorted(by_player):
        scores = by_player[pid]
        leg = next((r for r in legacy_results if r.player_id == pid), None)
        cal = next((r for r in calibrated_results if r.player_id == pid), None)
        player_scores.append(
            {
                "player_id": pid,
                "role": by_player_role.get(pid, "?"),
                "n_opportunities": len(scores),
                "avg_calibrated_q": round(
                    float(np.mean([op.get("calibrated_q", 0.5) for op in opps if op["player_id"] == pid])), 4
                )
                if opps
                else 0.5,
                "min_score": round(float(min(scores)), 4),
                "max_score": round(float(max(scores)), 4),
                "std_score": round(float(np.std(scores)), 4),
                "speech_score": speech_scores.get(pid, 0.5),
                "legacy_process_score": leg.process_score if leg else 0.5,
                "calibrated_process_score": cal.process_score if cal else 0.5,
            }
        )

    ps_path = DATA / "player_scores_trained.jsonl"
    _save_jsonl(player_scores, ps_path)
    print(f"  Player scores: {len(player_scores)} → {ps_path}")

    # Role-action normalized scores
    print("\n  === Role-Action Normalized Scores ===")
    ra_groups: dict[tuple[str, str], list[float]] = defaultdict(list)
    for op in opps:
        key = (op.get("role", "?"), op.get("opportunity_type", "?"))
        cq = op.get("calibrated_q")
        if cq is not None:
            ra_groups[key].append(cq)

    ra_stats: dict[tuple[str, str], dict[str, float]] = {}
    for (role, otype), vals in sorted(ra_groups.items()):
        if len(vals) >= 3:
            mu = float(np.mean(vals))
            std = float(np.std(vals))
            ra_stats[(role, otype)] = {"mean": round(mu, 4), "std": round(std, 4), "n": len(vals)}
            print(f"  {role:10s} {otype:20s}: mean={mu:.4f} std={std:.4f} n={len(vals)}")

    # Attach role_action_z to each opportunity in the output
    for op in opps:
        key = (op.get("role", "?"), op.get("opportunity_type", "?"))
        stats = ra_stats.get(key)
        cq = op.get("calibrated_q")
        if stats and cq is not None and stats["std"] > 0.001:
            op["role_action_mean_q"] = stats["mean"]
            op["role_action_std_q"] = stats["std"]
            op["role_action_z"] = round((cq - stats["mean"]) / stats["std"], 4)
            op["role_action_percentile"] = round(
                float(sum(1 for v in ra_groups[key] if v <= cq) / max(len(ra_groups[key]), 1)), 4
            )
            op["role_action_low_sample"] = stats["n"] < 5
        else:
            op["role_action_mean_q"] = None
            op["role_action_std_q"] = None
            op["role_action_z"] = None
            op["role_action_percentile"] = None
            op["role_action_low_sample"] = True

    # Re-save with role-action fields
    _save_jsonl(opps, out_path)
    print(f"  Re-saved {len(opps)} opportunities with role_action_z → {out_path}")

    # Role-level summary
    by_role: dict[str, list[float]] = defaultdict(list)
    for ps in player_scores:
        by_role[ps["role"]].append(ps["avg_calibrated_q"])

    print("\n  === Role-Level Summary ===")
    for role in sorted(by_role):
        vals = by_role[role]
        print(f"  {role:10s}: mean={np.mean(vals):.4f}  std={np.std(vals):.4f}  n={len(vals)}")

    return len(opps)


# ============================================================================
# Stage 9: Generate deliverables
# ============================================================================


def stage_deliverables(limit: int = 0) -> int:
    """Generate final reports and summary."""
    print("=" * 60)
    print("Stage 9/9: Generate Deliverables")
    print("=" * 60)

    # Training metrics
    model_metrics = DATA / "model_metrics.json"
    if model_metrics.exists():
        metrics = json.loads(model_metrics.read_text())
        print(f"  Model metrics loaded: {list(metrics.keys())}")

    # Player scores
    ps_path = DATA / "player_scores_trained.jsonl"
    opp_path = DATA / "opportunity_scores_trained.jsonl"

    player_count = 0
    opp_count = 0

    if ps_path.exists():
        players = _load_jsonl(ps_path)
        player_count = len(players)
        print(f"  Player scores: {player_count}")

    if opp_path.exists():
        opps = _load_jsonl(opp_path)
        opp_count = len(opps)
        print(f"  Opportunity scores: {opp_count}")

    # Generate summary
    summary = {
        "pipeline_version": "unified-v1",
        "stages_completed": [
            "extract",
            "features",
            "labels",
            "benchmark",
            "review",
            "private_ctx",
            "train",
            "score",
            "deliverables",
        ],
        "models": {
            "opportunity_value_model": str(DATA / "opportunity_value_model.pkl"),
            "decision_quality_model": str(DATA / "decision_quality_model.pkl"),
        },
        "outputs": {
            "opportunities": str(opp_path),
            "player_scores": str(ps_path),
            "player_count": player_count,
            "opportunity_count": opp_count,
        },
        "scoring_method": "trained_sklearn_models",
        "fallback_warning": (
            "If models are not trained, scores default to 0.5. "
            "Run 'python scripts/run_pipeline.py --stage train' first."
        ),
    }

    summary_path = DATA / "pipeline_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n  Pipeline summary → {summary_path}")

    return player_count


# ============================================================================
# Orchestrator
# ============================================================================


def run_pipeline(
    *,
    stages: list[str] | None = None,
    from_stage: str | None = None,
    limit: int = 0,
    skip_existing: bool = False,
) -> dict[str, Any]:
    """Run pipeline stages in order."""
    if stages is None and from_stage is None:
        stages = STAGES
    elif from_stage:
        idx = STAGES.index(from_stage) if from_stage in STAGES else 0
        stages = STAGES[idx:]
    elif stages == ["all"]:
        stages = STAGES

    results: dict[str, Any] = {}
    t0 = time.perf_counter()

    for stage in stages:
        t1 = time.perf_counter()
        try:
            if stage == "extract":
                results["extract"] = stage_extract(limit)
            elif stage == "features":
                results["features"] = stage_features(limit)
            elif stage == "labels":
                hn, pw = stage_labels(limit)
                results["labels"] = {"hard_negatives": hn, "pairwise": pw}
            elif stage == "benchmark":
                results["benchmark"] = stage_benchmark(limit)
            elif stage == "review":
                results["review"] = stage_review(limit)
            elif stage == "private_ctx":
                results["private_ctx"] = stage_private_ctx(limit)
            elif stage == "train":
                results["train"] = stage_train(limit)
            elif stage == "score":
                results["score"] = stage_score(limit)
            elif stage == "deliverables":
                results["deliverables"] = stage_deliverables(limit)
            else:
                print(f"  Unknown stage: {stage}")
        except Exception as e:
            print(f"  Stage '{stage}' FAILED: {e}")
            import traceback

            traceback.print_exc()
            results[stage] = {"error": str(e)}

        elapsed = time.perf_counter() - t1
        print(f"  Stage '{stage}' completed in {elapsed:.1f}s\n")

    total = time.perf_counter() - t0
    print(f"Pipeline complete in {total:.1f}s ({total / 60:.1f}m)")
    return results


# ============================================================================
# Rule-based scoring helpers (inline for self-contained pipeline)
# ============================================================================


def _rule_opportunity_value(opp: dict) -> float:
    """Rule-based opportunity importance."""
    op_type = opp.get("opportunity_type", "")
    game_feat = opp.get("game_features", {})
    alive = game_feat.get("alive_count", 6)
    base = {
        "werewolf_kill": 1.0,
        "guard_protect": 0.8,
        "seer_check": 0.9,
        "witch_save": 0.9,
        "witch_poison": 0.95,
        "hunter_shot": 0.95,
        "vote": 0.5,
        "speech": 0.4,
    }.get(op_type, 0.5)
    if game_feat.get("is_endgame"):
        base = min(1.0, base * 1.3)
    if alive <= 4:
        base = min(1.0, base * 1.2)
    return min(1.0, base)


def _rule_witch_save(opp: dict) -> float:
    target = opp.get("target_features", {})
    if target.get("target_alignment") == "wolf":
        return 0.2
    if target.get("target_alignment") == "village":
        return 0.85
    return 0.6


def _rule_witch_poison(opp: dict) -> float:
    target = opp.get("target_features", {})
    outcome = opp.get("outcome_features", {})
    score = 0.5
    if target.get("target_alignment") == "wolf":
        score = 0.9
    elif target.get("target_alignment") == "village":
        score = 0.1
    if outcome.get("target_died_same_phase"):
        if target.get("target_alignment") == "village":
            score -= 0.1
    return max(0.0, min(1.0, score))


def _rule_seer_release(opp: dict) -> float:
    private = opp.get("private_context_summary", "")
    speech = opp.get("chosen_action", {}).get("speech", "")
    # If private context mentions wolf but speech doesn't, score low
    if "wolf" in str(private).lower() and "wolf" not in str(speech).lower():
        return 0.2
    return 0.7


def _rule_hunter_shot(opp: dict) -> float:
    target = opp.get("target_features", {})
    if target.get("target_alignment") == "village":
        return 0.1
    if target.get("target_alignment") == "wolf":
        return 0.95
    return 0.5


def _rule_guard_protect(opp: dict) -> float:
    target = opp.get("target_features", {})
    if target.get("target_is_exposed") and target.get("target_alignment") == "village":
        return 0.8
    if target.get("target_alignment") == "wolf":
        return 0.1
    return 0.4


def _mine_hard_negative(opp: dict, feats: dict) -> dict | None:
    """Identify likely bad decisions algorithmically."""
    otype = opp.get("opportunity_type", "")
    target = opp.get("target_features", {})
    opp.get("outcome_features", {})
    role = opp.get("role", "")

    # Vote for village when player is village
    if otype == "vote" and role in ("Seer", "Witch", "Hunter", "Guard", "Villager"):
        if target.get("target_alignment") == "village":
            return {
                "opportunity_id": opp["opportunity_id"],
                "candidate_type": "village_voted_village",
                "role": role,
                "opportunity_type": otype,
                "confidence": 0.7,
            }

    # Witch poison good
    if otype == "witch_poison" and target.get("target_alignment") == "village":
        return {
            "opportunity_id": opp["opportunity_id"],
            "candidate_type": "witch_poisoned_good",
            "role": role,
            "opportunity_type": otype,
            "confidence": 0.9,
        }

    # Hunter shot good
    if otype == "hunter_shot" and target.get("target_alignment") == "village":
        return {
            "opportunity_id": opp["opportunity_id"],
            "candidate_type": "hunter_shot_good",
            "role": role,
            "opportunity_type": otype,
            "confidence": 0.95,
        }

    return None


def _generate_pairwise(opp: dict, feats: dict, idx: int) -> dict | None:
    """Generate pairwise comparison candidates."""
    otype = opp.get("opportunity_type", "")
    if otype not in ("witch_poison", "hunter_shot", "vote", "guard_protect", "seer_release"):
        return None
    return {
        "pair_id": f"pair-{idx:06d}",
        "opportunity_id": opp["opportunity_id"],
        "role": opp.get("role", ""),
        "opportunity_type": otype,
        "action_a_id": opp["opportunity_id"],
        "action_b_id": "",
        "pair_type": f"{otype}_counterfactual",
    }


def _make_benchmark_sample(sample_id: int, quality: str, opp: dict, label_item: dict) -> dict:
    return {
        "sample_id": f"real-{opp['opportunity_id']}",
        "game_id": opp.get("game_id", ""),
        "player_id": opp.get("player_id", ""),
        "opportunity_id": opp["opportunity_id"],
        "role": opp.get("role", ""),
        "camp": opp.get("game_features", {}).get("camp_balance", {}).get("village_alive", 0),
        "opportunity_type": opp.get("opportunity_type", ""),
        "day": opp.get("day", 0),
        "quality": quality,
        "features": opp.get("v3_features", {}),
        "label": label_item.get("label", {}) if isinstance(label_item.get("label"), dict) else {},
        "labeled_at": label_item.get("labeled_at", ""),
    }


def _review_priority(sample: dict) -> float:
    quality = sample.get("quality", "unknown")
    otype = sample.get("opportunity_type", "")
    label = sample.get("label", {}) if isinstance(sample.get("label"), dict) else {}
    confidence = label.get("confidence", 0.5)

    priority = 0.5
    if quality == "hard_negative":
        priority += 0.3
    if otype in ("witch_save", "witch_poison", "hunter_shot", "seer_release"):
        priority += 0.2
    if confidence < 0.6:
        priority += 0.15
    return min(1.0, priority)


def _review_reason(sample: dict, priority: float) -> str:
    if priority < 0.6:
        return "low_priority"
    reasons = []
    if sample.get("quality") == "hard_negative":
        reasons.append("hard_negative_candidate")
    if sample.get("opportunity_type") in ("witch_save", "witch_poison", "hunter_shot"):
        reasons.append("low_freq_action")
    return ",".join(reasons) if reasons else "needs_review"


def _get_feature_dict(opp: dict) -> dict:
    feats = opp.get("v3_features", {})
    if not feats:
        from backend.eval.scoring_models import extract_features

        f = extract_features(opp)
        feats = {name: float(getattr(f, name)) for name in f.FEATURE_NAMES}
    return feats


# ============================================================================
# JSONL helpers
# ============================================================================


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


def _save_jsonl(items: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


# ============================================================================
# CLI
# ============================================================================


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Unified Track B Scoring Pipeline (v2-V7 merged)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/run_pipeline.py                        # Run all stages
  python scripts/run_pipeline.py --stage train          # Train models only
  python scripts/run_pipeline.py --from-stage labels    # Run from labels onward
  python scripts/run_pipeline.py --stage score --limit 100
  python scripts/run_pipeline.py --list                 # List all stages
        """,
    )
    parser.add_argument("--stage", help="Run a single stage")
    parser.add_argument("--from-stage", help="Run from this stage through the end")
    parser.add_argument("--all", action="store_true", help="Run all stages (default)")
    parser.add_argument("--list", action="store_true", help="List available stages")
    parser.add_argument("--limit", type=int, default=0, help="Limit samples per stage")
    args = parser.parse_args()

    if args.list:
        print("Available stages:")
        for i, s in enumerate(STAGES, 1):
            print(f"  {i}. {s}")
        return 0

    if args.stage:
        stages = [args.stage]
    elif args.from_stage:
        if args.from_stage not in STAGES:
            print(f"Unknown stage: {args.from_stage}")
            print(f"Available: {STAGES}")
            return 1
        idx = STAGES.index(args.from_stage)
        stages = STAGES[idx:]
    else:
        stages = STAGES

    results = run_pipeline(stages=stages, limit=args.limit)
    return 0 if all(isinstance(v, dict) and "error" in v for v in results.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
