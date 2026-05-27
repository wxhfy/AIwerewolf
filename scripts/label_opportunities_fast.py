"""Phase 2 fast: Parallel labeling of DecisionOpportunity samples via Doubao.

Uses ThreadPoolExecutor to speed up labeling (8 workers).
Each sample is single-labeled for MVP; consistency check via random retry.

Run: python scripts/label_opportunities_fast.py [--limit N] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv()

from backend.llm import create_client

# ---- Sampling targets ----
SAMPLE_TARGETS = {
    "Witch": 100, "Guard": 100, "Hunter": 100,
    "Seer": 70, "Werewolf": 70, "Villager": 60,
}
TOTAL_TARGET = sum(SAMPLE_TARGETS.values())  # 500

# ---- Labeling prompts ----

SINGLE_ACTION_PROMPT = """你是狼人杀 Agent 复盘标注员。评估以下动作的质量。

评估维度：
1. 当时信息是否支持这个动作
2. 是否有更优合法动作
3. 是否符合角色目标
4. 是否有公开证据
5. 是否存在明显风险

输出 JSON：
{{"quality_score": 0-100, "role_alignment": 0-100, "risk_level": "low|medium|high", "confidence": 0.0-1.0, "reason": "简要理由"}}

=== 局势 ===
角色：{role}，阶段：{phase}，第{day}天
公开信息：{public}
私有信息：{private}

=== 执行动作 ===
{action}
"""

PAIRWISE_PROMPT = """你是狼人杀 Agent 复盘标注员。比较同角色同一局中的两个动作 A 和 B。

评估：A_better / B_better / tie / uncertain
考虑：信息支持度、角色目标符合度、战略价值、风险

输出 JSON：
{{"label": "A_better|B_better|tie|uncertain", "strength": "weak|medium|strong", "confidence": 0.0-1.0, "reason": "简要理由"}}

=== 角色 {role} ===
动作A ({type_a}): {action_a}
动作B ({type_b}): {action_b}

公开信息：{public}
"""

SPEECH_PROMPT = """你是狼人杀 Agent 复盘标注员。评估发言质量。

维度（goal doc §2.7）：
- groundedness 基于真实事件 0-25
- stance_clarity 明确踩/保/归票 0-20
- consistency 前后一致 0-20
- strategic_value 推动阵营目标 0-20
- information_safety 不泄露私有信息 0-15

输出 JSON：
{{"groundedness": 0-25, "stance_clarity": 0-20, "consistency": 0-20, "strategic_value": 0-20, "information_safety": 0-15, "confidence": 0.0-1.0, "reason": "简要理由"}}

=== 发言文本 ===
{speech}

角色：{role}，第{day}天，{phase}
公开信息：{public}
"""

MISTAKE_PROMPT = """你是狼人杀 Agent 复盘标注员。评估错误严重度。

考虑：对胜负影响、是否可挽回、是否关键轮次、损失角色价值

输出 JSON：
{{"severity_score": 0-100, "is_critical": true/false, "recoverable": true/false, "confidence": 0.0-1.0, "reason": "简要理由"}}

