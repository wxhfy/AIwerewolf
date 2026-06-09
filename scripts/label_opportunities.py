"""Phase 2: Label DecisionOpportunity samples using Doubao LLM.

Constructs 300-500 labeled samples following the goal doc §7 specification:
  - Pairwise decision preference: 220
  - Single action quality: 120
  - Mistake severity: 100
  - Speech quality: 60

Each sample is double-labeled (temp=0.2, temp=0.7) for consistency check.
Inconsistent labels get need_human_review=true.

Run: python scripts/label_opportunities.py [--dry-run] [--role ROLE]
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv()

from backend.llm import create_client

# ---- Sampling targets (from goal doc §7.2) ----
SAMPLE_TARGETS = {
    "pairwise": {
        "total": 220,
        "per_role": {"Witch": 44, "Guard": 44, "Hunter": 44, "Seer": 32, "Werewolf": 32, "Villager": 24},
    },
    "single_action": {
        "total": 120,
        "per_role": {"Witch": 30, "Guard": 24, "Hunter": 24, "Seer": 16, "Werewolf": 14, "Villager": 12},
    },
    "mistake_severity": {
        "total": 100,
        "per_role": {"Witch": 16, "Guard": 22, "Hunter": 22, "Seer": 16, "Werewolf": 16, "Villager": 8},
    },
    "speech_quality": {
        "total": 60,
        "per_role": {"Witch": 10, "Guard": 10, "Hunter": 10, "Seer": 6, "Werewolf": 8, "Villager": 16},
    },
}

# ---- Labeling prompts (from goal doc §7.3) ----
PAIRWISE_PROMPT = """你是狼人杀 Agent 复盘标注员。

你不能只根据最终胜负判断动作好坏。
你必须基于：
1. 当时玩家可见信息
2. 该角色目标
3. 合法动作集合
4. 公开证据
5. 局部后果
6. 反事实替代动作

下面有两个动作选择 A 和 B，在同一局势下。

请判断哪个更好：
- A_better: A 明显更好
- B_better: B 明显更好
- tie: 大致相同
- uncertain: 信息不足以判断

输出 JSON：
{{
  "label": "A_better|B_better|tie|uncertain",
  "strength": "weak|medium|strong",
  "confidence": 0.0-1.0,
  "reason": "简要理由",
  "need_human_review": false
}}

=== 局势背景 ===
角色：{role}
阶段：{phase}
第{day}天
公开信息：{public_context}
私有信息：{private_context}

=== 动作 A ===
{action_a}

=== 动作 B ===
{action_b}
"""

SINGLE_ACTION_PROMPT = """你是狼人杀 Agent 复盘标注员。

请评估以下动作的质量（0-100分）。

评估维度：
1. 当时信息是否支持这个动作
2. 是否有更优合法动作
3. 是否符合角色目标
4. 是否有公开证据
5. 是否存在明显风险
6. 局部后果如何

输出 JSON：
{{
  "quality_score": 0-100,
  "reasoning_quality": 0-100,
  "strategic_value": 0-100,
  "risk_level": "low|medium|high",
  "confidence": 0.0-1.0,
  "reason": "简要理由",
  "need_human_review": false
}}

=== 局势背景 ===
角色：{role}
阶段：{phase}
第{day}天
公开信息：{public_context}
私有信息：{private_context}

=== 执行的动作 ===
{chosen_action}

=== 合法动作集合 ===
{legal_actions}
"""

MISTAKE_SEVERITY_PROMPT = """你是狼人杀 Agent 复盘标注员。

请评估以下错误动作的严重度（0-100分）。

严重度考虑因素：
1. 对阵营胜负的影响
2. 是否可以挽回
3. 是否处于关键轮次
4. 损失的角色价值

输出 JSON：
{{
  "severity_score": 0-100,
  "is_critical": true/false,
  "recoverable": true/false,
  "confidence": 0.0-1.0,
  "reason": "简要理由",
  "need_human_review": false
}}

=== 局势背景 ===
角色：{role}
阶段：{phase}
第{day}天
公开信息：{public_context}
私有信息：{private_context}

=== 错误动作 ===
{chosen_action}

=== 结果 ===
{outcome}
"""

SPEECH_QUALITY_PROMPT = """你是狼人杀 Agent 复盘标注员。

请评估以下发言的质量。

评估维度（来自goal doc §2.7）：
1. groundedness：是否基于真实公开事件（0-25）
2. stance_clarity：是否明确踩/保/归票（0-20）
3. consistency：前后发言和投票是否一致（0-20）
4. strategic_value：是否推动阵营目标（0-20）
5. information_safety：是否泄露私有信息或编造事实（0-15）

输出 JSON：
{{
  "groundedness": 0-25,
  "stance_clarity": 0-20,
  "consistency": 0-20,
  "strategic_value": 0-20,
  "information_safety": 0-15,
  "confidence": 0.0-1.0,
  "reason": "简要理由",
  "need_human_review": false
}}

