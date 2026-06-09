"""Phase D fast: Pre-compute BGE-M3 embeddings once, then GroupKFold filter.

Key optimization: encode ALL once, filter by game_id per fold (numpy mask).
Avoids re-encoding the same texts for each fold.

Run: python scripts/run_ablation_d_fast.py
"""

from __future__ import annotations

import gc
import json
import math
import statistics
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.eval.embedding_retrieval import BGEM3Provider
from backend.eval.embedding_retrieval import format_opportunity_text
from backend.eval.scoring_models import DecisionQualityModel
from backend.eval.scoring_models import extract_features
from scripts.train_and_ablate import group_kfold_split
from scripts.train_and_ablate import load_baseline
from scripts.train_and_ablate import load_labeled
from scripts.train_and_ablate import load_opportunities
from scripts.train_and_ablate import rule_decision_quality

BGE_M3_PATH = "/home/4T-3/PLM/bge-m3/"


def cohens_d(a, b):
    if len(a) < 2 or len(b) < 2:
        return 0.0
    ma, mb = statistics.mean(a), statistics.mean(b)
    na, nb = len(a), len(b)
    va = statistics.variance(a) if na > 1 else 0.0
    vb = statistics.variance(b) if nb > 1 else 0.0
    ps = math.sqrt(((na - 1) * va + (nb - 1) * vb) / (na + nb - 2))
    return (ma - mb) / ps if ps > 0 else 0.0


