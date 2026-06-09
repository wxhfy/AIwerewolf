"""Use Doubao LLM to extract cross-game strategic patterns from review reports.

Unlike the heuristic StrategyKnowledgeExtractor (which mechanically parses
structured fields), this feeds the review content to Doubao and asks it to
synthesize higher-quality strategic principles per role.

Output: strategy cards saved to data/health/doubao_strategies.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import text

from backend.db.database import SessionLocal
from backend.eval.track_b import reconstruct_review_report
from backend.llm import create_client

ROLE_ORDER = ["Seer", "Witch", "Guard", "Hunter", "Werewolf", "Villager"]

EXTRACTION_PROMPT = """你是一位狼人杀策略分析师。下面是从多局 AI 狼人杀对局的复盘报告中提取的玩家表现数据。

请分析这些数据，为【{role}】角色总结出 5-8 条可操作的策略原则。

要求：
1. 每条策略包含：触发条件、推荐行动、理由、常见错误
2. 策略要具体，不要泛泛而谈（例如"第1夜应该验谁"而不是"要好好验人"）
3. 区分不同阶段（首夜/第一白天/中后期）
4. 基于数据中的实际表现模式，不是理论推演
5. 用中文输出

输出 JSON 格式：
{{
  "role": "{role}",
  "strategies": [
    {{
      "phase": "night_1|day_1|mid_game|late_game",
      "trigger": "触发条件描述",
      "action": "推荐的具体行动",
      "rationale": "理由",
      "common_mistake": "常见错误做法",
      "priority": "high|medium|low",
      "source_evidence": "数据中观察到的支撑模式（一句话）"
    }}
  ],
  "summary": "这个角色在数据中表现出的核心问题和提升方向（2-3句话）"
}}

