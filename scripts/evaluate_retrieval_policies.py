#!/usr/bin/env python3
"""Offline Retrieval Policy Evaluation — compare 6 policies on a fixed query set.

Usage:
    python scripts/evaluate_retrieval_policies.py
    python scripts/evaluate_retrieval_policies.py --judge llm
    python scripts/evaluate_retrieval_policies.py --output /tmp/eval

Output:
    outputs/retrieval_policy_eval/results.json  — raw metrics per policy
    outputs/retrieval_policy_eval/results.csv   — CSV for spreadsheet
    outputs/retrieval_policy_eval/summary.md    — human-readable comparison
    outputs/retrieval_policy_eval/per_query_details.jsonl — per-query trace
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from collections import Counter
from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import Dict
from typing import List
from typing import Tuple

import numpy as np

logger = logging.getLogger(__name__)

# ================================================================
# Query Set — covers 6 roles × 5+ scenarios × 4 MBTI types
# ================================================================

QUERY_SET: List[Dict[str, Any]] = [
    # === Werewolf scenarios ===
    {
        "query_id": "q_wolf_01",
        "keywords": ["被查杀", "表水"],
        "role": "Werewolf",
        "alignment": "wolf",
        "mbti": "INTJ",
        "phase": "DAY_SPEECH",
        "action_type": "talk",
        "situation": "被真预言家查杀，白天需要表水解释",
        "min_relevant_role": "werewolf",
    },
    {
        "query_id": "q_wolf_02",
        "keywords": ["悍跳预言家", "警徽流"],
        "role": "Werewolf",
        "alignment": "wolf",
        "mbti": "INTJ",
        "phase": "DAY_BADGE_SPEECH",
        "action_type": "talk",
        "situation": "狼人需要悍跳预言家抢警徽",
        "min_relevant_role": "werewolf",
    },
    {
        "query_id": "q_wolf_03",
        "keywords": ["刀人", "击杀", "目标"],
        "role": "Werewolf",
        "alignment": "wolf",
        "mbti": "ENFP",
        "phase": "NIGHT_WOLF_ACTION",
        "action_type": "attack",
        "situation": "狼队夜晚需要选择击杀目标",
        "min_relevant_role": "werewolf",
    },
    {
        "query_id": "q_wolf_04",
        "keywords": ["倒钩", "深水", "潜伏"],
        "role": "Werewolf",
        "alignment": "wolf",
        "mbti": "ESFP",
        "phase": "DAY_SPEECH",
        "action_type": "talk",
        "situation": "倒钩狼需要深水潜伏到最后",
        "min_relevant_role": "werewolf",
    },
    {
        "query_id": "q_wolf_05",
        "keywords": ["自爆", "时机"],
        "role": "Werewolf",
        "alignment": "wolf",
        "mbti": "ISTJ",
        "phase": "DAY_SPEECH",
        "action_type": "talk",
        "situation": "狼人被查杀考虑是否自爆",
        "min_relevant_role": "werewolf",
    },
    # === Seer scenarios ===
    {
        "query_id": "q_seer_01",
        "keywords": ["查验", "首夜", "验人"],
        "role": "Seer",
        "alignment": "village",
        "mbti": "INTJ",
        "phase": "NIGHT_SEER_ACTION",
        "action_type": "check",
        "situation": "预言家首夜需要选择查验目标",
        "min_relevant_role": "seer",
    },
    {
        "query_id": "q_seer_02",
        "keywords": ["警徽流", "验人", "跳身份"],
        "role": "Seer",
        "alignment": "village",
        "mbti": "INTJ",
        "phase": "DAY_BADGE_SPEECH",
        "action_type": "talk",
        "situation": "预言家起跳报查验争取警徽",
        "min_relevant_role": "seer",
    },
    {
        "query_id": "q_seer_03",
        "keywords": ["查杀", "日报", "跳预言家"],
        "role": "Seer",
        "alignment": "village",
        "mbti": "ENFP",
        "phase": "DAY_SPEECH",
        "action_type": "talk",
        "situation": "查验到狼人，需要决定是否立即跳身份",
        "min_relevant_role": "seer",
    },
    {
        "query_id": "q_seer_04",
        "keywords": ["悍跳", "对跳", "分辨"],
        "role": "Seer",
        "alignment": "village",
        "mbti": "ESFP",
        "phase": "DAY_SPEECH",
        "action_type": "talk",
        "situation": "面对悍跳狼对跳，需要分辨真假",
        "min_relevant_role": "seer",
    },
    {
        "query_id": "q_seer_05",
        "keywords": ["金水", "验证", "好人"],
        "role": "Seer",
        "alignment": "village",
        "mbti": "ISTJ",
        "phase": "DAY_SPEECH",
        "action_type": "talk",
        "situation": "查验结果为金水，如何发布信息",
        "min_relevant_role": "seer",
    },
    # === Witch scenarios ===
    {
        "query_id": "q_witch_01",
        "keywords": ["女巫", "解药", "救人"],
        "role": "Witch",
        "alignment": "village",
        "mbti": "INTJ",
        "phase": "NIGHT_WITCH_ACTION",
        "action_type": "save",
        "situation": "女巫首夜有玩家被刀，是否使用解药",
        "min_relevant_role": "witch",
    },
    {
        "query_id": "q_witch_02",
        "keywords": ["女巫", "毒药", "投毒"],
        "role": "Witch",
        "alignment": "village",
        "mbti": "INTJ",
        "phase": "NIGHT_WITCH_ACTION",
        "action_type": "save",
        "situation": "女巫怀疑某人是狼，考虑使用毒药",
        "min_relevant_role": "witch",
    },
    {
        "query_id": "q_witch_03",
        "keywords": ["双药", "用药", "决策"],
        "role": "Witch",
        "alignment": "village",
        "mbti": "ENFP",
        "phase": "NIGHT_WITCH_ACTION",
        "action_type": "save",
        "situation": "女巫双药齐全时的用药策略",
        "min_relevant_role": "witch",
    },
    {
        "query_id": "q_witch_04",
        "keywords": ["女巫跳身份", "报药水"],
        "role": "Witch",
        "alignment": "village",
        "mbti": "ESFP",
        "phase": "DAY_SPEECH",
        "action_type": "talk",
        "situation": "女巫用了解药后是否跳身份报银水",
        "min_relevant_role": "witch",
    },
    # === Hunter scenarios ===
    {
        "query_id": "q_hunter_01",
        "keywords": ["猎人", "开枪", "带人"],
        "role": "Hunter",
        "alignment": "village",
        "mbti": "INTJ",
        "phase": "HUNTER_SHOOT",
        "action_type": "shoot",
        "situation": "猎人被放逐，需要选择开枪目标",
        "min_relevant_role": "hunter",
    },
    {
        "query_id": "q_hunter_02",
        "keywords": ["猎人", "藏身份", "发言"],
        "role": "Hunter",
        "alignment": "village",
        "mbti": "ISTJ",
        "phase": "DAY_SPEECH",
        "action_type": "talk",
        "situation": "猎人白天如何隐藏身份避免被狼刀",
        "min_relevant_role": "hunter",
    },
    # === Guard scenarios ===
    {
        "query_id": "q_guard_01",
        "keywords": ["守卫", "守护", "目标"],
        "role": "Guard",
        "alignment": "village",
        "mbti": "INTJ",
        "phase": "NIGHT_GUARD_ACTION",
        "action_type": "guard",
        "situation": "守卫夜晚选择守护目标",
        "min_relevant_role": "guard",
    },
    {
        "query_id": "q_guard_02",
        "keywords": ["守卫", "连续", "同一人"],
        "role": "Guard",
        "alignment": "village",
        "mbti": "ENFP",
        "phase": "NIGHT_GUARD_ACTION",
        "action_type": "guard",
        "situation": "守卫是否可以连续守护同一人",
        "min_relevant_role": "guard",
    },
    # === Villager scenarios ===
    {
        "query_id": "q_vil_01",
        "keywords": ["投票", "归票", "放逐"],
        "role": "Villager",
        "alignment": "village",
        "mbti": "INTJ",
        "phase": "DAY_VOTE",
        "action_type": "vote",
        "situation": "白天投票阶段需要归票放逐嫌疑人",
        "min_relevant_role": "villager",
    },
    {
        "query_id": "q_vil_02",
        "keywords": ["表水", "自证", "解释"],
        "role": "Villager",
        "alignment": "village",
        "mbti": "INTJ",
        "phase": "DAY_SPEECH",
        "action_type": "talk",
        "situation": "平民被怀疑是狼人，需要表水自证",
        "min_relevant_role": "villager",
    },
    {
        "query_id": "q_vil_03",
        "keywords": ["站边", "判断", "预言家"],
        "role": "Villager",
        "alignment": "village",
        "mbti": "ENFP",
        "phase": "DAY_SPEECH",
        "action_type": "talk",
        "situation": "多人对跳预言家，平民如何选择站边",
        "min_relevant_role": "villager",
    },
    {
        "query_id": "q_vil_04",
        "keywords": ["金水", "银水", "判断"],
        "role": "Villager",
        "alignment": "village",
        "mbti": "ESFP",
        "phase": "DAY_SPEECH",
        "action_type": "talk",
        "situation": "如何判断金水和银水的可信度",
        "min_relevant_role": "villager",
    },
    {
        "query_id": "q_vil_05",
        "keywords": ["发言", "分析", "逻辑"],
        "role": "Villager",
        "alignment": "village",
        "mbti": "ISTJ",
        "phase": "DAY_SPEECH",
        "action_type": "talk",
        "situation": "平民如何进行有效的发言和分析",
        "min_relevant_role": "villager",
    },
    # === Cross-role scenarios ===
    {
        "query_id": "q_cross_01",
        "keywords": ["警徽流", "警长"],
        "role": "Villager",
        "alignment": "village",
        "mbti": "INTJ",
        "phase": "DAY_BADGE_SPEECH",
        "action_type": "talk",
        "situation": "如何判断警长候选人的警徽流是否合理",
        "min_relevant_role": "any",
    },
    {
        "query_id": "q_cross_02",
        "keywords": ["轮次", "计算", "胜负"],
        "role": "Werewolf",
        "alignment": "wolf",
        "mbti": "INTJ",
        "phase": "DAY_SPEECH",
        "action_type": "talk",
        "situation": "狼队如何计算轮次和胜负手",
        "min_relevant_role": "werewolf",
    },
    {
        "query_id": "q_cross_03",
        "keywords": ["悍跳", "反跳", "打格式"],
        "role": "Werewolf",
        "alignment": "wolf",
        "mbti": "ENFP",
        "phase": "DAY_SPEECH",
        "action_type": "talk",
        "situation": "悍跳狼如何对抗真预言家的查验格式",
        "min_relevant_role": "werewolf",
    },
]

# ================================================================
# Relevance Scoring
# ================================================================


def weak_label_relevance(doc: Dict, query: Dict) -> Tuple[int, Dict]:
    """Auto-label relevance using rule-based heuristics.

    Returns (score 0-3, reason_dict).
    """
    score = 0
    reasons = {}

    doc_role = str(doc.get("role", "")).lower().strip()
    doc_phase = str(doc.get("phase", "")).lower().strip()
    str(doc.get("doc_type", "")).lower().strip()
    quality = float(doc.get("quality", doc.get("quality_score", 0.0)))
    strategy = str(doc.get("strategy", doc.get("recommended_action", ""))).lower()
    situation = str(doc.get("situation", "")).lower()

    # Role match
    q_role = query.get("role", "").lower().strip()
    q_min_role = query.get("min_relevant_role", "").lower().strip()
    if doc_role == q_role:
        score += 1
        reasons["role_match"] = 1
    elif doc_role == "global" or doc_role == q_min_role:
        score += 0.5
        reasons["role_match"] = 0.5
    else:
        reasons["role_match"] = 0

    # Phase match
    q_phase = query.get("phase", "").lower().strip()
    if doc_phase == q_phase:
        score += 0.5
        reasons["phase_match"] = 1
    elif doc_phase == "global":
        score += 0.25
        reasons["phase_match"] = 0.5
    else:
        reasons["phase_match"] = 0

    # Actionability (has specific advice)
    if strategy and len(strategy) >= 20:
        score += 0.5
        reasons["actionability"] = 1
    else:
        reasons["actionability"] = 0

    # Quality bonus
    if quality >= 0.80:
        score += 0.5
        reasons["quality"] = 1
    else:
        reasons["quality"] = 0.5

    # Keyword overlap in situation/strategy
    kw_overlap = sum(1 for kw in query.get("keywords", []) if kw in situation or kw in strategy)
    if kw_overlap >= 2:
        score += 0.5
        reasons["keyword_match"] = 1
    elif kw_overlap >= 1:
        score += 0.25
        reasons["keyword_match"] = 0.5
    else:
        reasons["keyword_match"] = 0

    # MBTI fit (docs with persona_scope matching agent's MBTI get bonus)
    doc_mbti = str(doc.get("mbti_scope", "")).upper().strip()
    q_mbti = query.get("mbti", "").upper().strip()
    if doc_mbti and q_mbti and doc_mbti == q_mbti:
        score += 0.25
        reasons["mbti_fit"] = 1
    else:
        reasons["mbti_fit"] = 0

    # Map to 0-3
    if score >= 2.5:
        relevance = 3
        label = "highly_relevant"
    elif score >= 1.5:
        relevance = 2
        label = "relevant"
    elif score >= 0.5:
        relevance = 1
        label = "partially_relevant"
    else:
        relevance = 0
        label = "irrelevant"

    reasons["relevance"] = relevance
    reasons["label"] = label
    reasons["raw_score"] = round(score, 2)
    return relevance, reasons


# ================================================================
# Evaluation Metrics
# ================================================================


@dataclass
class PolicyMetrics:
    policy: str
    n_queries: int = 0
    n_empty: int = 0
    precision_at_1: float = 0.0
    precision_at_3: float = 0.0
    precision_at_5: float = 0.0
    recall_at_3: float = 0.0
    recall_at_5: float = 0.0
    mrr: float = 0.0
    ndcg_at_3: float = 0.0
    ndcg_at_5: float = 0.0
    avg_relevance: float = 0.0
    role_match_rate: float = 0.0
    mbti_match_rate: float = 0.0
    phase_match_rate: float = 0.0
    coverage_rate: float = 0.0
    candidate_leakage_count: int = 0
    latency_p50_ms: float = 0.0
    latency_p95_ms: float = 0.0
    diversity_score: float = 0.0
    avg_results_per_query: float = 0.0
    top5_fill_rate: float = 0.0
    bucket_distribution: Dict[str, float] = field(default_factory=dict)


_EXACT_ROLE_MBTI_BUCKETS = {
    "same_role_same_mbti",
    "same_role_same_mbti_same_phase",
}
_ROLE_BUCKETS = _EXACT_ROLE_MBTI_BUCKETS | {"same_role_all_mbti"}
_ALIGNMENT_BUCKETS = {"same_alignment_all_mbti"}
_GLOBAL_BUCKETS = {"global"}


def _bucket_share(m: PolicyMetrics, bucket_names: set[str]) -> float:
    return sum(float(m.bucket_distribution.get(name, 0.0)) for name in bucket_names)


def _format_bucket_distribution(m: PolicyMetrics) -> str:
    if not m.bucket_distribution:
        return ""
    return ";".join(f"{name}:{share:.2f}" for name, share in sorted(m.bucket_distribution.items()))


def dcg_at_k(scores: List[int], k: int) -> float:
    """Discounted Cumulative Gain at K."""
    scores = scores[:k]
    if not scores:
        return 0.0
    return sum(s / np.log2(i + 2) for i, s in enumerate(scores))


def ndcg_at_k(scores: List[int], k: int) -> float:
    """Normalized DCG at K."""
    dcg = dcg_at_k(scores, k)
    ideal = dcg_at_k(sorted(scores, reverse=True), k)
    return dcg / ideal if ideal > 0 else 0.0


def compute_metrics(
    policy_name: str,
    all_results: List[Dict],
    latencies: List[float],
) -> PolicyMetrics:
    """Compute all evaluation metrics from per-query results."""
    metrics = PolicyMetrics(policy=policy_name)
    metrics.n_queries = len(all_results)

    prec_1_list: List[float] = []
    prec_3_list: List[float] = []
    prec_5_list: List[float] = []
    recall_3_list: List[float] = []
    recall_5_list: List[float] = []
    mrr_list: List[float] = []
    ndcg3_list: List[float] = []
    ndcg5_list: List[float] = []
    rel_list: List[float] = []
    role_match_list: List[float] = []
    mbti_match_list: List[float] = []
    phase_match_list: List[float] = []
    coverage_count = 0
    empty_count = 0
    candidate_leak = 0
    all_doc_ids: List[str] = []
    bucket_counts: Counter[str] = Counter()
    bucket_total = 0

    for result in all_results:
        hits = result.get("results", [])
        rel_scores = result.get("relevance_scores", [])
        n = len(hits)

        if n == 0 or not hits:
            empty_count += 1
            prec_1_list.append(0.0)
            prec_3_list.append(0.0)
            prec_5_list.append(0.0)
            recall_3_list.append(0.0)
            recall_5_list.append(0.0)
            mrr_list.append(0.0)
            ndcg3_list.append(0.0)
            ndcg5_list.append(0.0)
            rel_list.append(0.0)
            role_match_list.append(0.0)
            mbti_match_list.append(0.0)
            phase_match_list.append(0.0)
            continue

        coverage_count += 1
        query_role = result.get("query", {}).get("role", "").lower().strip()
        query_mbti = result.get("query", {}).get("mbti", "").upper().strip()

        # Precision@K (relevance >= 2 counts as hit)
        p1 = 1.0 if (len(rel_scores) >= 1 and rel_scores[0] >= 2) else 0.0
        p3 = sum(1 for r in rel_scores[:3] if r >= 2) / min(3, len(rel_scores))
        p5 = sum(1 for r in rel_scores[:5] if r >= 2) / min(5, len(rel_scores))
        prec_1_list.append(p1)
        prec_3_list.append(p3)
        prec_5_list.append(p5)

        # Recall@K (at least one relevant in top K)
        r3 = 1.0 if any(r >= 2 for r in rel_scores[:3]) else 0.0
        r5 = 1.0 if any(r >= 2 for r in rel_scores[:5]) else 0.0
        recall_3_list.append(r3)
        recall_5_list.append(r5)

        # MRR
        mrr_val = 0.0
        for rank, r in enumerate(rel_scores, 1):
            if r >= 2:
                mrr_val = 1.0 / rank
                break
        mrr_list.append(mrr_val)

        # nDCG
        ndcg3_list.append(ndcg_at_k(rel_scores, 3))
        ndcg5_list.append(ndcg_at_k(rel_scores, 5))

        # Average relevance
        avg_rel = sum(rel_scores) / max(len(rel_scores), 1)
        rel_list.append(avg_rel)

        # Role match rate
        role_matches = [
            1.0
            if str(h.get("role_scope", h.get("role", ""))).lower().strip() in (query_role, "global", "any", "")
            else 0.0
            for h in hits[:5]
        ]
        role_match_list.append(sum(role_matches) / max(len(role_matches), 1))

        # MBTI match rate
        mbti_matches = [
            1.0 if str(h.get("mbti_scope", "")).upper().strip() in (query_mbti, "") else 0.0 for h in hits[:5]
        ]
        mbti_match_list.append(sum(mbti_matches) / max(len(mbti_matches), 1))

        # Phase match rate
        query_phase = result.get("query", {}).get("phase", "").lower().strip()
        phase_matches = [
            1.0 if str(h.get("phase_scope", h.get("phase", ""))).lower().strip() in (query_phase, "", "global") else 0.0
            for h in hits[:5]
        ]
        phase_match_list.append(sum(phase_matches) / max(len(phase_matches), 1))

        # Candidate leakage
        for h in hits:
            status = str(h.get("status", h.get("doc_type", ""))).lower().strip()
            if status in ("candidate",):
                candidate_leak += 1

        # Retrieval bucket path distribution. This quantifies how often a
        # single-role query is satisfied by the exact role/MBTI bucket, role
        # fallback bucket, alignment fallback bucket, or global bucket.
        for h in hits[:5]:
            bucket_name = str(h.get("bucket", "") or "unknown")
            bucket_counts[bucket_name] += 1
            bucket_total += 1

        # Collect doc IDs for diversity
        all_doc_ids.extend(h.get("doc_id", "") for h in hits[:5])

    m = metrics
    m.n_empty = empty_count
    m.precision_at_1 = float(np.mean(prec_1_list)) if prec_1_list else 0.0
    m.precision_at_3 = float(np.mean(prec_3_list)) if prec_3_list else 0.0
    m.precision_at_5 = float(np.mean(prec_5_list)) if prec_5_list else 0.0
    m.recall_at_3 = float(np.mean(recall_3_list)) if recall_3_list else 0.0
    m.recall_at_5 = float(np.mean(recall_5_list)) if recall_5_list else 0.0
    m.mrr = float(np.mean(mrr_list)) if mrr_list else 0.0
    m.ndcg_at_3 = float(np.mean(ndcg3_list)) if ndcg3_list else 0.0
    m.ndcg_at_5 = float(np.mean(ndcg5_list)) if ndcg5_list else 0.0
    m.avg_relevance = float(np.mean(rel_list)) if rel_list else 0.0
    m.role_match_rate = float(np.mean(role_match_list)) if role_match_list else 0.0
    m.mbti_match_rate = float(np.mean(mbti_match_list)) if mbti_match_list else 0.0
    m.phase_match_rate = float(np.mean(phase_match_list)) if phase_match_list else 0.0
    m.coverage_rate = coverage_count / max(m.n_queries, 1)
    m.candidate_leakage_count = candidate_leak
    m.diversity_score = len(set(all_doc_ids)) / max(len(all_doc_ids), 1) if all_doc_ids else 0.0
    m.avg_results_per_query = bucket_total / max(m.n_queries, 1)
    m.top5_fill_rate = bucket_total / max(m.n_queries * 5, 1)
    m.bucket_distribution = (
        {name: count / bucket_total for name, count in sorted(bucket_counts.items())} if bucket_total else {}
    )

    if latencies:
        lat_sorted = sorted(latencies)
        m.latency_p50_ms = float(np.percentile(lat_sorted, 50)) if len(lat_sorted) > 1 else lat_sorted[0]
        m.latency_p95_ms = float(np.percentile(lat_sorted, 95)) if len(lat_sorted) > 1 else lat_sorted[0]

    return m


def compute_offline_score(m: PolicyMetrics) -> float:
    """Composite offline score for policy ranking.

    Weights: nDCG@5 > P@3 > Coverage > AvgRelevance > RoleMatch > MBTIMatch
    """
    candidate_penalty = -1.0 if m.candidate_leakage_count > 0 else 0.0
    coverage_penalty = -0.5 if m.coverage_rate < 0.80 else 0.0
    return (
        0.30 * m.ndcg_at_5
        + 0.20 * m.precision_at_3
        + 0.15 * m.coverage_rate
        + 0.15 * m.avg_relevance / 3.0
        + 0.10 * m.role_match_rate
        + 0.05 * m.mbti_match_rate
        + candidate_penalty
        + coverage_penalty
    )


def build_effect_summary(
    metrics: Dict[str, PolicyMetrics],
    scores: Dict[str, float],
    *,
    baseline_policy: str = "global_only",
) -> Dict[str, Any]:
    """Build policy effects relative to a stable baseline policy."""
    if baseline_policy not in metrics and metrics:
        baseline_policy = sorted(metrics)[0]
    baseline = metrics.get(baseline_policy)
    baseline_score = scores.get(baseline_policy, 0.0)
    effects: Dict[str, Any] = {}
    for policy_name, metric in metrics.items():
        effects[policy_name] = {
            "baseline_policy": baseline_policy,
            "score": round(scores.get(policy_name, 0.0), 4),
            "score_delta": round(scores.get(policy_name, 0.0) - baseline_score, 4),
            "precision_at_3": round(metric.precision_at_3, 4),
            "precision_at_3_delta": round(metric.precision_at_3 - (baseline.precision_at_3 if baseline else 0.0), 4),
            "ndcg_at_5": round(metric.ndcg_at_5, 4),
            "ndcg_at_5_delta": round(metric.ndcg_at_5 - (baseline.ndcg_at_5 if baseline else 0.0), 4),
            "coverage_rate": round(metric.coverage_rate, 4),
            "coverage_rate_delta": round(metric.coverage_rate - (baseline.coverage_rate if baseline else 0.0), 4),
            "avg_relevance": round(metric.avg_relevance, 4),
            "avg_relevance_delta": round(metric.avg_relevance - (baseline.avg_relevance if baseline else 0.0), 4),
            "n_empty": metric.n_empty,
        }
    return {
        "baseline_policy": baseline_policy,
        "best_by_score": max(scores.items(), key=lambda item: item[1])[0] if scores else "",
        "effects": effects,
    }


def metrics_to_dict(m: PolicyMetrics, *, offline_score: float | None = None) -> Dict[str, Any]:
    """Serialize metrics for JSON reports.

    Effective@1 means the first retrieved strategy is relevant. Effective@3/5
    means at least one relevant strategy appears in the top K. These aliases
    make the product report easier to read while preserving the standard IR
    names already computed by the script.
    """
    data: Dict[str, Any] = {
        "policy": m.policy,
        "n_queries": m.n_queries,
        "n_empty": m.n_empty,
        "precision_at_1": round(m.precision_at_1, 4),
        "precision_at_3": round(m.precision_at_3, 4),
        "precision_at_5": round(m.precision_at_5, 4),
        "recall_at_3": round(m.recall_at_3, 4),
        "recall_at_5": round(m.recall_at_5, 4),
        "effective_at_1": round(m.precision_at_1, 4),
        "effective_at_3": round(m.recall_at_3, 4),
        "effective_at_5": round(m.recall_at_5, 4),
        "mrr": round(m.mrr, 4),
        "ndcg_at_3": round(m.ndcg_at_3, 4),
        "ndcg_at_5": round(m.ndcg_at_5, 4),
        "avg_relevance": round(m.avg_relevance, 4),
        "role_match_rate": round(m.role_match_rate, 4),
        "mbti_match_rate": round(m.mbti_match_rate, 4),
        "phase_match_rate": round(m.phase_match_rate, 4),
        "coverage_rate": round(m.coverage_rate, 4),
        "candidate_leakage_count": m.candidate_leakage_count,
        "diversity_score": round(m.diversity_score, 4),
        "avg_results_per_query": round(m.avg_results_per_query, 4),
        "top5_fill_rate": round(m.top5_fill_rate, 4),
        "bucket_distribution": {name: round(share, 4) for name, share in m.bucket_distribution.items()},
        "exact_role_mbti_bucket_share": round(_bucket_share(m, _EXACT_ROLE_MBTI_BUCKETS), 4),
        "role_bucket_share": round(_bucket_share(m, _ROLE_BUCKETS), 4),
        "alignment_bucket_share": round(_bucket_share(m, _ALIGNMENT_BUCKETS), 4),
        "global_bucket_share": round(_bucket_share(m, _GLOBAL_BUCKETS), 4),
        "latency_p50_ms": round(m.latency_p50_ms, 2),
        "latency_p95_ms": round(m.latency_p95_ms, 2),
    }
    if offline_score is not None:
        data["offline_score"] = round(offline_score, 4)
    return data


def _norm_role(value: Any) -> str:
    return str(value or "").lower().strip()


def _norm_mbti(value: Any) -> str:
    return str(value or "").upper().strip()


def _avg(values: List[int]) -> float:
    return sum(values) / max(len(values), 1)


def build_role_corpus_stats(docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Quantify the corpus available to each single-role retrieval path.

    The retrieval metrics say what was returned for the fixed query set. This
    corpus view explains why: it counts how many active docs are available in
    the exact role+MBTI pool, the role-generic fallback pool, and the global
    fallback pool before keyword matching and ranking.
    """
    roles = sorted({q["role"] for q in QUERY_SET})
    cross_mbti_fill = os.getenv("TRACK_C_ALLOW_CROSS_MBTI_ROLE_FILL", "").lower() in {"1", "true", "yes", "on"}
    global_generic_docs = [
        d
        for d in docs
        if _norm_role(d.get("role_scope") or d.get("role")) in {"", "any", "global"}
        and not _norm_mbti(d.get("mbti_scope"))
    ]
    rows: List[Dict[str, Any]] = []

    for role in roles:
        role_key = _norm_role(role)
        role_queries = [q for q in QUERY_SET if q["role"] == role]
        role_docs = [d for d in docs if _norm_role(d.get("role_scope") or d.get("role")) == role_key]
        role_generic_docs = [d for d in role_docs if not _norm_mbti(d.get("mbti_scope"))]
        role_mbti_docs = [d for d in role_docs if _norm_mbti(d.get("mbti_scope"))]
        doc_mbti_counts: Counter[str] = Counter(_norm_mbti(d.get("mbti_scope")) for d in role_mbti_docs)

        exact_pool_counts: List[int] = []
        default_role_pool_counts: List[int] = []
        default_total_pool_counts: List[int] = []
        for query in role_queries:
            query_mbti = _norm_mbti(query.get("mbti"))
            exact_docs = [d for d in role_docs if _norm_mbti(d.get("mbti_scope")) == query_mbti]
            if cross_mbti_fill:
                default_role_docs = list(role_docs)
            else:
                default_role_docs = [
                    d
                    for d in role_docs
                    if not _norm_mbti(d.get("mbti_scope")) or _norm_mbti(d.get("mbti_scope")) == query_mbti
                ]
            exact_pool_counts.append(len(exact_docs))
            default_role_pool_counts.append(len(default_role_docs))
            default_total_pool_counts.append(len(default_role_docs) + len(global_generic_docs))

        rows.append(
            {
                "role": role,
                "queries": len(role_queries),
                "role_scope_docs": len(role_docs),
                "role_generic_docs": len(role_generic_docs),
                "role_mbti_specific_docs": len(role_mbti_docs),
                "distinct_doc_mbtis": ";".join(sorted(doc_mbti_counts)) or "",
                "doc_mbti_distribution": ";".join(f"{k}:{v}" for k, v in sorted(doc_mbti_counts.items())) or "",
                "evaluated_mbtis": ";".join(sorted({_norm_mbti(q.get("mbti")) for q in role_queries})) or "",
                "exact_role_mbti_pool_avg": round(_avg(exact_pool_counts), 2),
                "exact_role_mbti_pool_min": min(exact_pool_counts) if exact_pool_counts else 0,
                "exact_role_mbti_pool_max": max(exact_pool_counts) if exact_pool_counts else 0,
                "exact_role_mbti_empty_queries": sum(1 for n in exact_pool_counts if n == 0),
                "hybrid_default_role_pool_avg": round(_avg(default_role_pool_counts), 2),
                "hybrid_default_role_pool_min": min(default_role_pool_counts) if default_role_pool_counts else 0,
                "hybrid_default_role_pool_max": max(default_role_pool_counts) if default_role_pool_counts else 0,
                "hybrid_default_total_pool_avg": round(_avg(default_total_pool_counts), 2),
                "global_generic_docs": len(global_generic_docs),
                "cross_mbti_role_fill_enabled": cross_mbti_fill,
            }
        )

    return rows