=== 发言 ===
{speech_text}

=== 局势背景 ===
角色：{role}，第{day}天，阶段：{phase}
公开信息：{public_context}
"""


def load_opportunities(path: str = "data/health/opportunities.jsonl") -> list[dict]:
    opps = []
    with open(ROOT / path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                opps.append(json.loads(line))
    return opps


def sample_opportunities(opps: list[dict]) -> dict[str, list[dict]]:
    """Sample opportunities per target distribution, stratified by role."""
    by_role_type: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))

    for opp in opps:
        op_type = opp["opportunity_type"]
        role = opp["role"]
        # Map opportunity types to sample categories
        if op_type in ("speech",):
            by_role_type["speech_quality"][role].append(opp)
            by_role_type["single_action"][role].append(opp)
        elif op_type in ("vote", "guard_protect", "werewolf_kill", "hunter_shot"):
            by_role_type["single_action"][role].append(opp)
            by_role_type["pairwise"][role].append(opp)
        else:
            by_role_type["single_action"][role].append(opp)

    sampled: dict[str, list[dict]] = {}
    for category, targets in SAMPLE_TARGETS.items():
        sampled[category] = []
        for role, target_n in targets["per_role"].items():
            pool = by_role_type.get(category, {}).get(role, [])
            if pool:
                n = min(target_n, len(pool))
                sampled[category].extend(random.sample(pool, n))

    return sampled


def create_doubao_client():
    model = os.environ.get("DOUBAO_MODEL")
    if not model:
        raise RuntimeError("DOUBAO_MODEL must be set for Doubao extraction scripts")
    return create_client(
        provider="doubao",
        model=model,
        api_key=os.environ["DOUBAO_API_KEY"],
        base_url=os.environ["DOUBAO_BASE_URL"],
    )


def call_doubao(client, prompt: str, temperature: float = 0.2) -> dict[str, Any]:
    """Call Doubao and parse JSON response."""
    client.timeout = 120.0
    response = client.chat_sync(
        [{"role": "user", "content": prompt}],
        max_tokens=1024,
        temperature=temperature,
    )
    text = client.parse_response(response).strip()

    # Extract JSON
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1].strip()

    try:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
    except (json.JSONDecodeError, ValueError):
        pass

    return {"raw_response": text, "parse_error": True}


def build_pairwise_sample(opp_a: dict, opp_b: dict) -> dict[str, Any]:
    """Build a pairwise comparison sample from two opportunities of same role."""
    prompt = PAIRWISE_PROMPT.format(
        role=opp_a["role"],
        phase=f"{opp_a['phase']} / {opp_b['phase']}",
        day=opp_a["day"],
        public_context=opp_a.get("public_context_summary", ""),
        private_context=opp_a.get("private_context_summary", "")[:800],
        action_a=json.dumps(opp_a["chosen_action"], ensure_ascii=False)[:500],
        action_b=json.dumps(opp_b["chosen_action"], ensure_ascii=False)[:500],
    )
    return {
        "type": "pairwise",
        "opportunity_a_id": opp_a["opportunity_id"],
        "opportunity_b_id": opp_b["opportunity_id"],
        "role": opp_a["role"],
        "prompt": prompt,
    }


def build_single_action_sample(opp: dict) -> dict[str, Any]:
    prompt = SINGLE_ACTION_PROMPT.format(
        role=opp["role"],
        phase=opp["phase"],
        day=opp["day"],
        public_context=opp.get("public_context_summary", ""),
        private_context=opp.get("private_context_summary", "")[:800],
        chosen_action=json.dumps(opp["chosen_action"], ensure_ascii=False)[:500],
        legal_actions=json.dumps(opp.get("legal_actions", []), ensure_ascii=False)[:300],
    )
    return {"type": "single_action", "opportunity_id": opp["opportunity_id"], "role": opp["role"], "prompt": prompt}


def build_speech_sample(opp: dict) -> dict[str, Any]:
    speech_text = opp.get("chosen_action", {}).get("speech") or opp.get("chosen_action", {}).get("text", "")
    if not speech_text:
        speech_text = opp.get("public_context_summary", "")
    prompt = SPEECH_QUALITY_PROMPT.format(
        role=opp["role"],
        phase=opp["phase"],
        day=opp["day"],
        speech_text=str(speech_text)[:1000],
        public_context=opp.get("public_context_summary", ""),
    )
    return {"type": "speech_quality", "opportunity_id": opp["opportunity_id"], "role": opp["role"], "prompt": prompt}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Build prompts without calling API")
    ap.add_argument("--limit", type=int, default=0, help="Limit samples per category")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--output", default="data/health/labeled_opportunities.jsonl")
    args = ap.parse_args()

    random.seed(args.seed)

    print("Loading opportunities...")
    opps = load_opportunities()
    print(f"  {len(opps)} opportunities loaded")

    sampled = sample_opportunities(opps)
    total = sum(len(v) for v in sampled.values())
    print(f"  Sampled {total} across {len(sampled)} categories")

    if args.dry_run:
        for cat, items in sampled.items():
            print(f"\n{cat}: {len(items)} samples")
            if items:
                print(f"  Sample prompt ({len(items[0].get('prompt', ''))} chars)")
                print(f"  First 200 chars: {items[0].get('prompt', '')[:200]}")
        return 0

    # Build prompts
    all_samples: list[dict] = []
    for cat, items in sampled.items():
        if cat == "pairwise":
            # Build pairwise from pairs within same role
            by_role: dict[str, list[dict]] = defaultdict(list)
            for opp in items:
                by_role[opp["role"]].append(opp)
            for _role, role_opps in by_role.items():
                random.shuffle(role_opps)
                for i in range(0, len(role_opps) - 1, 2):
                    sample = build_pairwise_sample(role_opps[i], role_opps[i + 1])
                    all_samples.append(sample)
        elif cat == "speech_quality":
            for opp in items:
                sample = build_speech_sample(opp)
                all_samples.append(sample)
        else:
            for opp in items:
                sample = build_single_action_sample(opp)
                sample["type"] = cat  # single_action or mistake_severity
                all_samples.append(sample)

    if args.limit:
        all_samples = all_samples[: args.limit]

    print(f"\nBuilt {len(all_samples)} labeling prompts")
    print("Calling Doubao for double-labeling...")

    client = create_doubao_client()

    output_path = ROOT / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)

    labeled_count = 0
    inconsistent_count = 0

    with open(output_path, "w", encoding="utf-8") as f:
        for i, sample in enumerate(all_samples):
            prompt = sample["prompt"]
            try:
                result_cold = call_doubao(client, prompt, temperature=0.2)
                time.sleep(0.3)
                result_warm = call_doubao(client, prompt, temperature=0.7)
            except Exception as e:
                print(f"  ERROR sample {i}: {e}")
                continue

            # Consistency check
            is_consistent = _check_consistency(sample["type"], result_cold, result_warm)
            if not is_consistent:
                inconsistent_count += 1

            labeled = {
                **sample,
                "label_cold": result_cold,
                "label_warm": result_warm,
                "consistent": is_consistent,
                "need_human_review": not is_consistent,
                "labeled_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            f.write(json.dumps(labeled, ensure_ascii=False) + "\n")
            labeled_count += 1

            if (i + 1) % 10 == 0:
                print(f"  Labeled {i + 1}/{len(all_samples)}, {inconsistent_count} inconsistent")

    print(f"\nLabeled {labeled_count} samples → {output_path}")
    print(
        f"Inconsistent (need human review): {inconsistent_count} ({inconsistent_count / max(labeled_count, 1) * 100:.1f}%)"
    )

    # Generate label quality report
    _generate_label_report(output_path, inconsistent_count, labeled_count)

    return 0


def _check_consistency(sample_type: str, cold: dict, warm: dict) -> bool:
    """Check if cold and warm labels are consistent."""
    if cold.get("parse_error") or warm.get("parse_error"):
        return False
    if sample_type == "pairwise":
        return cold.get("label") == warm.get("label")
    if sample_type in ("single_action", "mistake_severity"):
        c_score = cold.get("quality_score") or cold.get("severity_score") or 0
        w_score = warm.get("quality_score") or warm.get("severity_score") or 0
        return abs(c_score - w_score) <= 20  # Within 20 points
    if sample_type == "speech_quality":
        c_total = sum(
            cold.get(k, 0)
            for k in ["groundedness", "stance_clarity", "consistency", "strategic_value", "information_safety"]
        )
        w_total = sum(
            warm.get(k, 0)
            for k in ["groundedness", "stance_clarity", "consistency", "strategic_value", "information_safety"]
        )
        return abs(c_total - w_total) <= 15  # Within 15 points
    return True


def _generate_label_report(output_path, inconsistent_count, total):
    lines = [
        "# Label Quality Report (Phase 2)",
        "",
        f"**Total labeled**: {total}",
        f"**Inconsistent**: {inconsistent_count} ({inconsistent_count / max(total, 1) * 100:.1f}%)",
        f"**Need human review**: {inconsistent_count}",
        "",
        "## Consistency Check Method",
        "- Pairwise: label must match (A_better/B_better/tie/uncertain)",
        "- Single action: quality_score diff ≤ 20",
        "- Mistake severity: severity_score diff ≤ 20",
        "- Speech quality: total score diff ≤ 15",
        "",
        "## Notes",
        f"- Labeled samples saved to: {output_path}",
        "- Each sample has label_cold (temp=0.2) and label_warm (temp=0.7)",
        "- Inconsistent samples have need_human_review=true",
        "- Goal doc recommends ≥20% human spot-check on Witch poison, Guard protect, Hunter restraint",
    ]
    report_path = Path(output_path).with_suffix(".md")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Label quality report → {report_path}")


if __name__ == "__main__":
    raise SystemExit(main())