=== 局势 ===
角色：{role}，第{day}天
动作：{action}
结果：{outcome}
"""


def load_opps(path: str = "data/health/opportunities.jsonl") -> list[dict]:
    opps = []
    with open(ROOT / path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                opps.append(json.loads(line))
    return opps


def sample_opps(opps: list[dict]) -> list[dict]:
    """Sample opportunities stratified by role to meet targets."""
    by_role = defaultdict(list)
    for opp in opps:
        by_role[opp["role"]].append(opp)

    sampled = []
    for role, target_n in SAMPLE_TARGETS.items():
        pool = by_role.get(role, [])
        n = min(target_n, len(pool))
        sampled.extend(random.sample(pool, n))

    random.shuffle(sampled)
    return sampled


def build_label_task(opp: dict) -> dict[str, Any]:
    """Build a labeling task from one opportunity."""
    role = opp.get("role", "")
    op_type = opp.get("opportunity_type", "")
    phase = opp.get("phase", "")
    day = opp.get("day", 1)
    public = opp.get("public_context_summary", "")[:800]
    private = opp.get("private_context_summary", "")[:600]
    action = json.dumps(opp.get("chosen_action", {}), ensure_ascii=False)[:500]
    outcome = json.dumps(opp.get("outcome_features", {}), ensure_ascii=False)[:200]

    # Determine task type (use .replace() to avoid str.format brace issues)
    if op_type == "speech":
        speech_text = str(opp.get("chosen_action", {}).get("speech") or public)[:1000]
        prompt = (SPEECH_PROMPT
            .replace("{role}", str(role)).replace("{day}", str(day))
            .replace("{phase}", str(phase)).replace("{speech}", speech_text)
            .replace("{public}", public))
        task_type = "speech_quality"
    elif op_type in ("witch_poison", "witch_skip", "hunter_shot") and "died" in outcome:
        prompt = (MISTAKE_PROMPT
            .replace("{role}", str(role)).replace("{day}", str(day))
            .replace("{action}", action).replace("{outcome}", outcome))
        task_type = "mistake_severity"
    else:
        prompt = (SINGLE_ACTION_PROMPT
            .replace("{role}", str(role)).replace("{phase}", str(phase))
            .replace("{day}", str(day)).replace("{public}", public)
            .replace("{private}", private).replace("{action}", action))
        task_type = "single_action"

    return {
        "opportunity_id": opp["opportunity_id"],
        "role": role,
        "opportunity_type": op_type,
        "task_type": task_type,
        "day": day,
        "prompt": prompt,
    }


_SHARED_CLIENT = None

def _get_client():
    global _SHARED_CLIENT
    if _SHARED_CLIENT is None:
        _SHARED_CLIENT = create_client(
            provider="doubao",
            model=os.environ.get("DOUBAO_MODEL", "ep-20260514115354-k4jz4"),
            api_key=os.environ["DOUBAO_API_KEY"],
            base_url=os.environ["DOUBAO_BASE_URL"],
        )
        _SHARED_CLIENT.timeout = 60.0
    return _SHARED_CLIENT


def call_doubao(prompt: str, temperature: float = 0.3) -> dict[str, Any]:
    """Call Doubao API and parse JSON response."""
    client = _get_client()
    response = client.chat_sync(
        [{"role": "user", "content": prompt}],
        max_tokens=512,
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
    return {"parse_error": True, "raw": text[:200]}


def label_one(task: dict) -> dict:
    """Label one sample with retry on failure."""
    for attempt in range(3):
        try:
            result = call_doubao(task["prompt"], temperature=0.3)
            if not result.get("parse_error"):
                return {**task, "label": result, "labeled_at": time.strftime("%Y-%m-%dT%H:%M:%SZ")}
            time.sleep(1.0)
        except Exception as e:
            if attempt < 2:
                time.sleep(2.0)
            else:
                return {**task, "label": {"error": str(e)}, "labeled_at": time.strftime("%Y-%m-%dT%H:%M:%SZ")}
    return {**task, "label": result, "labeled_at": time.strftime("%Y-%m-%dT%H:%M:%SZ")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--output", default="data/health/labeled_opportunities.jsonl")
    args = ap.parse_args()

    random.seed(args.seed)

    print("Loading opportunities...")
    opps = load_opps()
    print(f"  {len(opps)} opportunities loaded")

    sampled = sample_opps(opps)
    print(f"  Sampled {len(sampled)} across {len(SAMPLE_TARGETS)} roles")
    for role in sorted(SAMPLE_TARGETS):
        n = sum(1 for o in sampled if o["role"] == role)
        print(f"    {role}: {n}")

    if args.dry_run:
        for opp in sampled[:3]:
            task = build_label_task(opp)
            print(f"\n  Task: {task['task_type']} role={task['role']}")
            print(f"  Prompt ({len(task['prompt'])} chars): {task['prompt'][:200]}...")
        return 0

    # Resume: load already-labeled opportunity IDs
    output_path = ROOT / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    existing_ids = set()
    if output_path.exists():
        with open(output_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        existing_ids.add(json.loads(line)["opportunity_id"])
                    except (json.JSONDecodeError, KeyError):
                        pass
    if existing_ids:
        print(f"  Resuming: {len(existing_ids)} already labeled, skipping...")
        sampled = [o for o in sampled if o["opportunity_id"] not in existing_ids]

    # Build tasks
    tasks = [build_label_task(opp) for opp in sampled]
    if args.limit:
        tasks = tasks[:args.limit]

    if not tasks:
        print("All samples already labeled!")
        _generate_report(output_path, len(existing_ids), 0)
        return 0

    print(f"\nLabeling {len(tasks)} new samples with {args.workers} workers...")

    completed = 0
    errors = 0
    start_time = time.time()

    # Append mode to preserve existing data
    with open(output_path, "a", encoding="utf-8") as f:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(label_one, task): task for task in tasks}
            for future in as_completed(futures):
                result = future.result()
                f.write(json.dumps(result, ensure_ascii=False) + "\n")
                f.flush()
                completed += 1
                if result["label"].get("parse_error") or result["label"].get("error"):
                    errors += 1
                if completed % 20 == 0:
                    elapsed = time.time() - start_time
                    rate = completed / max(elapsed, 1)
                    eta = (len(tasks) - completed) / max(rate, 0.01)
                    print(f"  [{completed}/{len(tasks)}] {rate:.1f}/s, errors={errors}, ETA={eta:.0f}s")

    total = len(existing_ids) + completed
    elapsed = time.time() - start_time
    print(f"\nDone: {completed} new + {len(existing_ids)} existing = {total} total in {elapsed:.0f}s ({completed/elapsed:.1f}/s)")
    print(f"Errors: {errors}")
    print(f"Output: {output_path}")

    # Generate label quality report
    _generate_report(output_path, total, errors)

    return 0


def _generate_report(output_path: Path, total: int, errors: int):
    """Generate label_quality_report.md."""
    labeled = []
    with open(output_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                labeled.append(json.loads(line))

    # Stats
    role_counts = Counter(item["role"] for item in labeled)
    type_counts = Counter(item["task_type"] for item in labeled)
    parse_errors = sum(1 for item in labeled if item["label"].get("parse_error") or item["label"].get("error"))

    # Quality score distribution
    quality_scores = []
    for item in labeled:
        qs = item["label"].get("quality_score")
        if qs is not None:
            quality_scores.append(qs)

    # Label distribution for pairwise
    pairwise_labels = Counter()
    for item in labeled:
        if item["task_type"] == "pairwise":
            pairwise_labels[item["label"].get("label", "?")] += 1

    lines = [
        "# Label Quality Report (Phase 2)",
        "",
        f"**Total labeled**: {total}",
        f"**Parse errors**: {parse_errors} ({parse_errors/max(total,1)*100:.1f}%)",
        f"**Success rate**: {(total-parse_errors)/max(total,1)*100:.1f}%",
        "",
        "## Per Role",
        "| Role | Count |",
        "|------|-------|",
    ]
    for role in sorted(role_counts):
        lines.append(f"| {role} | {role_counts[role]} |")

    lines += [
        "",
        "## Per Task Type",
        "| Type | Count |",
        "|------|-------|",
    ]
    for t, c in type_counts.most_common():
        lines.append(f"| {t} | {c} |")

    if quality_scores:
        import statistics
        lines += [
            "",
            "## Quality Score Distribution",
            f"Mean: {statistics.mean(quality_scores):.1f}",
            f"Median: {statistics.median(quality_scores):.1f}",
            f"Std: {statistics.stdev(quality_scores):.1f}" if len(quality_scores) > 1 else "Std: N/A",
            f"Min: {min(quality_scores):.1f}",
            f"Max: {max(quality_scores):.1f}",
        ]

    # Per-role score summary
    lines += [
        "",
        "## Per-Role Quality Score Summary",
        "| Role | Count | Mean Score | Median |",
        "|------|-------|------------|--------|",
    ]
    for role in sorted(role_counts):
        role_scores = [item["label"].get("quality_score", 0) or 0 for item in labeled if item["role"] == role]
        if role_scores:
            lines.append(f"| {role} | {len(role_scores)} | {statistics.mean(role_scores):.1f} | {statistics.median(role_scores):.1f} |")

    lines += [
        "",
        "## Notes",
        "- Labeled using Doubao API (single-label, temp=0.3)",
        "- Full double-label consistency check deferred to Phase 2.1",
        f"- Output saved to: {output_path}",
    ]

    report_path = Path(str(output_path).replace(".jsonl", "_quality_report.md"))
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report: {report_path}")


if __name__ == "__main__":
    raise SystemExit(main())
