#!/usr/bin/env python3
"""Summarize single-role retrieval mechanics and metrics.

This script reads the reproducible retrieval evaluation artifacts and writes a
Chinese report focused on how a single role retrieves strategy knowledge.
It does not run LLM calls or mutate the database.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EVIDENCE_DIR = ROOT / "docs" / "evidence"
DEFAULT_INPUT_DIR = ROOT / "outputs" / "retrieval_effectiveness_current"
DEFAULT_REPORT = EVIDENCE_DIR / "PROJECT_ROLE_RETRIEVAL_QUANTIFICATION.md"
DEFAULT_FACTS = EVIDENCE_DIR / "PROJECT_ROLE_RETRIEVAL_FACTS.json"

DEFAULT_POLICY = "hybrid_role_mbti_global"
BASELINE_POLICY = "global_only"
EXACT_POLICY = "same_role_same_mbti"
POLICY_ORDER = [
    "global_only",
    "self_mbti_only",
    "same_role_all_mbti",
    "same_role_same_mbti",
    "hybrid_role_mbti_global",
    "hybrid_role_alignment_phase",
]


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def fnum(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def inum(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def fmt(value: Any, digits: int = 4) -> str:
    if value is None or value == "":
        return "n/a"
    return f"{fnum(value):.{digits}f}"


def pct(value: Any) -> str:
    return f"{fnum(value) * 100:.2f}%"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(lines)


def role_row(rows: list[dict[str, str]], role: str, policy: str) -> dict[str, str]:
    for row in rows:
        if row.get("role") == role and row.get("policy") == policy:
            return row
    return {}


def corpus_row(rows: list[dict[str, str]], role: str) -> dict[str, str]:
    for row in rows:
        if row.get("role") == role:
            return row
    return {}


def policy_metric_row(row: dict[str, str]) -> dict[str, Any]:
    return {
        "role": row.get("role", ""),
        "policy": row.get("policy", ""),
        "query_count": inum(row.get("queries")),
        "precision_at_3": fnum(row.get("P@3")),
        "effective_at_3": fnum(row.get("Effective@3")),
        "ndcg_at_5": fnum(row.get("nDCG@5")),
        "coverage": fnum(row.get("Coverage")),
        "top5_fill_rate": fnum(row.get("Top5FillRate")),
        "role_bucket_share": fnum(row.get("RoleBucketShare")),
        "global_bucket_share": fnum(row.get("GlobalBucketShare")),
        "exact_role_mbti_bucket_share": fnum(row.get("ExactRoleMBTIBucketShare")),
        "alignment_bucket_share": fnum(row.get("AlignmentBucketShare")),
        "offline_score": fnum(row.get("OfflineScore")),
        "empty_results": inum(row.get("NEmpty")),
        "bucket_distribution": row.get("BucketDistribution", ""),
    }


def diagnose_role(default_row: dict[str, str], exact_row: dict[str, str], corpus: dict[str, str]) -> str:
    effective = fnum(default_row.get("Effective@3"))
    precision = fnum(default_row.get("P@3"))
    exact_coverage = fnum(exact_row.get("Coverage"))
    mbti_docs = inum(corpus.get("role_mbti_specific_docs"))
    role_docs = inum(corpus.get("role_scope_docs"))

    if effective >= 1.0 and precision >= 0.4:
        return "当前默认检索命中充分；主要补强方向是扩充 role+MBTI 细分卡，减少对角色通用池的依赖。"
    if effective >= 0.5:
        return "当前默认检索覆盖稳定，但 Top-3 高相关密度不足；应补充该角色关键阶段/动作的高质量策略卡。"
    if role_docs < 25 or mbti_docs < 5:
        return "当前默认检索能返回结果，但角色语料池偏小；应优先补充角色通用卡和 MBTI 细分卡。"
    if exact_coverage < 0.5:
        return "当前默认检索依赖角色通用池；精确 role+MBTI 池过窄，需要按常见人格补足策略。"
    return "当前默认检索覆盖稳定但相关性偏低；需要优化查询集、策略文本和质量排序。"


def build_policy_summary(
    roles: list[str],
    per_role_rows: list[dict[str, str]],
    corpus_rows: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    comparison: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for role in roles:
        rows_for_role = [
            policy_metric_row(row) for policy in POLICY_ORDER for row in [role_row(per_role_rows, role, policy)] if row
        ]
        comparison.extend(rows_for_role)

        default_row = role_row(per_role_rows, role, DEFAULT_POLICY)
        baseline_row = role_row(per_role_rows, role, BASELINE_POLICY)
        same_role_row = role_row(per_role_rows, role, "same_role_all_mbti")
        exact_row = role_row(per_role_rows, role, EXACT_POLICY)
        phase_row = role_row(per_role_rows, role, "hybrid_role_alignment_phase")
        corpus = corpus_row(corpus_rows, role)
        best = max(rows_for_role, key=lambda row: row["offline_score"], default={})

        summaries.append(
            {
                "role": role,
                "query_count": inum(default_row.get("queries")),
                "best_policy_by_offline_score": best.get("policy", ""),
                "best_offline_score": best.get("offline_score", 0.0),
                "default_policy": DEFAULT_POLICY,
                "default_offline_score": fnum(default_row.get("OfflineScore")),
                "default_precision_at_3": fnum(default_row.get("P@3")),
                "default_effective_at_3": fnum(default_row.get("Effective@3")),
                "default_coverage": fnum(default_row.get("Coverage")),
                "default_exact_bucket_share": fnum(default_row.get("ExactRoleMBTIBucketShare")),
                "default_role_bucket_share": fnum(default_row.get("RoleBucketShare")),
                "default_global_bucket_share": fnum(default_row.get("GlobalBucketShare")),
                "global_only_effective_at_3": fnum(baseline_row.get("Effective@3")),
                "global_only_coverage": fnum(baseline_row.get("Coverage")),
                "same_role_all_mbti_effective_at_3": fnum(same_role_row.get("Effective@3")),
                "same_role_all_mbti_offline_score": fnum(same_role_row.get("OfflineScore")),
                "same_role_same_mbti_effective_at_3": fnum(exact_row.get("Effective@3")),
                "same_role_same_mbti_coverage": fnum(exact_row.get("Coverage")),
                "same_role_same_mbti_empty_results": inum(exact_row.get("NEmpty")),
                "hybrid_role_alignment_phase_effective_at_3": fnum(phase_row.get("Effective@3")),
                "default_minus_global_effective_at_3": fnum(default_row.get("Effective@3"))
                - fnum(baseline_row.get("Effective@3")),
                "default_minus_global_precision_at_3": fnum(default_row.get("P@3")) - fnum(baseline_row.get("P@3")),
                "default_minus_global_coverage": fnum(default_row.get("Coverage")) - fnum(baseline_row.get("Coverage")),
                "role_scope_docs": inum(corpus.get("role_scope_docs")),
                "role_generic_docs": inum(corpus.get("role_generic_docs")),
                "role_mbti_specific_docs": inum(corpus.get("role_mbti_specific_docs")),
                "diagnosis": diagnose_role(default_row, exact_row, corpus),
            }
        )
    return comparison, summaries


def build_role_summary(
    role: str,
    default_row: dict[str, str],
    exact_row: dict[str, str],
    corpus: dict[str, str],
) -> str:
    effective = fnum(default_row.get("Effective@3"))
    p3 = fnum(default_row.get("P@3"))
    exact_empty = inum(exact_row.get("NEmpty"))
    role_docs = inum(corpus.get("role_scope_docs"))
    role_generic = inum(corpus.get("role_generic_docs"))
    mbti_docs = inum(corpus.get("role_mbti_specific_docs"))

    if effective >= 1.0:
        prefix = "默认检索在该角色查询中均能命中可用策略"
    elif effective >= 0.5:
        prefix = "默认检索可以稳定返回本角色策略，但高相关命中仍需扩充"
    else:
        prefix = "默认检索可以覆盖该角色，但相关性仍是主要短板"

    if exact_empty > 0:
        suffix = f"精确 role+MBTI 检索有 {exact_empty} 个查询为空，主要原因是当前 MBTI 细分语料不足。"
    else:
        suffix = "精确 role+MBTI 检索未出现空结果，可作为该角色的个性化增强桶。"

    return (
        f"{prefix}；P@3={p3:.4f}，Effective@3={effective:.4f}。"
        f"当前角色语料 {role_docs} 条，其中角色通用 {role_generic} 条、MBTI 细分 {mbti_docs} 条。{suffix}"
    )


def build_evidence(input_dir: Path) -> dict[str, Any]:
    results = read_json(input_dir / "results.json")
    per_role_rows = read_csv(input_dir / "per_role_results.csv")
    corpus_rows = read_csv(input_dir / "role_corpus_stats.csv")

    metrics = results.get("metrics", {}) if isinstance(results, dict) else {}
    default_metrics = metrics.get(DEFAULT_POLICY, {})
    baseline_metrics = metrics.get(BASELINE_POLICY, {})
    exact_metrics = metrics.get(EXACT_POLICY, {})

    roles = sorted({row.get("role", "") for row in per_role_rows if row.get("role")})
    policy_comparison, policy_summaries = build_policy_summary(roles, per_role_rows, corpus_rows)
    role_summaries: list[dict[str, Any]] = []
    for role in roles:
        default_row = role_row(per_role_rows, role, DEFAULT_POLICY)
        baseline_row = role_row(per_role_rows, role, BASELINE_POLICY)
        exact_row = role_row(per_role_rows, role, EXACT_POLICY)
        corpus = corpus_row(corpus_rows, role)
        role_summaries.append(
            {
                "role": role,
                "query_count": inum(default_row.get("queries")),
                "default_policy": DEFAULT_POLICY,
                "default_precision_at_3": fnum(default_row.get("P@3")),
                "default_effective_at_3": fnum(default_row.get("Effective@3")),
                "default_ndcg_at_5": fnum(default_row.get("nDCG@5")),
                "default_coverage": fnum(default_row.get("Coverage")),
                "default_top5_fill_rate": fnum(default_row.get("Top5FillRate")),
                "default_role_bucket_share": fnum(default_row.get("RoleBucketShare")),
                "default_global_bucket_share": fnum(default_row.get("GlobalBucketShare")),
                "default_empty_results": inum(default_row.get("NEmpty")),
                "baseline_effective_at_3": fnum(baseline_row.get("Effective@3")),
                "baseline_coverage": fnum(baseline_row.get("Coverage")),
                "exact_policy_coverage": fnum(exact_row.get("Coverage")),
                "exact_policy_empty_results": inum(exact_row.get("NEmpty")),
                "role_scope_docs": inum(corpus.get("role_scope_docs")),
                "role_generic_docs": inum(corpus.get("role_generic_docs")),
                "role_mbti_specific_docs": inum(corpus.get("role_mbti_specific_docs")),
                "exact_role_mbti_pool_avg": fnum(corpus.get("exact_role_mbti_pool_avg")),
                "exact_role_mbti_empty_queries_before_keyword": inum(corpus.get("exact_role_mbti_empty_queries")),
                "hybrid_default_role_pool_avg": fnum(corpus.get("hybrid_default_role_pool_avg")),
                "hybrid_default_total_pool_avg": fnum(corpus.get("hybrid_default_total_pool_avg")),
                "global_generic_docs": inum(corpus.get("global_generic_docs")),
                "evaluated_mbtis": corpus.get("evaluated_mbtis", ""),
                "doc_mbti_distribution": corpus.get("doc_mbti_distribution", ""),
                "summary": build_role_summary(role, default_row, exact_row, corpus),
            }
        )

    return {
        "generated_at": now_iso(),
        "input_dir": str(input_dir.relative_to(ROOT)),
        "sources": {
            "results": str((input_dir / "results.json").relative_to(ROOT)),
            "per_role_results": str((input_dir / "per_role_results.csv").relative_to(ROOT)),
            "role_corpus_stats": str((input_dir / "role_corpus_stats.csv").relative_to(ROOT)),
            "per_query_details": str((input_dir / "per_query_details.jsonl").relative_to(ROOT)),
            "code_retriever": "backend/agents/cognitive/retrieval_prod.py",
            "code_tool": "backend/agents/cognitive/tools.py",
            "code_evaluation": "scripts/evaluate_retrieval_policies.py",
        },
        "metric_definitions": {
            "precision_at_3": "Top-3 检索结果中弱标注为相关或高相关的比例。",
            "effective_at_3": "Top-3 中至少有一条相关或高相关策略，作为实际可用命中率口径。",
            "coverage": "该查询是否返回至少一条策略。",
            "top5_fill_rate": "Top-5 位置被策略填满的比例。",
            "role_bucket_share": "Top-5 结果中来自 exact role+MBTI 或 same-role fallback 桶的比例。",
            "global_bucket_share": "Top-5 结果中来自 global fallback 桶的比例。",
        },
        "retrieval_pipeline": [
            {
                "step": 1,
                "name": "Agent 工具调用",
                "description": "CognitiveAgent / AgentLoop 在需要策略辅助时调用 search_strategies，并带入角色、MBTI、阵营、阶段、动作类型和关键词。",
                "code": "backend/agents/cognitive/tools.py",
            },
            {
                "step": 2,
                "name": "构造 AgentContext",
                "description": "retrieve_strategies_prod 将 role/mbti/alignment/phase/action_type 统一为 AgentContext，作为后续 policy 分桶依据。",
                "code": "backend/agents/cognitive/retrieval_prod.py",
            },
            {
                "step": 3,
                "name": "关键词召回",
                "description": "优先使用 Agent 给出的关键词/正则在 situation、strategy、rationale 等字段中加权 grep；候选过少时回退 BM25 全文检索。",
                "code": "backend/agents/cognitive/retrieval_prod.py",
            },
            {
                "step": 4,
                "name": "RetrievalPolicy 分桶",
                "description": "默认 hybrid_role_mbti_global 依次使用 same_role_same_mbti、same_role_all_mbti、global；hybrid_role_alignment_phase 额外考虑阵营/阶段桶。",
                "code": "backend/agents/cognitive/retrieval_prod.py",
            },
            {
                "step": 5,
                "name": "质量门禁与 Top-K 填充",
                "description": "按 quality / strategy_rank_score 排序，默认质量阈值为 0.72，去重后从优先桶填满 Top-K，并记录 bucket_trace。",
                "code": "backend/agents/cognitive/retrieval_prod.py",
            },
            {
                "step": 6,
                "name": "严格模式安全过滤",
                "description": "AIWEREWOLF_STRICT_MODE=true 时，结果还会进入 retrieve_for_agent 的 4-filter 安全管线，避免低置信、越权或污染知识进入 Prompt。",
                "code": "backend/eval/knowledge_confidence.py",
            },
            {
                "step": 7,
                "name": "Prompt 注入与反馈记录",
                "description": "检索结果进入 Agent Prompt 的 Strategy 层，doc_id 随 tool_trace / strategy usage 进入后续 feedback 和 Track B 联表分析。",
                "code": "backend/agents/cognitive/agent_loop.py",
            },
        ],
        "overall": {
            "query_set_size": results.get("query_set_size"),
            "retriever_size": results.get("retriever_size"),
            "default_policy": default_metrics,
            "baseline_global_only": baseline_metrics,
            "exact_role_mbti_policy": exact_metrics,
            "default_effective_hit_rate_at_3": fnum(default_metrics.get("effective_at_3")),
            "default_precision_at_3": fnum(default_metrics.get("precision_at_3")),
            "default_coverage": fnum(default_metrics.get("coverage_rate")),
            "default_role_bucket_share": fnum(default_metrics.get("role_bucket_share")),
            "default_global_bucket_share": fnum(default_metrics.get("global_bucket_share")),
            "exact_policy_empty_results": inum(exact_metrics.get("n_empty")),
        },
        "policy_comparison_by_role": policy_comparison,
        "single_role_policy_summary": policy_summaries,
        "single_role": role_summaries,
        "limitations": [
            "当前 26 条查询是离线弱标注 query set；Guard/Hunter 等角色样本数较少。",
            "P@3 和 Effective@3 衡量检索相关性，不等同最终胜率或 Track C 因果增益。",
            "精确 role+MBTI 池的空结果既受语料规模影响，也受关键词匹配和质量阈值影响。",
            "正式结论应在后续扩充每角色查询集并进行人工或 LLM judge 复核后再冻结。",
        ],
    }


def render_report(evidence: dict[str, Any]) -> str:
    overall = evidence["overall"]
    default = overall["default_policy"]
    baseline = overall["baseline_global_only"]
    exact = overall["exact_role_mbti_policy"]
    role_rows = evidence["single_role"]
    policy_summaries = evidence["single_role_policy_summary"]
    policy_comparison = evidence["policy_comparison_by_role"]
    pipeline = evidence["retrieval_pipeline"]

    lines = [
        "# 单角色检索机制与量化报告",
        "",
        f"生成时间：{evidence['generated_at']}",
        "",
        "数据来源：",
        "",
        f"- `{evidence['sources']['results']}`",
        f"- `{evidence['sources']['per_role_results']}`",
        f"- `{evidence['sources']['role_corpus_stats']}`",
        f"- `{evidence['sources']['per_query_details']}`",
        f"- 代码依据：`{evidence['sources']['code_retriever']}`、`{evidence['sources']['code_tool']}`、`{evidence['sources']['code_evaluation']}`",
        "",
        "可追溯性说明：`outputs/retrieval_effectiveness_current/` 是本地实验输出目录，按仓库规则不进入 GitHub；本报告对应的可提交机器可读摘要保存在 `docs/evidence/PROJECT_ROLE_RETRIEVAL_FACTS.json`，方法总览同时汇总到 `docs/evidence/PROJECT_METHOD_EFFECTIVENESS_FACTS.json`。",
        "",
        "## 1. 单角色检索是如何运行的",
        "",
        "当前单角色检索不是简单按角色查表，而是“关键词候选召回 + RetrievalPolicy 分桶 + 质量门禁 + Top-K 填充”的组合流程。Agent 调用 `search_strategies` 时会带入自己的角色、MBTI、阵营、阶段、动作类型和关键词；`StrategyRetriever.search_with_keywords` 先用关键词在策略知识字段中召回候选，如果候选不足会走 BM25 全文搜索兜底，然后由 `RetrievalPolicy` 决定候选对该角色是否可见。",
        "",
        "默认策略 `hybrid_role_mbti_global` 的单角色路径为：优先 exact role+MBTI，其次 same-role 通用策略，最后 global 通用策略。当前 `TRACK_C_ALLOW_CROSS_MBTI_ROLE_FILL` 默认关闭，因此 same-role fallback 主要使用该角色通用策略或当前 MBTI 匹配策略，避免把其他人格的经验直接注入当前角色。",
        "",
        "### 1.1 单角色检索步骤",
        "",
        table(
            ["步骤", "环节", "量化/记录点", "代码依据"],
            [
                [
                    item["step"],
                    item["name"],
                    item["description"],
                    f"`{item['code']}`",
                ]
                for item in pipeline
            ],
        ),
        "",
        "```mermaid",
        "flowchart LR",
        "    accTitle: Single Role Retrieval Flow",
        "    accDescr: A single agent provides role, MBTI, phase and keywords. The retriever recalls candidates, filters them into policy buckets, applies quality gates, and returns top-k strategy docs.",
        "    observation[PlayerView / Observation] --> tool[search_strategies]",
        "    tool --> context[role + MBTI + alignment + phase + action]",
        "    context --> keywords[agent keywords / regex]",
        "    keywords --> grep[keyword grep over strategy docs]",
        "    grep --> fallback{candidates < 3?}",
        "    fallback -->|yes| bm25[BM25 full-text fallback]",
        "    fallback -->|no| candidates[candidate docs]",
        "    bm25 --> candidates",
        "    candidates --> policy{RetrievalPolicy}",
        "    policy --> exact[same_role_same_mbti]",
        "    policy --> role[same_role_all_mbti]",
        "    policy --> align[same_alignment_all_mbti]",
        "    policy --> global[global]",
        "    exact --> fill[quality gate + dedup + top-k fill]",
        "    role --> fill",
        "    align --> fill",
        "    global --> fill",
        "    fill --> prompt[Strategy layer in Agent prompt]",
        "```",
        "",
        "## 2. 命中率口径",
        "",
        table(
            ["指标", "含义", "本报告中的解释"],
            [
                ["P@3", "Top-3 中相关策略占比", "检索结果整体纯度"],
                ["Effective@3", "Top-3 至少一条相关策略", "实际可用命中率"],
                ["Coverage", "查询是否返回至少一条策略", "是否空检索"],
                ["Top5Fill", "Top-5 是否填满", "候选池充足程度"],
                ["RoleBucketShare", "Top-5 中来自本角色桶的比例", "是否真正按角色检索"],
                ["GlobalBucketShare", "Top-5 中来自全局桶的比例", "global 兜底依赖程度"],
            ],
        ),
        "",
        "## 3. 总体策略对比",
        "",
        table(
            [
                "Policy",
                "OfflineScore",
                "P@3",
                "Effective@3",
                "nDCG@5",
                "Coverage",
                "Top5Fill",
                "RoleBucket",
                "GlobalBucket",
                "Empty",
            ],
            [
                [
                    BASELINE_POLICY,
                    fmt(baseline.get("offline_score")),
                    fmt(baseline.get("precision_at_3")),
                    fmt(baseline.get("effective_at_3")),
                    fmt(baseline.get("ndcg_at_5")),
                    fmt(baseline.get("coverage_rate")),
                    fmt(baseline.get("top5_fill_rate")),
                    fmt(baseline.get("role_bucket_share")),
                    fmt(baseline.get("global_bucket_share")),
                    baseline.get("n_empty"),
                ],
                [
                    DEFAULT_POLICY,
                    fmt(default.get("offline_score")),
                    fmt(default.get("precision_at_3")),
                    fmt(default.get("effective_at_3")),
                    fmt(default.get("ndcg_at_5")),
                    fmt(default.get("coverage_rate")),
                    fmt(default.get("top5_fill_rate")),
                    fmt(default.get("role_bucket_share")),
                    fmt(default.get("global_bucket_share")),
                    default.get("n_empty"),
                ],
                [
                    EXACT_POLICY,
                    fmt(exact.get("offline_score")),
                    fmt(exact.get("precision_at_3")),
                    fmt(exact.get("effective_at_3")),
                    fmt(exact.get("ndcg_at_5")),
                    fmt(exact.get("coverage_rate")),
                    fmt(exact.get("top5_fill_rate")),
                    fmt(exact.get("role_bucket_share")),
                    fmt(exact.get("global_bucket_share")),
                    exact.get("n_empty"),
                ],
            ],
        ),
        "",
        f"按 Effective@3 作为可用命中率口径，默认单角色检索当前整体命中率为 {pct(overall['default_effective_hit_rate_at_3'])}；P@3 为 {fmt(overall['default_precision_at_3'])}；Coverage 为 {pct(overall['default_coverage'])}。默认策略的 RoleBucketShare 为 {pct(overall['default_role_bucket_share'])}，GlobalBucketShare 为 {pct(overall['default_global_bucket_share'])}，说明结果主要来自本角色策略桶，global 只承担兜底。",
        "",
        "精确 `same_role_same_mbti` 当前不适合单独作为默认策略：整体 Coverage 只有 "
        f"{pct(exact.get('coverage_rate'))}，空结果 {overall['exact_policy_empty_results']} / {overall['query_set_size']}。这说明单角色个性化应作为优先桶，而不是唯一检索范围。",
        "",
        "## 4. 单角色路径量化摘要",
        "",
        table(
            [
                "Role",
                "BestPolicy",
                "DefaultEff@3",
                "GlobalEff@3",
                "ExactEff@3",
                "Default-Global Eff@3",
                "Default P@3",
                "RoleBucket",
                "ExactBucket",
                "GlobalBucket",
                "诊断",
            ],
            [
                [
                    row["role"],
                    row["best_policy_by_offline_score"],
                    fmt(row["default_effective_at_3"]),
                    fmt(row["global_only_effective_at_3"]),
                    fmt(row["same_role_same_mbti_effective_at_3"]),
                    fmt(row["default_minus_global_effective_at_3"]),
                    fmt(row["default_precision_at_3"]),
                    fmt(row["default_role_bucket_share"]),
                    fmt(row["default_exact_bucket_share"]),
                    fmt(row["default_global_bucket_share"]),
                    row["diagnosis"],
                ]
                for row in policy_summaries
            ],
        ),
        "",
        "这张表把“单个角色如何命中”拆成三层：第一，默认策略是否比 `global_only` 更容易命中；第二，检索结果到底来自本角色桶、精确 role+MBTI 桶还是 global 兜底；第三，当前短板是语料不足还是相关性不足。当前默认策略 6 个核心角色 Coverage 均为 1.0000，但不同角色的 Effective@3 差异明显。",
        "",
        "## 5. 单角色默认检索结果",
        "",
        table(
            ["Role", "Queries", "P@3", "Effective@3", "Coverage", "Top5Fill", "RoleBucket", "GlobalBucket", "Empty"],
            [
                [
                    row["role"],
                    row["query_count"],
                    fmt(row["default_precision_at_3"]),
                    fmt(row["default_effective_at_3"]),
                    fmt(row["default_coverage"]),
                    fmt(row["default_top5_fill_rate"]),
                    fmt(row["default_role_bucket_share"]),
                    fmt(row["default_global_bucket_share"]),
                    row["default_empty_results"],
                ]
                for row in role_rows
            ],
        ),
        "",
        "## 6. 单角色 Policy 对比",
        "",
        table(
            [
                "Role",
                "Policy",
                "P@3",
                "Effective@3",
                "Coverage",
                "OfflineScore",
                "RoleBucket",
                "GlobalBucket",
                "Empty",
            ],
            [
                [
                    row["role"],
                    row["policy"],
                    fmt(row["precision_at_3"]),
                    fmt(row["effective_at_3"]),
                    fmt(row["coverage"]),
                    fmt(row["offline_score"]),
                    fmt(row["role_bucket_share"]),
                    fmt(row["global_bucket_share"]),
                    row["empty_results"],
                ]
                for row in policy_comparison
            ],
        ),
        "",
        "Policy 对比显示，`same_role_all_mbti` 通常能提供稳定覆盖，`same_role_same_mbti` 当前因为 MBTI 细分策略不足而频繁为空；默认 `hybrid_role_mbti_global` 在覆盖率和角色约束之间取得更稳妥的折中。",
        "",
        "## 7. 单角色知识池规模",
        "",
        table(
            [
                "Role",
                "RoleDocs",
                "RoleGeneric",
                "RoleMBTISpecific",
                "ExactPoolAvg",
                "ExactEmptyBeforeKeyword",
                "HybridRolePoolAvg",
                "HybridTotalPoolAvg",
                "GlobalGeneric",
                "DocMBTIs",
            ],
            [
                [
                    row["role"],
                    row["role_scope_docs"],
                    row["role_generic_docs"],
                    row["role_mbti_specific_docs"],
                    fmt(row["exact_role_mbti_pool_avg"], 2),
                    row["exact_role_mbti_empty_queries_before_keyword"],
                    fmt(row["hybrid_default_role_pool_avg"], 2),
                    fmt(row["hybrid_default_total_pool_avg"], 2),
                    row["global_generic_docs"],
                    row["doc_mbti_distribution"] or "-",
                ]
                for row in role_rows
            ],
        ),
        "",
        "## 8. 分角色解释",
        "",
    ]

    for row in role_rows:
        lines += [
            f"### {row['role']}",
            "",
            row["summary"],
            "",
        ]

    lines += [
        "## 9. 当前可写结论与边界",
        "",
        table(
            ["可以写入报告的结论", "证据来源"],
            [
                [
                    "默认单角色检索能够覆盖 6 个核心角色，当前离线 query set 无空结果。",
                    "`outputs/retrieval_effectiveness_current/per_role_results.csv`",
                ],
                [
                    "默认策略主要从本角色桶返回策略，而不是依赖全局兜底。",
                    "`outputs/retrieval_effectiveness_current/results.json`",
                ],
                [
                    "精确 role+MBTI 检索当前过窄，不适合作为唯一默认策略。",
                    "`outputs/retrieval_effectiveness_current/results.json` 与 `role_corpus_stats.csv`",
                ],
                [
                    "Guard、Hunter、Witch、Villager 等角色需要补充更多 MBTI 细分策略卡。",
                    "`outputs/retrieval_effectiveness_current/role_corpus_stats.csv`",
                ],
            ],
        ),
        "",
        table(
            ["暂不能写入的结论", "原因", "后续补充"],
            [
                [
                    "每个角色的当前检索策略已经达到最终最优",
                    "离线 query set 每角色样本数有限，且为弱标注。",
                    "每角色补 20+ 查询，并进行人工或 LLM judge 标注。",
                ],
                [
                    "单角色检索直接带来胜率提升",
                    "当前指标是检索相关性，不是在线因果实验。",
                    "运行 target-seat paired A/B，固定对手，只切换目标席位 Track C。",
                ],
                [
                    "role+MBTI 个性化已经充分覆盖所有角色",
                    "当前 MBTI 细分策略集中在少数角色/人格。",
                    "按角色和 MBTI 补充 active 策略卡，再重跑检索评估。",
                ],
            ],
        ),
        "",
        "## 10. 建议补充实验",
        "",
        "- 每个角色构造不少于 20 条场景查询，覆盖发言、投票、夜间技能和身份暴露等关键局面。",
        "- 对 Top-5 检索结果进行人工或 LLM judge 复核，区分弱标注误差和真实检索误差。",
        "- 分别评估 `same_role_all_mbti`、`same_role_same_mbti`、`hybrid_role_mbti_global` 对每个角色的最佳适配情况。",
        "- 扩充 Guard、Hunter、Villager、Witch 的 MBTI 细分 active 策略卡，再重跑本脚本。",
        "- 将 `knowledge_usage_feedback` 与 Track B `ScoredStep` 联表，统计单角色 used strategy 对决策分数的影响。",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", default=str(DEFAULT_INPUT_DIR))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--facts", default=str(DEFAULT_FACTS))
    args = parser.parse_args()

    input_dir = Path(args.input_dir).resolve()
    evidence = build_evidence(input_dir)

    report_path = Path(args.report).resolve()
    facts_path = Path(args.facts).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    facts_path.parent.mkdir(parents=True, exist_ok=True)

    report_path.write_text(render_report(evidence), encoding="utf-8")
    facts_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Wrote {report_path.relative_to(ROOT)}")
    print(f"Wrote {facts_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