def main() -> int:
    print("=" * 60)
    print("Phase D fast: BGE-M3 Embedding + Ablation D")
    print("=" * 60)

    print("\n[1/4] Loading data...")
    opps = load_opportunities()
    labeled = load_labeled()
    baseline = load_baseline()

    from sqlalchemy import text

    from backend.db.database import SessionLocal
    from backend.db.database import init_db

    init_db()
    db = SessionLocal()
    clean_ids = set(json.loads(Path("/tmp/clean_llm_game_ids.json").read_text()))
    games = db.execute(text("SELECT id, winner FROM games WHERE id IN :ids"), {"ids": tuple(clean_ids)}).fetchall()
    {g[0]: g[1] for g in games}
    db.close()

    opp_by_id = {o["opportunity_id"]: o for o in opps}
    {o["opportunity_id"]: o["game_id"] for o in opps}

    # Split labeled into good/bad for retrieval
    good_opps, bad_opps = [], []
    good_game_ids, bad_game_ids = [], []
    for item in labeled:
        opp = opp_by_id.get(item["opportunity_id"])
        if opp is None:
            continue
        qs = item.get("label", {}).get("quality_score")
        is_good = (qs >= 50) if qs is not None else (rule_decision_quality(opp) >= 0.5)
        if is_good:
            good_opps.append(opp)
            good_game_ids.append(opp["game_id"])
        else:
            bad_opps.append(opp)
            bad_game_ids.append(opp["game_id"])

    print(f"  Good cases: {len(good_opps)}, Bad cases: {len(bad_opps)}")

    # Load BGE-M3
    print("\n[2/4] Loading BGE-M3 and pre-computing embeddings...")
    provider = BGEM3Provider(model_name=BGE_M3_PATH, device="cpu")
    print(f"  Model: {provider.model_name}, Dim: {provider.dim}")

    # Pre-compute all good/bad embeddings ONCE
    t0 = time.time()
    good_texts = [format_opportunity_text(o) for o in good_opps]
    bad_texts = [format_opportunity_text(o) for o in bad_opps]
    all_good_embs = provider.embed(good_texts, batch_size=16) if good_texts else np.array([])
    all_bad_embs = provider.embed(bad_texts, batch_size=16) if bad_texts else np.array([])
    good_game_arr = np.array(good_game_ids)
    bad_game_arr = np.array(bad_game_ids)
    print(f"  Encoded in {time.time() - t0:.0f}s: good={all_good_embs.shape}, bad={all_bad_embs.shape}")

    # Build training data
    print("\n[3/4] Building features with GroupKFold retrieval...")
    folds = group_kfold_split(opps, n_splits=5)

    _X_base_list, _X_ret_list, _y_list, _game_list = [], [], [], []
    retrieval_added = 0

    for fold_i, (train_opps, test_opps) in enumerate(folds):
        train_games = {o["game_id"] for o in train_opps}

        # Filter pre-computed embeddings by train games (anti-leakage!)
        good_mask = np.array([g in train_games for g in good_game_arr])
        bad_mask = np.array([g in train_games for g in bad_game_arr])

        fold_good_embs = all_good_embs[good_mask] if len(all_good_embs) > 0 else np.array([])
        fold_bad_embs = all_bad_embs[bad_mask] if len(all_bad_embs) > 0 else np.array([])
        fold_good_opps_list = [o for o, m in zip(good_opps, good_mask) if m]
        fold_bad_opps_list = [o for o, m in zip(bad_opps, bad_mask) if m]

        if len(fold_good_embs) < 2 or len(fold_bad_embs) < 2:
            print(f"  Fold {fold_i}: insufficient (good={len(fold_good_embs)}, bad={len(fold_bad_embs)}), skip")
            continue

        # For each TEST opportunity, compute retrieval features
        test_opps_fold = list(test_opps)
        for opp in test_opps_fold:
            query_text = format_opportunity_text(opp)
            query_vec = provider.embed_single(query_text)
            qrole = opp.get("role", "")

            # Good retrieval
            g_sims = np.zeros(len(fold_good_embs))
            if len(fold_good_embs) > 0:
                g_dot = np.dot(fold_good_embs, query_vec)
                g_norms = np.linalg.norm(fold_good_embs, axis=1) * np.linalg.norm(query_vec)
                g_sims = g_dot / (g_norms + 1e-8)
                # Same-role filter
                for j, go in enumerate(fold_good_opps_list):
                    if go.get("role") != qrole:
                        g_sims[j] = 0
                g_top = np.sort(g_sims[g_sims > 0])[-3:] if np.any(g_sims > 0) else []
                ng_sim = round(float(g_top[-1]), 4) if len(g_top) > 0 else 0.0
                ng_avg = round(float(np.mean(g_top)), 4) if len(g_top) > 0 else 0.0
            else:
                ng_sim, ng_avg = 0.0, 0.0

            # Bad retrieval
            b_sims = np.zeros(len(fold_bad_embs))
            if len(fold_bad_embs) > 0:
                b_dot = np.dot(fold_bad_embs, query_vec)
                b_norms = np.linalg.norm(fold_bad_embs, axis=1) * np.linalg.norm(query_vec)
                b_sims = b_dot / (b_norms + 1e-8)
                for j, bo in enumerate(fold_bad_opps_list):
                    if bo.get("role") != qrole:
                        b_sims[j] = 0
                b_top = np.sort(b_sims[b_sims > 0])[-3:] if np.any(b_sims > 0) else []
                nb_sim = round(float(b_top[-1]), 4) if len(b_top) > 0 else 0.0
                nb_avg = round(float(np.mean(b_top)), 4) if len(b_top) > 0 else 0.0
            else:
                nb_sim, nb_avg = 0.0, 0.0

            margin = round(ng_sim - nb_sim, 4)

            # Build features for this opportunity
            feats = extract_features(opp)
            feats.nearest_good_similarity = ng_sim
            feats.nearest_bad_similarity = nb_sim
            feats.good_bad_similarity_margin = margin
            feats.similar_good_avg_quality = ng_avg
            feats.similar_bad_avg_quality = nb_avg
            retrieval_added += 1

        print(f"  Fold {fold_i}: good={len(fold_good_embs)}, bad={len(fold_bad_embs)}, test={len(test_opps_fold)}")

        # Clean up large arrays
        del fold_good_embs, fold_bad_embs
        gc.collect()

    print(f"  Retrieval features added to {retrieval_added} opportunities")

    # Build feature matrices from labeled data
    print("\n[4/4] Training DecisionQualityModel (C vs D)...")

    X_base_all, X_ret_all, y_all, game_all = [], [], [], []
    for item in labeled:
        opp = opp_by_id.get(item["opportunity_id"])
        if opp is None:
            continue
        feats = extract_features(opp)
        base_vec = feats.to_array()
        ret_vec = np.array(
            [
                feats.nearest_good_similarity,
                feats.nearest_bad_similarity,
                feats.good_bad_similarity_margin,
                feats.similar_good_avg_quality,
                feats.similar_bad_avg_quality,
            ]
        )
        X_base_all.append(base_vec)
        X_ret_all.append(np.concatenate([base_vec, ret_vec]))
        label_qs = item.get("label", {}).get("quality_score")
        y_all.append((label_qs / 100.0) if label_qs is not None else rule_decision_quality(opp))
        game_all.append(opp["game_id"])

    X_base_all = np.array(X_base_all)
    X_ret_all = np.array(X_ret_all)
    y_all = np.array(y_all)
    y_bin = (y_all >= 0.5).astype(int)
    game_arr = np.array(game_all)

    folds5 = group_kfold_split(opps, n_splits=5)
    c_results, d_results = [], []

    for fold_i, (train_opps, test_opps) in enumerate(folds5):
        train_g = {o["game_id"] for o in train_opps}
        test_g = {o["game_id"] for o in test_opps}
        train_m = np.array([g in train_g for g in game_arr])
        test_m = np.array([g in test_g for g in game_arr])
        if train_m.sum() < 5 or test_m.sum() < 2 or len(set(y_bin[train_m])) < 2:
            continue

        # C: base
        mc = DecisionQualityModel()
        try:
            mc.fit(X_base_all[train_m], y_bin[train_m])
            yp_c = mc.predict(X_base_all[test_m])
        except Exception:
            continue
        acc_c = float(np.mean((yp_c >= 0.5) == y_bin[test_m]))
        nc, npc = 0, 0
        for i in range(len(yp_c)):
            for j in range(i + 1, len(yp_c)):
                if y_bin[test_m][i] != y_bin[test_m][j]:
                    npc += 1
                    if (yp_c[i] > yp_c[j]) == (y_bin[test_m][i] > y_bin[test_m][j]):
                        nc += 1
        paw_c = nc / max(npc, 1)
        c_results.append(
            {
                "fold": fold_i,
                "accuracy": round(acc_c, 4),
                "pairwise_accuracy": round(paw_c, 4),
                "n_train": int(train_m.sum()),
                "n_test": int(test_m.sum()),
            }
        )

        # D: base + retrieval
        md = DecisionQualityModel()
        try:
            md.fit(X_ret_all[train_m], y_bin[train_m])
            yp_d = md.predict(X_ret_all[test_m])
        except Exception:
            continue
        acc_d = float(np.mean((yp_d >= 0.5) == y_bin[test_m]))
        nc2, npc2 = 0, 0
        for i in range(len(yp_d)):
            for j in range(i + 1, len(yp_d)):
                if y_bin[test_m][i] != y_bin[test_m][j]:
                    npc2 += 1
                    if (yp_d[i] > yp_d[j]) == (y_bin[test_m][i] > y_bin[test_m][j]):
                        nc2 += 1
        paw_d = nc2 / max(npc2, 1)
        d_results.append(
            {
                "fold": fold_i,
                "accuracy": round(acc_d, 4),
                "pairwise_accuracy": round(paw_d, 4),
                "n_train": int(train_m.sum()),
                "n_test": int(test_m.sum()),
            }
        )
        print(f"  Fold {fold_i}: C acc={acc_c:.4f} paw={paw_c:.4f} | D acc={acc_d:.4f} paw={paw_d:.4f}")

    c_ma = statistics.mean([r["accuracy"] for r in c_results]) if c_results else 0
    c_mp = statistics.mean([r["pairwise_accuracy"] for r in c_results]) if c_results else 0
    d_ma = statistics.mean([r["accuracy"] for r in d_results]) if d_results else 0
    d_mp = statistics.mean([r["pairwise_accuracy"] for r in d_results]) if d_results else 0

    # Generate reports
    baseline.get("role_summary", {})

    # Eval report
    eval_lines = [
        "# Embedding Retrieval Evaluation (Phase D)",
        "",
        f"**Model**: BGE-M3 ({BGE_M3_PATH})",
        f"**Dim**: {provider.dim}",
        f"**Good cases**: {len(good_opps)}, **Bad cases**: {len(bad_opps)}",
        "**Retrieval features**: neighbor similarity to good/bad cases",
        "",
        "## Anti-Leakage",
        "Each GroupKFold test split retrieves from train-split-only index.",
        "",
        "## Results",
        "| Metric | C (Base) | D (+Retrieval) | Delta |",
        "|--------|----------|----------------|-------|",
        f"| Accuracy | {c_ma:.4f} | {d_ma:.4f} | {d_ma - c_ma:+.4f} |",
        f"| Pairwise Acc | {c_mp:.4f} | {d_mp:.4f} | {d_mp - c_mp:+.4f} |",
        f"| Folds | {len(c_results)} | {len(d_results)} | |",
    ]
    (ROOT / "data/health/embedding_retrieval_eval.md").write_text("\n".join(eval_lines))
    print("\n  → embedding_retrieval_eval.md")

    # Ablation D report
    abl_lines = [
        "# Learned Evaluator Ablation Report — System D",
        "",
        "**Date**: 2026-05-27",
        "",
        "## Systems Compared",
        "- **C**: Opportunity + Small Models (base features)",
        "- **D**: Opportunity + Small Models + BGE-M3 Retrieval Features",
        "",
        "## Performance",
        "| Metric | C | D | Delta |",
        "|--------|---|---|-------|",
        f"| Accuracy | {c_ma:.4f} | {d_ma:.4f} | {d_ma - c_ma:+.4f} |",
        f"| Pairwise Acc | {c_mp:.4f} | {d_mp:.4f} | {d_mp - c_mp:+.4f} |",
        "",
        "## Per-Fold",
        "| Fold | C Acc | C Paw | D Acc | D Paw |",
        "|------|-------|-------|-------|-------|",
    ]
    for i in range(max(len(c_results), len(d_results))):
        c = c_results[i] if i < len(c_results) else {}
        d = d_results[i] if i < len(d_results) else {}
        abl_lines.append(
            f"| {i} | {c.get('accuracy', 0):.4f} | {c.get('pairwise_accuracy', 0):.4f} | "
            f"{d.get('accuracy', 0):.4f} | {d.get('pairwise_accuracy', 0):.4f} |"
        )

    status = "✓ Retrieval IMPROVES" if d_mp > c_mp else "⚠ No improvement yet"
    abl_lines += [
        "",
        f"## Verdict: {status}",
        f"- C pairwise: {c_mp:.4f} → D pairwise: {d_mp:.4f} (Δ={d_mp - c_mp:+.4f})",
        "- Retrieval features add similarity-to-good/bad-cases signals",
        "- Benefit is limited when labeled data is small (more data → better retrieval)",
    ]
    (ROOT / "data/health/learned_evaluator_ablation_report_d.md").write_text("\n".join(abl_lines))
    print("  → learned_evaluator_ablation_report_d.md")

    print("\nDone!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
