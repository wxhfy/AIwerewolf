#!/usr/bin/env python3
"""LLM-judged retrieval policy evaluation.

This script reuses the fixed query set and metric code from
``evaluate_retrieval_policies.py`` but replaces weak labels with an
OpenAI-compatible LLM judge. For each query, it retrieves top-5 documents
for every policy, deduplicates the candidate docs, and asks the judge once
to score each candidate from 0 to 3.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.evaluate_retrieval_policies import QUERY_SET
from scripts.evaluate_retrieval_policies import PolicyMetrics
from scripts.evaluate_retrieval_policies import build_effect_summary
from scripts.evaluate_retrieval_policies import compute_metrics
from scripts.evaluate_retrieval_policies import compute_offline_score


def _derive_alignment_for_role(role: str) -> str:
    from backend.agents.cognitive.retrieval_prod import _derive_alignment_from_role

    return _derive_alignment_from_role(role)


def _doc_key(doc: dict[str, Any]) -> str:
    doc_id = str(doc.get("doc_id") or "").strip()
    if doc_id:
        return doc_id
    return "|".join(
        [
            str(doc.get("role_scope") or doc.get("role") or ""),
            str(doc.get("phase_scope") or doc.get("phase") or ""),
            str(doc.get("situation") or "")[:80],
            str(doc.get("strategy") or "")[:120],
        ]
    )


def _truncate(text: Any, limit: int) -> str:
    value = str(text or "").replace("\n", " ").strip()
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _build_judge_prompt(query: dict[str, Any], docs: list[dict[str, Any]]) -> str:
    doc_lines = []
    for idx, doc in enumerate(docs):
        doc_lines.append(
            "\n".join(
                [
                    f"ID: {idx}",
                    f"role_scope: {doc.get('role_scope') or doc.get('role') or ''}",
                    f"mbti_scope: {doc.get('mbti_scope') or ''}",
                    f"phase_scope: {doc.get('phase_scope') or doc.get('phase') or ''}",
                    f"situation: {_truncate(doc.get('situation'), 180)}",
                    f"strategy: {_truncate(doc.get('strategy'), 320)}",
                    f"quality: {doc.get('quality', doc.get('quality_score', ''))}",
                ]
            )
        )

    return "\n\n".join(
        [
            "你是狼人杀 Agent 检索质量裁判。请只根据查询目标和候选策略文档，给每个文档打相关性分。",
            "评分标准：3=高度相关且可直接用于当前角色/阶段/动作；2=相关且有明显帮助；1=部分相关但过泛或不完全匹配；0=无关或会误导。",
            "优先考虑：角色匹配、阶段/动作匹配、策略是否具体可执行、是否符合当前阵营信息边界。MBTI 匹配是次要加分项，不应压过角色和阶段。",
            '必须输出严格 JSON，格式为：{"scores":{"0":3,"1":2},"rationale":"一句话说明主要判断"}。不要输出 Markdown。',
            "",
            "查询：",
            json.dumps(
                {
                    "query_id": query["query_id"],
                    "role": query["role"],
                    "alignment": query.get("alignment", _derive_alignment_for_role(query["role"])),
                    "mbti": query.get("mbti", ""),
                    "phase": query["phase"],
                    "action_type": query.get("action_type", ""),
                    "keywords": query.get("keywords", []),
                    "situation": query.get("situation", ""),
                },
                ensure_ascii=False,
            ),
            "",
            "候选文档：",
            "\n\n---\n\n".join(doc_lines),
        ]
    )


def _extract_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?", "", stripped).strip()
        stripped = re.sub(r"```$", "", stripped).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, flags=re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def _judge_query(
    client: Any,
    query: dict[str, Any],
    docs: list[dict[str, Any]],
    *,
    model: str,
    max_tokens: int,
) -> tuple[dict[str, int], str, int]:
    if not docs:
        return {}, "no candidate docs", 0

    prompt = _build_judge_prompt(query, docs)
    response = client.chat_sync(
        [{"role": "user", "content": prompt}],
        model=model or None,
        temperature=0.0,
        max_tokens=max_tokens,
        thinking=False,
    )
    message = response.get("choices", [{}])[0].get("message", {})
    content = str(message.get("content") or "")
    parsed = _extract_json(content)
    raw_scores = parsed.get("scores", {})
    scores: dict[str, int] = {}
    for idx in range(len(docs)):
        raw = raw_scores.get(str(idx), raw_scores.get(idx, 0))
        try:
            scores[str(idx)] = max(0, min(3, int(raw)))
        except (TypeError, ValueError):
            scores[str(idx)] = 0
    rationale = str(parsed.get("rationale") or "").strip()
    total_tokens = int((response.get("usage") or {}).get("total_tokens") or 0)
    return scores, rationale, total_tokens


def _retrieve_all_policies() -> tuple[dict[str, list[dict[str, Any]]], int]:
    from backend.agents.cognitive.retrieval_prod import AgentContext
    from backend.agents.cognitive.retrieval_prod import RetrievalPolicy
    from backend.agents.cognitive.retrieval_prod import _derive_alignment_from_role
    from backend.agents.cognitive.retrieval_prod import get_retriever

    retriever = get_retriever()
    if retriever is None or not retriever.ready:
        raise RuntimeError("retriever_not_available")

    results_by_policy: dict[str, list[dict[str, Any]]] = {}
    for policy in RetrievalPolicy:
        policy_results: list[dict[str, Any]] = []
        for query in QUERY_SET:
            ctx = AgentContext(
                player_id=f"llm_judge_{query['query_id']}",
                role=query["role"],
                alignment=query.get("alignment", _derive_alignment_from_role(query["role"])),
                mbti=query.get("mbti", ""),
                phase=query["phase"],
                action_type=query.get("action_type", ""),
                keywords=query.get("keywords", []),
            )
            started = time.perf_counter()
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
            policy_results.append(
                {
                    "query_id": query["query_id"],
                    "query": query,
                    "results": hits,
                    "latency_ms": (time.perf_counter() - started) * 1000,
                }
            )
        results_by_policy[policy.value] = policy_results
    return results_by_policy, retriever.size


def _candidate_docs_for_query(
    results_by_policy: dict[str, list[dict[str, Any]]],
    query_index: int,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    docs: list[dict[str, Any]] = []
    key_to_idx: dict[str, int] = {}
    for policy_results in results_by_policy.values():
        for doc in policy_results[query_index]["results"]:
            key = _doc_key(doc)
            if key not in key_to_idx:
                key_to_idx[key] = len(docs)
                docs.append(doc)
    return docs, key_to_idx


def run_llm_judge(
    *,
    provider: str,
    model: str,
    output_dir: str,
    max_tokens: int,
    judge_retries: int,
) -> dict[str, Any]:
    from backend.llm import create_client

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    results_by_policy, retriever_size = _retrieve_all_policies()
    timeout = httpx.Timeout(connect=5.0, read=60.0, write=30.0, pool=5.0)
    client = create_client(provider=provider, model=model or None, timeout=timeout, max_retries=0)
    if getattr(client, "available", True) is False:
        raise RuntimeError(f"{getattr(client, 'provider', provider)} client unavailable")

    query_judgments: list[dict[str, Any]] = []
    total_tokens = 0
    failed_queries: list[dict[str, str]] = []

    for query_index, query in enumerate(QUERY_SET):
        print(f"judging {query['query_id']} ...", flush=True)
        docs, key_to_idx = _candidate_docs_for_query(results_by_policy, query_index)
        scores_by_idx: dict[str, int] | None = None
        rationale = ""
        last_error = ""
        for attempt in range(judge_retries + 1):
            try:
                scores_by_idx, rationale, tokens = _judge_query(
                    client,
                    query,
                    docs,
                    model=model,
                    max_tokens=max_tokens,
                )
                total_tokens += tokens
                break
            except Exception as exc:
                last_error = f"judge_failed: {type(exc).__name__}: {exc}"
                if attempt < judge_retries:
                    time.sleep(min(2.0 * (attempt + 1), 8.0))
        if scores_by_idx is None:
            scores_by_idx = {str(idx): 0 for idx in range(len(docs))}
            rationale = last_error
            failed_queries.append({"query_id": query["query_id"], "error": rationale})

        score_by_doc_key = {key: scores_by_idx.get(str(idx), 0) for key, idx in key_to_idx.items()}
        for policy_name, policy_results in results_by_policy.items():
            result = policy_results[query_index]
            rel_scores = [score_by_doc_key.get(_doc_key(doc), 0) for doc in result["results"]]
            result["relevance_scores"] = rel_scores
            for doc, rel in zip(result["results"], rel_scores):
                doc["_llm_relevance"] = rel

        query_judgments.append(
            {
                "query_id": query["query_id"],
                "n_candidate_docs": len(docs),
                "rationale": rationale,
                "scores": scores_by_idx,
                "doc_ids": [doc.get("doc_id", "") for doc in docs],
            }
        )

    metrics: dict[str, PolicyMetrics] = {}
    scores: dict[str, float] = {}
    for policy_name, policy_results in results_by_policy.items():
        latencies = [float(r.get("latency_ms", 0.0)) for r in policy_results]
        metric = compute_metrics(policy_name, policy_results, latencies)
        metrics[policy_name] = metric
        scores[policy_name] = compute_offline_score(metric)

    ranked = sorted(scores.items(), key=lambda item: -item[1])
    effect_summary = build_effect_summary(metrics, scores)
    summary = {
        "judge": "llm",
        "provider": provider,
        "model": model,
        "query_set_size": len(QUERY_SET),
        "retriever_size": retriever_size,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "failed_queries": failed_queries,
        "total_tokens": total_tokens,
        "ranked_policies": [{"policy": p, "offline_score": round(s, 4)} for p, s in ranked],
        "effect_summary": effect_summary,
        "metrics": {
            name: {
                "policy": name,
                "n_queries": metric.n_queries,
                "n_empty": metric.n_empty,
                "precision_at_3": round(metric.precision_at_3, 4),
                "ndcg_at_5": round(metric.ndcg_at_5, 4),
                "avg_relevance": round(metric.avg_relevance, 4),
                "role_match_rate": round(metric.role_match_rate, 4),
                "mbti_match_rate": round(metric.mbti_match_rate, 4),
                "phase_match_rate": round(metric.phase_match_rate, 4),
                "coverage_rate": round(metric.coverage_rate, 4),
                "candidate_leakage_count": metric.candidate_leakage_count,
                "offline_score": round(scores[name], 4),
            }
            for name, metric in metrics.items()
        },
    }

    (output / "results.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    with (output / "per_query_judgments.jsonl").open("w", encoding="utf-8") as handle:
        for row in query_judgments:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (output / "policy_results.jsonl").open("w", encoding="utf-8") as handle:
        for policy_name, policy_results in results_by_policy.items():
            for row in policy_results:
                handle.write(json.dumps({"policy": policy_name, **row}, ensure_ascii=False) + "\n")
    with (output / "results.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "rank",
                "policy",
                "score",
                "delta_score_vs_baseline",
                "P@3",
                "delta_p@3_vs_baseline",
                "nDCG@5",
                "delta_ndcg@5_vs_baseline",
                "Coverage",
                "delta_coverage_vs_baseline",
                "AvgRel",
                "NEmpty",
            ]
        )
        for rank, (policy_name, score) in enumerate(ranked, 1):
            metric = metrics[policy_name]
            effect = effect_summary["effects"][policy_name]
            writer.writerow(
                [
                    rank,
                    policy_name,
                    f"{score:.4f}",
                    f"{effect['score_delta']:.4f}",
                    f"{metric.precision_at_3:.4f}",
                    f"{effect['precision_at_3_delta']:.4f}",
                    f"{metric.ndcg_at_5:.4f}",
                    f"{effect['ndcg_at_5_delta']:.4f}",
                    f"{metric.coverage_rate:.4f}",
                    f"{effect['coverage_rate_delta']:.4f}",
                    f"{metric.avg_relevance:.4f}",
                    metric.n_empty,
                ]
            )

    md_lines = [
        "# LLM Judge Retrieval Policy Evaluation",
        "",
        f"Judge: `{provider}` / `{model}`",
        f"Failed queries: {len(failed_queries)}/{len(QUERY_SET)}",
        f"Baseline for deltas: `{effect_summary['baseline_policy']}`",
        "",
        "| Rank | Policy | Score | ΔScore | P@3 | ΔP@3 | nDCG@5 | ΔnDCG@5 | Coverage | ΔCoverage | AvgRel | Empty |",
        "|------|--------|-------|--------|-----|------|--------|---------|----------|-----------|--------|-------|",
    ]
    for rank, (policy_name, score) in enumerate(ranked, 1):
        metric = metrics[policy_name]
        effect = effect_summary["effects"][policy_name]
        md_lines.append(
            f"| {rank} | `{policy_name}` | {score:.4f} | {effect['score_delta']:+.4f} | "
            f"{metric.precision_at_3:.2f} | {effect['precision_at_3_delta']:+.2f} | "
            f"{metric.ndcg_at_5:.2f} | {effect['ndcg_at_5_delta']:+.2f} | "
            f"{metric.coverage_rate:.2f} | {effect['coverage_rate_delta']:+.2f} | "
            f"{metric.avg_relevance:.2f} | {metric.n_empty}/{metric.n_queries} |"
        )
    if failed_queries:
        md_lines += ["", "## Failed Queries", ""]
        for item in failed_queries:
            md_lines.append(f"- `{item['query_id']}`: {item['error']}")
    (output / "summary.md").write_text("\n".join(md_lines), encoding="utf-8")

    print(f"\nResults saved to {output}")
    print(f"Top policy: {ranked[0][0]} (score={ranked[0][1]:.4f})")
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
    if failed_queries:
        print(f"WARNING: {len(failed_queries)} query judge calls failed; see summary.md")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate retrieval policies with an LLM judge")
    parser.add_argument("--provider", default=os.getenv("LLM_PROVIDER", "weapi"))
    parser.add_argument("--model", default=os.getenv("WEAPI_MODEL", "gpt-5.5"))
    parser.add_argument("--output", default="outputs/retrieval_policy_eval_llm_judge")
    parser.add_argument("--max-tokens", type=int, default=1200)
    parser.add_argument("--judge-retries", type=int, default=2)
    args = parser.parse_args()

    run_llm_judge(
        provider=args.provider,
        model=args.model,
        output_dir=args.output,
        max_tokens=args.max_tokens,
        judge_retries=args.judge_retries,
    )


if __name__ == "__main__":
    main()