def build_per_role_metrics(
    policy_results: Dict[str, List[Dict]],
) -> Tuple[Dict[str, Dict[str, PolicyMetrics]], Dict[str, Dict[str, float]], Dict[str, Dict[str, Any]]]:
    """Aggregate policy metrics for each queried role."""
    roles = sorted({q["role"] for q in QUERY_SET})
    per_role_metrics: Dict[str, Dict[str, PolicyMetrics]] = {}
    per_role_scores: Dict[str, Dict[str, float]] = {}

    for policy_name, results in policy_results.items():
        per_role_metrics[policy_name] = {}
        per_role_scores[policy_name] = {}
        for role in roles:
            role_results = [r for r in results if r.get("query", {}).get("role") == role]
            role_latencies = [float(r.get("latency_ms", 0.0)) for r in role_results]
            metric = compute_metrics(policy_name, role_results, role_latencies)
            per_role_metrics[policy_name][role] = metric
            per_role_scores[policy_name][role] = compute_offline_score(metric)

    role_winners: Dict[str, Dict[str, Any]] = {}
    for role in roles:
        role_policy_scores = {p: role_scores[role] for p, role_scores in per_role_scores.items()}
        role_policy_metrics = {p: role_metrics[role] for p, role_metrics in per_role_metrics.items()}
        role_winners[role] = {
            "best_by_offline_score": max(role_policy_scores.items(), key=lambda item: item[1])[0],
            "best_by_precision_at_3": max(role_policy_metrics.items(), key=lambda item: item[1].precision_at_3)[0],
            "best_by_effective_at_3": max(role_policy_metrics.items(), key=lambda item: item[1].recall_at_3)[0],
            "best_by_ndcg_at_5": max(role_policy_metrics.items(), key=lambda item: item[1].ndcg_at_5)[0],
        }

    return per_role_metrics, per_role_scores, role_winners