以下是【{role}】角色的对局复盘数据：
{review_data}"""


def load_game_ids(label: str | None) -> list[str]:
    if label:
        path = ROOT / "data" / "health" / f"llm_batch_{label}.jsonl"
        if path.exists():
            return [
                json.loads(line)["game_id"] for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
            ]
    # Load from clean file
    clean_path = Path("/tmp/clean_llm_game_ids.json")
    if clean_path.exists():
        return json.loads(clean_path.read_text())
    return []


def collect_role_data(game_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    """Group review data by role, extracting player reviews + suggestions + bad cases."""

    db = SessionLocal()
    try:
        rows = db.execute(
            text("""
            SELECT pr.game_id, g.winner, pr.report_json
            FROM published_reviews pr
            JOIN games g ON g.id = pr.game_id
            WHERE pr.game_id IN :gids AND pr.publish_allowed = true
        """),
            {"gids": tuple(game_ids)},
        ).fetchall()

        role_data: dict[str, list[dict[str, Any]]] = {r: [] for r in ROLE_ORDER}
        for game_id, winner, report_json in rows:
            if not report_json:
                continue
            try:
                report = reconstruct_review_report(report_json)
            except Exception:
                continue

            for pr in report.player_reviews:
                role = getattr(pr, "role", None) or "Unknown"
                if role not in role_data:
                    continue
                alignment = getattr(pr, "alignment", "village")
                won = (winner == "wolf" and alignment == "wolf") or (winner == "village" and alignment == "village")
                role_data[role].append(
                    {
                        "game_id": game_id[:8],
                        "won": won,
                        "process_score": getattr(pr, "process_score", 0) or 0,
                        "adjusted_final_score": getattr(pr, "adjusted_final_score", 0) or 0,
                        "strengths": list(getattr(pr, "strengths", []) or [])[:3],
                        "weaknesses": list(getattr(pr, "weaknesses", []) or [])[:3],
                        "summary": getattr(pr, "overall_summary", "") or "",
                    }
                )

            # Also collect global strategy suggestions
            for s in getattr(report, "strategy_suggestions", []) or []:
                target = getattr(s, "target", "global") if getattr(s, "target_type", "") == "role" else "global"
                if target in role_data:
                    role_data[target].append(
                        {
                            "suggestion_type": getattr(s, "suggestion_type", ""),
                            "suggestion": getattr(s, "suggestion", ""),
                            "priority": getattr(s, "priority", "medium"),
                            "source": getattr(s, "source", ""),
                        }
                    )

        return role_data
    finally:
        db.close()


def build_role_prompt(role: str, data: list[dict[str, Any]], max_games: int = 15) -> str:
    """Build a prompt for Doubao with role-specific review data."""
    # Separate player reviews from suggestions
    reviews = [d for d in data if "process_score" in d]
    suggestions = [d for d in data if "suggestion" in d]

    # Sort reviews by process_score to show both good and bad examples
    reviews_sorted = sorted(reviews, key=lambda r: r.get("process_score", 0), reverse=True)
    min(max_games, len(reviews_sorted))

    lines = []
    lines.append(f"共 {len(reviews)} 局对局数据。以下是代表性样本：\n")

    # Top performers
    lines.append("## 高分玩家 (top 5)")
    for r in reviews_sorted[:5]:
        lines.append(f"- [{r['game_id']}] {'赢' if r['won'] else '输'} | process={r['process_score']:.1f}")
        if r.get("strengths"):
            lines.append(f"  优点: {'; '.join(r['strengths'][:2])}")
        if r.get("summary"):
            lines.append(f"  总结: {r['summary'][:200]}")

    # Bottom performers
    lines.append("\n## 低分玩家 (bottom 5)")
    for r in reviews_sorted[-5:]:
        lines.append(f"- [{r['game_id']}] {'赢' if r['won'] else '输'} | process={r['process_score']:.1f}")
        if r.get("weaknesses"):
            lines.append(f"  问题: {'; '.join(r['weaknesses'][:2])}")

    # Strategy suggestions
    if suggestions:
        lines.append(f"\n## 已有策略建议 ({len(suggestions)} 条)")
        for s in suggestions[:8]:
            lines.append(f"- [{s.get('priority', '?')}] {s.get('suggestion', '')[:200]}")

    return EXTRACTION_PROMPT.format(role=role, review_data="\n".join(lines))


def extract_with_doubao(prompt: str, model: str | None = None) -> dict[str, Any]:
    """Call Doubao to extract strategies."""
    import os

    resolved_model = model or os.environ.get("DOUBAO_MODEL")
    if not resolved_model:
        raise RuntimeError("DOUBAO_MODEL must be set for Doubao extraction scripts")

    client = create_client(
        provider="doubao",
        model=resolved_model,
        api_key=os.environ["DOUBAO_API_KEY"],
        base_url=os.environ["DOUBAO_BASE_URL"],
    )
    client.timeout = 180.0

    response = client.chat_sync(
        [{"role": "user", "content": prompt}],
        max_tokens=4096,
        temperature=0.3,
    )
    text = client.parse_response(response).strip()

    # Extract JSON from response
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON object
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
        return {"raw_response": text, "parse_error": True}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default=None, help="Batch label for game IDs")
    ap.add_argument("--roles", nargs="*", default=None, help="Roles to extract (default: all)")
    ap.add_argument("--output", default="data/health/doubao_strategies.json", help="Output file")
    ap.add_argument("--dry-run", action="store_true", help="Build prompts without calling API")
    args = ap.parse_args()

    game_ids = load_game_ids(args.label)
    print(f"Loading review data for {len(game_ids)} games...")
    role_data = collect_role_data(game_ids)

    for role in ROLE_ORDER:
        print(f"  {role}: {len(role_data[role])} records")

    roles_to_extract = args.roles or ROLE_ORDER
    all_results: dict[str, Any] = {}

    for role in roles_to_extract:
        data = role_data.get(role, [])
        if not data:
            print(f"\n  Skipping {role}: no data")
            continue

        prompt = build_role_prompt(role, data)
        print(f"\n=== {role} prompt: {len(prompt)} chars ===")

        if args.dry_run:
            print(prompt[:500] + "...")
            continue

        print("  Calling Doubao...")
        try:
            result = extract_with_doubao(prompt)
            all_results[role] = result
            n_strategies = len(result.get("strategies", []))
            print(f"  ✓ {role}: {n_strategies} strategies extracted")
            if result.get("summary"):
                print(f"    summary: {result['summary'][:120]}")
        except Exception as exc:
            print(f"  ✗ {role} failed: {exc}")
            all_results[role] = {"error": str(exc)}

    if not args.dry_run and all_results:
        output_path = ROOT / args.output
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(all_results, ensure_ascii=False, indent=2))
        print(f"\nSaved to {output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
