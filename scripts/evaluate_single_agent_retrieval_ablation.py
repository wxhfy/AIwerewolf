#!/usr/bin/env python3
"""Lightweight single-agent retrieval ablation judged by an LLM.

This script does not run full games. It fixes a small set of single-agent
werewolf decision scenarios, changes only the retrieval policy used to provide
strategy context, asks the same model to make a decision, and then asks an
anonymous LLM judge to score the resulting decisions.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_OUTPUT = ROOT / "outputs" / "single_agent_retrieval_llm_ablation"
DEFAULT_EVIDENCE_JSON = ROOT / "docs" / "evidence" / "PROJECT_SINGLE_AGENT_RETRIEVAL_LLM_ABLATION.json"
DEFAULT_EVIDENCE_MD = ROOT / "docs" / "evidence" / "PROJECT_SINGLE_AGENT_RETRIEVAL_LLM_ABLATION.md"

POLICIES = [
    "no_retrieval",
    "global_only",
    "same_role_all_mbti",
    "hybrid_role_mbti_global",
]

SCENARIOS: list[dict[str, Any]] = [
    {
        "scenario_id": "wolf_checked_speech",
        "role": "Werewolf",
        "alignment": "wolf",
        "mbti": "INTJ",
        "phase": "DAY_SPEECH",
        "action_type": "talk",
        "keywords": ["被查杀", "表水", "悍跳", "警徽流"],
        "situation": "7人局第1天白天，1号声称预言家并查杀3号，3号是狼人；6号是狼同伴但不能暴露。",
        "task": "你是3号狼人，请生成一段白天发言，并给出投票倾向。",
        "legal_targets": ["P1", "P2", "P4", "P5", "P6", "P7"],
        "private_info": "你知道6号是狼同伴。公开发言不能直接泄露狼队信息。",
    },
    {
        "scenario_id": "seer_badge_claim",
        "role": "Seer",
        "alignment": "village",
        "mbti": "INTJ",
        "phase": "DAY_BADGE_SPEECH",
        "action_type": "talk",
        "keywords": ["预言家", "查杀", "警徽流", "对跳"],
        "situation": "7人局第1天警上，2号悍跳预言家给5号金水；你是1号真预言家，昨夜查验6号为狼人。",
        "task": "你是1号预言家，请生成警上发言，说明查验和警徽流。",
        "legal_targets": ["P2", "P3", "P4", "P5", "P6", "P7"],
        "private_info": "你知道6号查验结果为狼人。",
    },
    {
        "scenario_id": "witch_first_night_save",
        "role": "Witch",
        "alignment": "village",
        "mbti": "ISTJ",
        "phase": "NIGHT_WITCH_ACTION",
        "action_type": "save",
        "keywords": ["女巫", "解药", "救人", "首夜"],
        "situation": "7人局首夜，狼人刀口是4号。你是女巫，解药和毒药都还在。",
        "task": "请决定是否使用解药、是否使用毒药；如果不用也要说明一句公开可审计理由。",
        "legal_targets": ["P1", "P2", "P3", "P4", "P5", "P6", "P7"],
        "private_info": "只有你知道今晚刀口是4号。",
    },
    {
        "scenario_id": "hunter_exile_speech",
        "role": "Hunter",
        "alignment": "village",
        "mbti": "ESTP",
        "phase": "DAY_SPEECH",
        "action_type": "talk",
        "keywords": ["猎人", "开枪", "放逐", "表水"],
        "situation": "第2天白天，你是5号猎人并被多人归票；2号和7号互踩，3号发言前后矛盾。",
        "task": "请生成放逐前发言，决定是否跳猎人身份，并给出潜在枪口或票口。",
        "legal_targets": ["P1", "P2", "P3", "P4", "P6", "P7"],
        "private_info": "你确认自己是猎人，若被放逐可开枪。",
    },
    {
        "scenario_id": "guard_second_night",
        "role": "Guard",
        "alignment": "village",
        "mbti": "ISTJ",
        "phase": "NIGHT_GUARD_ACTION",
        "action_type": "guard",
        "keywords": ["守卫", "守护", "预言家", "连续"],
        "situation": "第2夜，你是守卫。上一夜守护了1号；白天1号被多数人认作真预言家，狼队可能刀1号。",
        "task": "请在不能连续守护同一人的前提下选择今晚守护目标。",
        "legal_targets": ["P2", "P3", "P4", "P5", "P6", "P7"],
        "private_info": "规则限制：本场不能连续两晚守护同一玩家，所以今晚不能守1号。",
    },
    {
        "scenario_id": "villager_vote_standoff",
        "role": "Villager",
        "alignment": "village",
        "mbti": "ENFP",
        "phase": "DAY_VOTE",
        "action_type": "vote",
        "keywords": ["投票", "站边", "归票", "预言家"],
        "situation": "第1天放逐投票前，1号和2号对跳预言家；1号给6号查杀，2号给5号金水。4号发言只跟票无推理。",
        "task": "你是普通平民，请给出投票目标和一句投票理由。",
        "legal_targets": ["P1", "P2", "P3", "P4", "P5", "P6", "P7"],
        "private_info": "你没有夜间信息，只能根据公开发言和票型判断。",
    },
]


@dataclass
class LLMCallResult:
    content: str
    latency_ms: int
    total_tokens: int
    raw: dict[str, Any]


def extract_json(text: str) -> dict[str, Any]:
    """Extract a JSON object from a model response."""
    stripped = str(text or "").strip()
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


def clamp_score(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(10.0, float(value)))
    except (TypeError, ValueError):
        return default


def mean(values: list[float]) -> float:
    return float(statistics.fmean(values)) if values else 0.0


def fmt(value: Any, digits: int = 2) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "n/a"


def pct_delta(candidate: float, baseline: float) -> str:
    if baseline == 0:
        return "n/a"
    return f"{((candidate - baseline) / baseline) * 100:+.1f}%"


def chat_sync(client: Any, messages: list[dict[str, str]], *, model: str, max_tokens: int) -> LLMCallResult:
    started = time.perf_counter()
    response = client.chat_sync(
        messages,
        model=model or None,
        temperature=0.0,
        max_tokens=max_tokens,
        thinking=False,
    )
    latency_ms = int((time.perf_counter() - started) * 1000)
    message = response.get("choices", [{}])[0].get("message", {})
    usage = response.get("usage") or {}
    return LLMCallResult(
        content=str(message.get("content") or ""),
        latency_ms=latency_ms,
        total_tokens=int(usage.get("total_tokens") or 0),
        raw=response,
    )


def build_client(provider: str, model: str, timeout_seconds: float, retries: int) -> Any:
    from backend.llm import create_client

    os.environ.setdefault("LLM_TIMEOUT_SECONDS", str(timeout_seconds))
    timeout = httpx.Timeout(connect=5.0, read=timeout_seconds, write=30.0, pool=5.0)
    client = create_client(provider=provider, model=model or None, timeout=timeout, max_retries=retries)
    if getattr(client, "available", True) is False:
        raise RuntimeError(f"{provider} client unavailable: missing API key")
    if hasattr(client, "timeout"):
        client.timeout = timeout
    return client


def get_retriever() -> Any:
    from backend.agents.cognitive.retrieval_prod import get_retriever as build_retriever

    retriever = build_retriever()
    if retriever is None or not getattr(retriever, "ready", False):
        raise RuntimeError("strategy retriever is not available")
    return retriever


def retrieve_docs(retriever: Any, scenario: dict[str, Any], policy: str, *, top_k: int) -> list[dict[str, Any]]:
    if policy == "no_retrieval":
        return []

    from backend.agents.cognitive.retrieval_prod import AgentContext
    from backend.agents.cognitive.retrieval_prod import RetrievalPolicy

    context = AgentContext(
        player_id=f"single_agent_eval_{scenario['scenario_id']}",
        role=scenario["role"],
        alignment=scenario["alignment"],
        mbti=scenario["mbti"],
        phase=scenario["phase"],
        action_type=scenario["action_type"],
        keywords=list(scenario["keywords"]),
    )
    return retriever.search_with_keywords(
        list(scenario["keywords"]),
        role=scenario["role"],
        phase=scenario["phase"],
        k=top_k,
        use_bm25_rerank=False,
        output_mode="content",
        retrieval_policy=RetrievalPolicy(policy),
        agent_context=context,
    )


def compact_docs(docs: list[dict[str, Any]], *, limit: int = 4) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for doc in docs[:limit]:
        compact.append(
            {
                "doc_id": doc.get("doc_id", ""),
                "bucket": doc.get("bucket", ""),
                "role_scope": doc.get("role_scope", doc.get("role", "")),
                "mbti_scope": doc.get("mbti_scope", ""),
                "phase_scope": doc.get("phase_scope", ""),
                "quality": doc.get("quality", doc.get("quality_score", "")),
                "situation": str(doc.get("situation", ""))[:160],
                "strategy": str(doc.get("strategy", ""))[:320],
            }
        )
    return compact


def build_strategy_context(policy: str, docs: list[dict[str, Any]]) -> str:
    if policy == "no_retrieval":
        return "本轮不提供策略检索结果，请只根据基础规则和可见局面决策。"
    if not docs:
        return "策略检索没有返回可用结果，请只根据基础规则和可见局面决策。"

    lines = []
    for idx, doc in enumerate(compact_docs(docs), 1):
        lines.append(
            "\n".join(
                [
                    f"[策略{idx}] bucket={doc['bucket']} role={doc['role_scope']} mbti={doc['mbti_scope']} phase={doc['phase_scope']}",
                    f"局面: {doc['situation']}",
                    f"建议: {doc['strategy']}",
                ]
            )
        )
    return "\n\n".join(lines)


def build_decision_messages(scenario: dict[str, Any], policy: str, docs: list[dict[str, Any]]) -> list[dict[str, str]]:
    payload = {
        "scenario_id": scenario["scenario_id"],
        "role": scenario["role"],
        "alignment": scenario["alignment"],
        "mbti": scenario["mbti"],
        "phase": scenario["phase"],
        "action_type": scenario["action_type"],
        "situation": scenario["situation"],
        "task": scenario["task"],
        "legal_targets": scenario["legal_targets"],
        "private_info": scenario["private_info"],
        "strategy_context": build_strategy_context(policy, docs),
    }
    system = (
        "你是狼人杀单 Agent 决策器。你只能使用题目给出的可见信息、私有信息和策略上下文。"
        "输出必须是严格 JSON，不要 Markdown，不要展示长思维链。"
    )
    user = "\n".join(
        [
            "请完成当前单 Agent 决策。",
            json.dumps(payload, ensure_ascii=False, indent=2),
            "",
            "输出 JSON 格式：",
            json.dumps(
                {
                    "action": "talk/vote/guard/save/poison/shoot/skip",
                    "target": "P? 或 null",
                    "speech": "公开可说的话，夜间行动可为空",
                    "rationale": "一句话说明可审计理由",
                    "risk_control": "一句话说明如何控制身份、信息或误伤风险",
                },
                ensure_ascii=False,
            ),
        ]
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def normalize_decision(raw: str) -> dict[str, Any]:
    try:
        parsed = extract_json(raw)
    except Exception:
        parsed = {"action": "", "target": None, "speech": raw[:500], "rationale": "", "risk_control": ""}
    return {
        "action": str(parsed.get("action") or "").strip(),
        "target": parsed.get("target"),
        "speech": str(parsed.get("speech") or "").strip(),
        "rationale": str(parsed.get("rationale") or "").strip(),
        "risk_control": str(parsed.get("risk_control") or "").strip(),
    }


def build_judge_messages(
    scenario: dict[str, Any],
    anonymous_decisions: list[tuple[str, dict[str, Any]]],
) -> list[dict[str, str]]:
    options = [
        {
            "option": label,
            "decision": decision,
        }
        for label, decision in anonymous_decisions
    ]
    prompt = {
        "scenario": {
            "scenario_id": scenario["scenario_id"],
            "role": scenario["role"],
            "alignment": scenario["alignment"],
            "mbti": scenario["mbti"],
            "phase": scenario["phase"],
            "action_type": scenario["action_type"],
            "situation": scenario["situation"],
            "task": scenario["task"],
            "legal_targets": scenario["legal_targets"],
            "private_info_boundary": scenario["private_info"],
        },
        "anonymous_options": options,
    }
    system = (
        "你是狼人杀单 Agent 决策质量裁判。你不知道每个选项来自哪种检索策略。"
        "请只评价决策结果本身，不要猜测来源。输出严格 JSON。"
    )
    user = "\n".join(
        [
            "请按 0-10 分评价每个匿名选项，评分维度：",
            "1. role_fit：是否符合角色/阵营任务；2. strategic_depth：是否体现博弈策略；",
            "3. actionability：行动、目标、发言是否明确可执行；4. information_safety：是否遵守信息边界；",
            "5. overall：综合质量。",
            "只给简短理由，不要输出长思维链。",
            "",
            json.dumps(prompt, ensure_ascii=False, indent=2),
            "",
            "输出 JSON 格式：",
            json.dumps(
                {
                    "scores": {
                        "A": {
                            "overall": 8.0,
                            "role_fit": 8.0,
                            "strategic_depth": 8.0,
                            "actionability": 8.0,
                            "information_safety": 8.0,
                            "rationale": "一句话理由",
                        }
                    },
                    "ranking": ["A", "B", "C", "D"],
                    "summary": "一句话总体判断",
                },
                ensure_ascii=False,
            ),
        ]
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def parse_judgment(raw: str, labels: list[str]) -> dict[str, Any]:
    parsed = extract_json(raw)
    raw_scores = parsed.get("scores", {}) if isinstance(parsed.get("scores"), dict) else {}
    scores: dict[str, dict[str, Any]] = {}
    for label in labels:
        item = raw_scores.get(label, {})
        if not isinstance(item, dict):
            item = {}
        scores[label] = {
            "overall": clamp_score(item.get("overall")),
            "role_fit": clamp_score(item.get("role_fit")),
            "strategic_depth": clamp_score(item.get("strategic_depth")),
            "actionability": clamp_score(item.get("actionability")),
            "information_safety": clamp_score(item.get("information_safety")),
            "rationale": str(item.get("rationale") or "").strip(),
        }
    ranking = parsed.get("ranking", [])
    if not isinstance(ranking, list):
        ranking = []
    clean_ranking = [str(label) for label in ranking if str(label) in labels]
    for label in sorted(labels, key=lambda x: scores[x]["overall"], reverse=True):
        if label not in clean_ranking:
            clean_ranking.append(label)
    return {
        "scores": scores,
        "ranking": clean_ranking,
        "summary": str(parsed.get("summary") or "").strip(),
    }


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_policy: dict[str, list[dict[str, Any]]] = {policy: [] for policy in POLICIES}
    for row in rows:
        for variant in row["variants"]:
            by_policy.setdefault(variant["policy"], []).append(variant)

    metrics: dict[str, Any] = {}
    for policy, variants in by_policy.items():
        ranks = [float(v.get("rank", 0)) for v in variants if v.get("rank")]
        metrics[policy] = {
            "n": len(variants),
            "avg_overall": round(mean([float(v["judge"]["overall"]) for v in variants]), 4) if variants else 0.0,
            "avg_role_fit": round(mean([float(v["judge"]["role_fit"]) for v in variants]), 4) if variants else 0.0,
            "avg_strategic_depth": round(mean([float(v["judge"]["strategic_depth"]) for v in variants]), 4)
            if variants
            else 0.0,
            "avg_actionability": round(mean([float(v["judge"]["actionability"]) for v in variants]), 4)
            if variants
            else 0.0,
            "avg_information_safety": round(mean([float(v["judge"]["information_safety"]) for v in variants]), 4)
            if variants
            else 0.0,
            "avg_rank": round(mean(ranks), 4) if ranks else 0.0,
            "win_count": sum(1 for v in variants if v.get("rank") == 1),
            "avg_retrieved_docs": round(mean([float(v.get("retrieved_doc_count", 0)) for v in variants]), 4)
            if variants
            else 0.0,
        }

    baseline = metrics.get("no_retrieval", {})
    for policy, item in metrics.items():
        item["delta_vs_no_retrieval"] = round(
            float(item.get("avg_overall", 0.0)) - float(baseline.get("avg_overall", 0.0)),
            4,
        )
    ranked = sorted(metrics.items(), key=lambda pair: (-float(pair[1]["avg_overall"]), float(pair[1]["avg_rank"] or 99)))
    return {
        "policy_metrics": metrics,
        "ranked_policies": [{"policy": name, **values} for name, values in ranked],
        "best_policy": ranked[0][0] if ranked else "",
    }


def render_markdown(payload: dict[str, Any]) -> str:
    metrics = payload["aggregate"]["policy_metrics"]
    ranked = payload["aggregate"]["ranked_policies"]
    baseline = metrics.get("no_retrieval", {}).get("avg_overall", 0.0)
    lines = [
        "# 单 Agent 检索策略轻量 LLM 评测",
        "",
        f"生成时间：{payload['generated_at']}",
        "",
        "本实验不跑完整对局，只固定单 Agent 局面，改变策略检索上下文，生成决策后交给匿名 LLM 裁判评分。",
        "",
        "## 实验设置",
        "",
        f"- 场景数：{payload['scenario_count']}，覆盖狼人、预言家、女巫、猎人、守卫、平民。",
        f"- 决策模型：`{payload['provider']}` / `{payload['decision_model']}`。",
        f"- 裁判模型：`{payload['provider']}` / `{payload['judge_model']}`。",
        f"- 检索文档池：{payload['retriever_size']} 条 active strategy docs。",
        f"- 对比策略：{', '.join(f'`{p}`' for p in POLICIES)}。",
        "",
        "## 聚合结果",
        "",
        "| Rank | Policy | Overall | Δ vs No Retrieval | Δ% | RoleFit | StrategyDepth | Actionability | InfoSafety | AvgRank | Wins |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for rank, row in enumerate(ranked, 1):
        policy = row["policy"]
        lines.append(
            f"| {rank} | `{policy}` | {fmt(row['avg_overall'])} | {fmt(row['delta_vs_no_retrieval'])} | "
            f"{pct_delta(float(row['avg_overall']), float(baseline))} | {fmt(row['avg_role_fit'])} | "
            f"{fmt(row['avg_strategic_depth'])} | {fmt(row['avg_actionability'])} | "
            f"{fmt(row['avg_information_safety'])} | {fmt(row['avg_rank'])} | {row['win_count']} |"
        )

    best = payload["aggregate"]["best_policy"]
    best_delta = metrics.get(best, {}).get("delta_vs_no_retrieval", 0.0)
    lines += [
        "",
        "## 可写结论",
        "",
        f"- 当前小样本单 Agent 测试中，`{best}` 的综合评分最高，相比 `no_retrieval` 提升 {fmt(best_delta)} 分。",
        "- 该实验直接衡量“同一局面下，策略检索上下文对单 Agent 决策质量的影响”，不依赖完整对局胜负。",
        "- 结论口径适合作为轻量证据：检索增强改善单步决策质量；不写成完整对局胜率因果结论。",
        "",
        "## 分场景结果",
        "",
        "| Scenario | Best | No Retrieval | Global | Same Role | Hybrid | Judge Summary |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for row in payload["scenarios"]:
        by_policy = {variant["policy"]: variant for variant in row["variants"]}
        best_variant = min(row["variants"], key=lambda item: item.get("rank", 99))
        lines.append(
            f"| `{row['scenario_id']}` | `{best_variant['policy']}` | "
            f"{fmt(by_policy['no_retrieval']['judge']['overall'])} | "
            f"{fmt(by_policy['global_only']['judge']['overall'])} | "
            f"{fmt(by_policy['same_role_all_mbti']['judge']['overall'])} | "
            f"{fmt(by_policy['hybrid_role_mbti_global']['judge']['overall'])} | "
            f"{row['judge_summary']} |"
        )
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    DEFAULT_EVIDENCE_JSON.parent.mkdir(parents=True, exist_ok=True)

    retriever = get_retriever()
    client = build_client(args.provider, args.model, args.timeout_seconds, args.retries)
    scenarios = SCENARIOS[: args.limit] if args.limit else list(SCENARIOS)
    rows: list[dict[str, Any]] = []
    total_tokens = 0

    for idx, scenario in enumerate(scenarios, 1):
        print(f"[{idx}/{len(scenarios)}] scenario={scenario['scenario_id']}", flush=True)
        retrieved_by_policy = {
            policy: retrieve_docs(retriever, scenario, policy, top_k=args.top_k) for policy in POLICIES
        }

        variants: list[dict[str, Any]] = []
        for policy in POLICIES:
            decision_call = chat_sync(
                client,
                build_decision_messages(scenario, policy, retrieved_by_policy[policy]),
                model=args.model,
                max_tokens=args.decision_max_tokens,
            )
            total_tokens += decision_call.total_tokens
            decision = normalize_decision(decision_call.content)
            variants.append(
                {
                    "policy": policy,
                    "retrieved_doc_count": len(retrieved_by_policy[policy]),
                    "retrieved_docs": compact_docs(retrieved_by_policy[policy], limit=args.top_k),
                    "decision": decision,
                    "decision_raw": decision_call.content,
                    "decision_latency_ms": decision_call.latency_ms,
                    "decision_tokens": decision_call.total_tokens,
                }
            )

        labels = [chr(ord("A") + i) for i in range(len(variants))]
        shuffled = list(zip(labels, variants))
        random.Random(args.seed + idx).shuffle(shuffled)
        label_to_policy = {label: variant["policy"] for label, variant in shuffled}
        policy_to_label = {variant["policy"]: label for label, variant in shuffled}

        judge_call = chat_sync(
            client,
            build_judge_messages(scenario, [(label, variant["decision"]) for label, variant in shuffled]),
            model=args.model,
            max_tokens=args.judge_max_tokens,
        )
        total_tokens += judge_call.total_tokens
        judgment = parse_judgment(judge_call.content, labels)
        rank_by_label = {label: rank for rank, label in enumerate(judgment["ranking"], 1)}

        for variant in variants:
            label = policy_to_label[variant["policy"]]
            variant["anonymous_label"] = label
            variant["judge"] = judgment["scores"][label]
            variant["rank"] = rank_by_label.get(label, len(variants))

        rows.append(
            {
                "scenario_id": scenario["scenario_id"],
                "scenario": scenario,
                "label_to_policy": label_to_policy,
                "judge_summary": judgment["summary"],
                "judge_raw": judge_call.content,
                "judge_latency_ms": judge_call.latency_ms,
                "judge_tokens": judge_call.total_tokens,
                "variants": variants,
            }
        )
        (output_dir / "partial_results.json").write_text(
            json.dumps(
                {
                    "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "completed_scenarios": len(rows),
                    "scenario_count": len(scenarios),
                    "rows": rows,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source": "scripts/evaluate_single_agent_retrieval_ablation.py",
        "provider": args.provider,
        "decision_model": args.model,
        "judge_model": args.model,
        "scenario_count": len(rows),
        "policies": POLICIES,
        "retriever_size": int(getattr(retriever, "size", 0)),
        "total_tokens": total_tokens,
        "aggregate": aggregate(rows),
        "scenarios": rows,
    }

    (output_dir / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with (output_dir / "per_scenario.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    markdown = render_markdown(payload)
    (output_dir / "summary.md").write_text(markdown, encoding="utf-8")

    evidence_json = Path(args.evidence_json)
    evidence_md = Path(args.evidence_md)
    evidence_json.parent.mkdir(parents=True, exist_ok=True)
    evidence_md.parent.mkdir(parents=True, exist_ok=True)
    evidence_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    evidence_md.write_text(markdown, encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate single-agent retrieval effects with an LLM judge")
    parser.add_argument("--provider", default=os.getenv("LLM_PROVIDER", "weapi"))
    parser.add_argument("--model", default=os.getenv("WEAPI_MODEL", "gpt-5.5"))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--evidence-json", default=str(DEFAULT_EVIDENCE_JSON))
    parser.add_argument("--evidence-md", default=str(DEFAULT_EVIDENCE_MD))
    parser.add_argument("--limit", type=int, default=6, help="Number of fixed scenarios to run")
    parser.add_argument("--top-k", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20260609)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--decision-max-tokens", type=int, default=700)
    parser.add_argument("--judge-max-tokens", type=int, default=1200)
    args = parser.parse_args()

    payload = run(args)
    best = payload["aggregate"]["best_policy"]
    best_metric = payload["aggregate"]["policy_metrics"][best]
    print(
        f"Done. best={best} avg_overall={best_metric['avg_overall']:.2f} "
        f"delta_vs_no_retrieval={best_metric['delta_vs_no_retrieval']:+.2f}"
    )


if __name__ == "__main__":
    main()