# ================================================================
# Main Evaluation
# ================================================================


def run_evaluation(output_dir: str = "outputs/retrieval_policy_eval") -> Dict[str, Any]:
    """Run the full policy comparison evaluation."""
    print(
        f"Query set: {len(QUERY_SET)} queries "
        f"({len({q['role'] for q in QUERY_SET})} roles × "
        f"{len({q['mbti'] for q in QUERY_SET})} MBTI types)"
    )

    os.makedirs(output_dir, exist_ok=True)

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from backend.agents.cognitive.retrieval_prod import AgentContext
    from backend.agents.cognitive.retrieval_prod import RetrievalPolicy
    from backend.agents.cognitive.retrieval_prod import _derive_alignment_from_role
    from backend.agents.cognitive.retrieval_prod import get_retriever

    retriever = get_retriever()
    if retriever is None or not retriever.ready:
        print("ERROR: Retriever not available. Ensure PostgreSQL is accessible.")
        return {"error": "retriever_not_available"}

    print(f"Evaluating {len(QUERY_SET)} queries against {retriever.size} docs")
    print(f"Policy space: {[p.value for p in RetrievalPolicy]}")
    print()

    all_policy_metrics: Dict[str, PolicyMetrics] = {}
    all_policy_results: Dict[str, List[Dict]] = {}
    per_query_details: List[Dict] = []

    for policy in RetrievalPolicy:
        print(f"  {policy.value:35s} ...", end=" ", flush=True)
        results_for_policy: List[Dict] = []
        latencies: List[float] = []

        for query in QUERY_SET:
            ctx = AgentContext(
                player_id=f"eval_{query['query_id']}",
                role=query["role"],
                alignment=query.get("alignment", _derive_alignment_from_role(query["role"])),
                mbti=query.get("mbti", ""),
                phase=query["phase"],
                action_type=query.get("action_type", ""),
                keywords=query.get("keywords", []),
            )

            t0 = time.perf_counter()
            hits = retriever.search_with_keywords(
                query["keywords"],
                role=query["role"],
                phase=query["phase"],
                k=5,
                use_bm25_rerank=False,
                output_mode="content",
                retrieval_policy=policy,
                agent_context=ctx,
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000
            latencies.append(elapsed_ms)

            # Score relevance
            rel_scores = []
            for h in hits:
                rel, reason = weak_label_relevance(h, query)
                rel_scores.append(rel)
                h["_relevance"] = rel
                h["_relevance_reason"] = reason

            # Compute metrics for this query
            results_for_policy.append(
                {
                    "query_id": query["query_id"],
                    "query": query,
                    "results": hits,
                    "relevance_scores": rel_scores,
                    "latency_ms": elapsed_ms,
                }
            )

            per_query_details.append(
                {
                    "query_id": query["query_id"],
                    "policy": policy.value,
                    "role": query["role"],
                    "mbti": query["mbti"],
                    "n_results": len(hits),
                    "relevance_scores": rel_scores,
                    "doc_ids": [h.get("doc_id", "") for h in hits[:5]],
                    "buckets": [h.get("bucket", "") for h in hits[:5]],
                    "bucket_trace": hits[0].get("_bucket_trace", {}) if hits else {},
                }
            )

        m = compute_metrics(policy.value, results_for_policy, latencies)
        all_policy_metrics[policy.value] = m
        all_policy_results[policy.value] = results_for_policy

        # Quick status
        status = "✓" if m.candidate_leakage_count == 0 else "✗ LEAK"
        status += f" P@3={m.precision_at_3:.2f} nDCG5={m.ndcg_at_5:.2f} Cov={m.coverage_rate:.2f}"
        print(status)

    # ================================================================
    # Compute composite scores and ranking
    # ================================================================

    scores: Dict[str, float] = {}
    for pname, m in all_policy_metrics.items():
        scores[pname] = compute_offline_score(m)

    ranked = sorted(scores.items(), key=lambda x: -x[1])
    effect_summary = build_effect_summary(all_policy_metrics, scores)
    per_role_metrics, per_role_scores, role_winners = build_per_role_metrics(all_policy_results)
    role_corpus_stats = build_role_corpus_stats(retriever.get_docs())

    # ================================================================
    # Save results
    # ================================================================

    # JSON
    results_json = {
        "query_set_size": len(QUERY_SET),
        "retriever_size": retriever.size,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "ranked_policies": [{"policy": p, "offline_score": round(s, 4)} for p, s in ranked],
        "effect_summary": effect_summary,
        "metrics": {pname: metrics_to_dict(m, offline_score=scores[pname]) for pname, m in all_policy_metrics.items()},
        "per_role_winners": role_winners,
        "role_corpus_stats": role_corpus_stats,
        "per_role_metrics": {
            pname: {
                role: metrics_to_dict(metric, offline_score=per_role_scores[pname][role])
                for role, metric in role_metrics.items()
            }
            for pname, role_metrics in per_role_metrics.items()
        },
    }

    with open(os.path.join(output_dir, "results.json"), "w") as f:
        json.dump(results_json, f, ensure_ascii=False, indent=2)

    # CSV
    csv_headers = [
        "policy",
        "P@1",
        "P@3",
        "P@5",
        "R@3",
        "R@5",
        "Effective@1",
        "Effective@3",
        "Effective@5",
        "MRR",
        "nDCG@3",
        "nDCG@5",
        "AvgRel",
        "RoleMatch",
        "MBTIMatch",
        "PhaseMatch",
        "Coverage",
        "CandidateLeak",
        "Diversity",
        "AvgResultsPerQuery",
        "Top5FillRate",
        "ExactRoleMBTIBucketShare",
        "RoleBucketShare",
        "AlignmentBucketShare",
        "GlobalBucketShare",
        "BucketDistribution",
        "LatencyP50ms",
        "LatencyP95ms",
        "OfflineScore",
        "DeltaScoreVsBaseline",
        "DeltaP@3VsBaseline",
        "DeltaNDCG@5VsBaseline",
        "DeltaCoverageVsBaseline",
        "NEmpty",
    ]
    with open(os.path.join(output_dir, "results.csv"), "w") as f:
        f.write(",".join(csv_headers) + "\n")
        for pname, m in all_policy_metrics.items():
            row = [
                pname,
                f"{m.precision_at_1:.4f}",
                f"{m.precision_at_3:.4f}",
                f"{m.precision_at_5:.4f}",
                f"{m.recall_at_3:.4f}",
                f"{m.recall_at_5:.4f}",
                f"{m.precision_at_1:.4f}",
                f"{m.recall_at_3:.4f}",
                f"{m.recall_at_5:.4f}",
                f"{m.mrr:.4f}",
                f"{m.ndcg_at_3:.4f}",
                f"{m.ndcg_at_5:.4f}",
                f"{m.avg_relevance:.4f}",
                f"{m.role_match_rate:.4f}",
                f"{m.mbti_match_rate:.4f}",
                f"{m.phase_match_rate:.4f}",
                f"{m.coverage_rate:.4f}",
                str(m.candidate_leakage_count),
                f"{m.diversity_score:.4f}",
                f"{m.avg_results_per_query:.4f}",
                f"{m.top5_fill_rate:.4f}",
                f"{_bucket_share(m, _EXACT_ROLE_MBTI_BUCKETS):.4f}",
                f"{_bucket_share(m, _ROLE_BUCKETS):.4f}",
                f"{_bucket_share(m, _ALIGNMENT_BUCKETS):.4f}",
                f"{_bucket_share(m, _GLOBAL_BUCKETS):.4f}",
                _format_bucket_distribution(m),
                f"{m.latency_p50_ms:.2f}",
                f"{m.latency_p95_ms:.2f}",
                f"{scores[pname]:.4f}",
                f"{effect_summary['effects'][pname]['score_delta']:.4f}",
                f"{effect_summary['effects'][pname]['precision_at_3_delta']:.4f}",
                f"{effect_summary['effects'][pname]['ndcg_at_5_delta']:.4f}",
                f"{effect_summary['effects'][pname]['coverage_rate_delta']:.4f}",
                str(m.n_empty),
            ]
            f.write(",".join(row) + "\n")

    # Per-role CSV
    role_csv_headers = [
        "role",
        "policy",
        "queries",
        "P@1",
        "P@3",
        "Effective@3",
        "MRR",
        "nDCG@5",
        "AvgRel",
        "RoleMatch",
        "MBTIMatch",
        "PhaseMatch",
        "Coverage",
        "CandidateLeak",
        "AvgResultsPerQuery",
        "Top5FillRate",
        "ExactRoleMBTIBucketShare",
        "RoleBucketShare",
        "AlignmentBucketShare",
        "GlobalBucketShare",
        "BucketDistribution",
        "LatencyP95ms",
        "OfflineScore",
        "NEmpty",
    ]
    with open(os.path.join(output_dir, "per_role_results.csv"), "w") as f:
        f.write(",".join(role_csv_headers) + "\n")
        for role in sorted({q["role"] for q in QUERY_SET}):
            for policy_name, _score in ranked:
                m = per_role_metrics[policy_name][role]
                row = [
                    role,
                    policy_name,
                    str(m.n_queries),
                    f"{m.precision_at_1:.4f}",
                    f"{m.precision_at_3:.4f}",
                    f"{m.recall_at_3:.4f}",
                    f"{m.mrr:.4f}",
                    f"{m.ndcg_at_5:.4f}",
                    f"{m.avg_relevance:.4f}",
                    f"{m.role_match_rate:.4f}",
                    f"{m.mbti_match_rate:.4f}",
                    f"{m.phase_match_rate:.4f}",
                    f"{m.coverage_rate:.4f}",
                    str(m.candidate_leakage_count),
                    f"{m.avg_results_per_query:.4f}",
                    f"{m.top5_fill_rate:.4f}",
                    f"{_bucket_share(m, _EXACT_ROLE_MBTI_BUCKETS):.4f}",
                    f"{_bucket_share(m, _ROLE_BUCKETS):.4f}",
                    f"{_bucket_share(m, _ALIGNMENT_BUCKETS):.4f}",
                    f"{_bucket_share(m, _GLOBAL_BUCKETS):.4f}",
                    _format_bucket_distribution(m),
                    f"{m.latency_p95_ms:.2f}",
                    f"{per_role_scores[policy_name][role]:.4f}",
                    str(m.n_empty),
                ]
                f.write(",".join(row) + "\n")

    # Role corpus CSV
    corpus_csv_headers = [
        "role",
        "queries",
        "role_scope_docs",
        "role_generic_docs",
        "role_mbti_specific_docs",
        "distinct_doc_mbtis",
        "doc_mbti_distribution",
        "evaluated_mbtis",
        "exact_role_mbti_pool_avg",
        "exact_role_mbti_pool_min",
        "exact_role_mbti_pool_max",
        "exact_role_mbti_empty_queries",
        "hybrid_default_role_pool_avg",
        "hybrid_default_role_pool_min",
        "hybrid_default_role_pool_max",
        "hybrid_default_total_pool_avg",
        "global_generic_docs",
        "cross_mbti_role_fill_enabled",
    ]
    with open(os.path.join(output_dir, "role_corpus_stats.csv"), "w") as f:
        f.write(",".join(corpus_csv_headers) + "\n")
        for stats in role_corpus_stats:
            row = [str(stats.get(header, "")) for header in corpus_csv_headers]
            f.write(",".join(row) + "\n")

    # per-query details (JSONL)
    with open(os.path.join(output_dir, "per_query_details.jsonl"), "w") as f:
        for detail in per_query_details:
            f.write(json.dumps(detail, ensure_ascii=False) + "\n")

    # Markdown summary
    md = _build_markdown_summary(
        ranked,
        all_policy_metrics,
        scores,
        effect_summary,
        per_role_metrics,
        per_role_scores,
        role_winners,
        role_corpus_stats,
    )
    with open(os.path.join(output_dir, "summary.md"), "w") as f:
        f.write(md)

    print(f"\nResults saved to {output_dir}/")
    print(
        "  results.json, results.csv, per_role_results.csv, role_corpus_stats.csv, summary.md, per_query_details.jsonl"
    )
    print(f"\nTop policy: {ranked[0][0]} (score={ranked[0][1]:.4f})")
    print(f"Baseline policy: {effect_summary['baseline_policy']}")
    for policy_name, _score in ranked:
        effect = effect_summary["effects"][policy_name]
        print(
            f"  effect {policy_name:35s} "
            f"ΔScore={effect['score_delta']:+.4f} "
            f"ΔP@3={effect['precision_at_3_delta']:+.4f} "
            f"ΔnDCG@5={effect['ndcg_at_5_delta']:+.4f} "
            f"ΔCoverage={effect['coverage_rate_delta']:+.4f}"
        )

    return results_json


def _build_markdown_summary(
    ranked: List[Tuple[str, float]],
    metrics: Dict[str, PolicyMetrics],
    scores: Dict[str, float],
    effect_summary: Dict[str, Any],
    per_role_metrics: Dict[str, Dict[str, PolicyMetrics]],
    per_role_scores: Dict[str, Dict[str, float]],
    role_winners: Dict[str, Dict[str, Any]],
    role_corpus_stats: List[Dict[str, Any]],
) -> str:
    """Build a human-readable Markdown comparison report."""
    lines = [
        "# Retrieval Policy Evaluation Summary",
        "",
        f"**Query set**: {len(QUERY_SET)} queries covering 6 roles × 4 MBTI types",
        "**Relevance scoring**: Rule-based weak labeling (role + phase + keywords + actionability + MBTI fit)",
        "**Effective@1/3/5**: Effective@1 equals P@1; Effective@K means at least one relevant strategy appears in top K.",
        "",
        "## Policy Ranking (Offline Score)",
        "",
        f"Baseline for deltas: `{effect_summary['baseline_policy']}`",
        "",
        "| Rank | Policy | Score | ΔScore | P@3 | ΔP@3 | nDCG@5 | ΔnDCG@5 | Coverage | ΔCoverage | Leak |",
        "|------|--------|-------|--------|-----|------|--------|---------|----------|-----------|------|",
    ]

    for rank, (pname, score) in enumerate(ranked, 1):
        m = metrics[pname]
        effect = effect_summary["effects"][pname]
        lines.append(
            f"| {rank} | `{pname}` | {score:.4f} | {effect['score_delta']:+.4f} | "
            f"{m.precision_at_3:.2f} | {effect['precision_at_3_delta']:+.2f} | "
            f"{m.ndcg_at_5:.2f} | {effect['ndcg_at_5_delta']:+.2f} | "
            f"{m.coverage_rate:.2f} | {effect['coverage_rate_delta']:+.2f} | {m.candidate_leakage_count} |"
        )

    lines += [
        "",
        "## Single-Role Retrieval Winners",
        "",
        "| Role | Best Offline Score | Best P@3 | Best Effective@3 | Best nDCG@5 |",
        "|------|--------------------|----------|------------------|-------------|",
    ]

    for role in sorted(role_winners):
        winners = role_winners[role]
        lines.append(
            f"| {role} | `{winners['best_by_offline_score']}` | `{winners['best_by_precision_at_3']}` | "
            f"`{winners['best_by_effective_at_3']}` | `{winners['best_by_ndcg_at_5']}` |"
        )

    lines += [
        "",
        "## Single-Role Metrics by Policy",
        "",
        "| Role | Policy | Queries | P@1 | P@3 | Effective@3 | nDCG@5 | Coverage | RoleMatch | MBTIMatch | Empty | Score |",
        "|------|--------|---------|-----|-----|--------------|--------|----------|-----------|-----------|-------|-------|",
    ]

    for role in sorted(role_winners):
        for pname, _score in ranked:
            m = per_role_metrics[pname][role]
            lines.append(
                f"| {role} | `{pname}` | {m.n_queries} | {m.precision_at_1:.2f} | "
                f"{m.precision_at_3:.2f} | {m.recall_at_3:.2f} | {m.ndcg_at_5:.2f} | "
                f"{m.coverage_rate:.2f} | {m.role_match_rate:.2f} | {m.mbti_match_rate:.2f} | "
                f"{m.n_empty} | {per_role_scores[pname][role]:.4f} |"
            )

    lines += [
        "",
        "## Single-Role Retrieval Path",
        "",
        "Bucket share shows where top-5 retrieved docs came from. ExactRoleMBTI is the narrowest match; "
        "RoleBucket includes exact role/MBTI and same-role fallback; Alignment and Global are fallback layers.",
        "",
        "| Role | Policy | AvgResults | Top5Fill | ExactRoleMBTI | RoleBucket | AlignmentBucket | GlobalBucket | Empty | Bucket Distribution |",
        "|------|--------|------------|----------|---------------|------------|-----------------|--------------|-------|---------------------|",
    ]

    for role in sorted(role_winners):
        for pname, _score in ranked:
            m = per_role_metrics[pname][role]
            lines.append(
                f"| {role} | `{pname}` | {m.avg_results_per_query:.2f} | {m.top5_fill_rate:.2f} | "
                f"{_bucket_share(m, _EXACT_ROLE_MBTI_BUCKETS):.2f} | "
                f"{_bucket_share(m, _ROLE_BUCKETS):.2f} | {_bucket_share(m, _ALIGNMENT_BUCKETS):.2f} | "
                f"{_bucket_share(m, _GLOBAL_BUCKETS):.2f} | {m.n_empty} | {_format_bucket_distribution(m)} |"
            )

    lines += [
        "",
        "## Single-Role Corpus Pool",
        "",
        "This table quantifies the active knowledge pool available before keyword ranking. "
        "ExactRoleMBTIPool is the narrow role+MBTI pool used by `same_role_same_mbti`; "
        "HybridRolePool is the role-scoped pool available to the default hybrid policy "
        "after applying the current cross-MBTI setting.",
        "",
        "| Role | RoleDocs | RoleGeneric | RoleMBTISpecific | ExactRoleMBTIPoolAvg | ExactEmptyQueries | HybridRolePoolAvg | HybridTotalPoolAvg | GlobalGeneric | Doc MBTI Distribution |",
        "|------|----------|-------------|------------------|----------------------|-------------------|-------------------|--------------------|---------------|-----------------------|",
    ]

    for stats in role_corpus_stats:
        lines.append(
            f"| {stats['role']} | {stats['role_scope_docs']} | {stats['role_generic_docs']} | "
            f"{stats['role_mbti_specific_docs']} | {stats['exact_role_mbti_pool_avg']:.2f} | "
            f"{stats['exact_role_mbti_empty_queries']} | {stats['hybrid_default_role_pool_avg']:.2f} | "
            f"{stats['hybrid_default_total_pool_avg']:.2f} | {stats['global_generic_docs']} | "
            f"{stats['doc_mbti_distribution'] or '-'} |"
        )

    lines += [
        "",
        "## Policy Analysis",
        "",
    ]

    # Analysis per policy
    analyses = {
        "global_only": "**Baseline.** Highest coverage but no personalization. All docs treated equally. "
        "Best when knowledge base is small or MBTI data is sparse.",
        "self_mbti_only": "Only docs matching agent's MBTI. Expected: high precision but low coverage. "
        "Risk: empty results for rare MBTI types.",
        "same_role_all_mbti": "All docs for agent's role regardless of MBTI. "
        "Should balance role relevance with good coverage.",
        "same_role_same_mbti": "Most restrictive: same role AND same MBTI. "
        "Expected: highest relevance but sparsest coverage.",
        "hybrid_role_mbti_global": "**Recommended default.** 3-layer: same_role_same_mbti → same_role_all_mbti → global. "
        "Balances personalization with fallback coverage.",
        "hybrid_role_alignment_phase": "4-layer with phase constraint. Most granular. "
        "Expected: best for specific scenarios but lower coverage.",
    }

    for pname, _ in ranked:
        m = metrics[pname]
        analysis = analyses.get(pname, "")
        lines.append(f"### `{pname}`")
        lines.append(f"- Precision@3: {m.precision_at_3:.4f}")
        lines.append(f"- nDCG@5: {m.ndcg_at_5:.4f}")
        lines.append(f"- Coverage: {m.coverage_rate:.1%}")
        lines.append(f"- Role Match: {m.role_match_rate:.1%}")
        lines.append(f"- MBTI Match: {m.mbti_match_rate:.1%}")
        lines.append(f"- Empty Results: {m.n_empty}/{m.n_queries}")
        lines.append(f"- Top-5 Fill Rate: {m.top5_fill_rate:.1%}")
        lines.append(f"- Candidate Leak: {m.candidate_leakage_count}")
        lines.append(f"- {analysis}")
        lines.append("")

    # Hypotheses testing
    lines += [
        "## Hypothesis Testing",
        "",
        "| Hypothesis | Expected | Result |",
        "|-----------|----------|--------|",
    ]

    for label, policy_name, expected in [
        ("H1: SELF_MBTI sparse", "self_mbti_only", "low coverage, high precision"),
        ("H2: SAME_ROLE stable", "same_role_all_mbti", "high coverage, moderate precision"),
        ("H3: SAME_ROLE_MBTI sparse", "same_role_same_mbti", "very low coverage"),
        ("H4: HYBRID best default", "hybrid_role_mbti_global", "best balance"),
        ("H5: ALIGNMENT_PHASE too narrow", "hybrid_role_alignment_phase", "lower coverage than hybrid"),
    ]:
        m = metrics.get(policy_name)
        if m:
            lines.append(
                f"| {label} | {expected} | "
                f"P@3={m.precision_at_3:.2f}, Cov={m.coverage_rate:.2f}, "
                f"nDCG5={m.ndcg_at_5:.2f} |"
            )
        else:
            lines.append(f"| {label} | {expected} | N/A |")

    lines += [
        "",
        "## Recommendation",
        "",
        f"**Recommended default policy**: `{ranked[0][0]}` (offline_score={ranked[0][1]:.4f})",
        "",
        "---",
        "*Generated by scripts/evaluate_retrieval_policies.py*",
    ]

    return "\n".join(lines)


# ================================================================
# Entry Point
# ================================================================

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Evaluate retrieval policies offline")
    ap.add_argument("--output", default="outputs/retrieval_policy_eval", help="Output directory")
    ap.add_argument("--judge", default="weak", choices=["weak", "llm"], help="Relevance judge type")
    args = ap.parse_args()

    if args.judge == "llm":
        print("LLM judge not implemented yet. Using weak labeling.")
        print("To enable LLM judge, set ANTHROPIC_API_KEY and implement the judge call.")
        print()

    run_evaluation(output_dir=args.output)
