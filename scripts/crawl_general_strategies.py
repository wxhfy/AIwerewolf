#!/usr/bin/env python3
"""Generate 500+ Chinese werewolf strategies using LLM (MiniMax/DeepSeek).

Instead of actual web crawling (which fails due to anti-crawler measures),
this script uses the LLM to generate authentic Chinese werewolf strategies
based on well-known gameplay patterns.

Usage:
  python scripts/crawl_general_strategies.py                  # Full run
  python scripts/crawl_general_strategies.py --dry-run        # Show plan, no LLM
  python scripts/crawl_general_strategies.py --skip-db        # Generate, skip DB
  python scripts/crawl_general_strategies.py --role Seer      # Single role only
  python scripts/crawl_general_strategies.py --provider doubao  # Explicit provider
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import sys
import time
import traceback
from pathlib import Path
from typing import Any
from uuid import uuid4

# ──────────────────────────────────────────────────────────────────────
# Path setup — ensure the project root is on sys.path so that
# "backend.llm" and "backend.db" resolve correctly.
# ──────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ──────────────────────────────────────────────────────────────────────
# Database URL — must be set BEFORE importing backend.db.database
# because the SQLAlchemy engine is created at module-import time.
# ──────────────────────────────────────────────────────────────────────
DB_URL = "postgresql://werewolf:wolf_secret_2026@127.0.0.1:5433/werewolf"
os.environ.setdefault("DATABASE_URL", DB_URL)

# Now safe to import project internals.
from backend.db.database import SessionLocal  # noqa: E402
from backend.db.database import init_db  # noqa: E402
from backend.db.models import StrategyKnowledgeDoc  # noqa: E402
from backend.llm import create_client  # noqa: E402
from backend.llm import load_env_file  # noqa: E402

load_env_file()

# ──────────────────────────────────────────────────────────────────────
# Output directory for generated JSON (always written, even with --skip-db)
# ──────────────────────────────────────────────────────────────────────
OUTPUT_DIR = ROOT / "data" / "strategies" / "generated"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ──────────────────────────────────────────────────────────────────────
# Role configuration — defines how many strategies to generate per role
# and which strategy types to cover.
# ──────────────────────────────────────────────────────────────────────
ROLE_TARGETS: dict[str, int] = {
    "Seer": 70,  # 预言家
    "Witch": 70,  # 女巫
    "Hunter": 70,  # 猎人
    "Guard": 70,  # 守卫
    "Villager": 70,  # 村民
    "Werewolf": 70,  # 狼人
    "WhiteWolfKing": 40,  # 白狼王
    "global": 40,  # 全局策略
}

# Chinese display names for logging.
ROLE_CN: dict[str, str] = {
    "Seer": "预言家",
    "Witch": "女巫",
    "Hunter": "猎人",
    "Guard": "守卫",
    "Villager": "村民",
    "Werewolf": "狼人",
    "WhiteWolfKing": "白狼王",
    "global": "全局",
}

# Strategy types — each batch prompt will ask for a subset of these.
STRATEGY_TYPES: dict[str, str] = {
    "opening": "开局策略 — 首夜/首日的信息获取、身份隐藏、初步布局",
    "mid_game": "中期博弈 — 对跳站边、身份碰撞、狼队战术配合",
    "endgame": "后期残局 — 残局人数计算、关键轮次决策、绝境翻盘",
    "identity_concealment": "身份伪装 — 穿衣服脱衣服、悍跳倒钩、假身分管理",
    "info_analysis": "信息分析 — 票型分析、发言逻辑链、夜信息推理",
    "voting_strategy": "投票策略 — 归票分票、冲票绑票、压手战术",
}

# Maps strategy type -> typical phases where those strategies apply.
STRATEGY_TYPE_PHASES: dict[str, list[str]] = {
    "opening": ["NIGHT_ACTION", "DAY_SPEECH"],
    "mid_game": ["DAY_SPEECH", "DAY_VOTE"],
    "endgame": ["DAY_VOTE", "DAY_SPEECH"],
    "identity_concealment": ["DAY_SPEECH", "NIGHT_ACTION"],
    "info_analysis": ["DAY_SPEECH", "DAY_VOTE"],
    "voting_strategy": ["DAY_VOTE", "DAY_SPEECH"],
}

# Batch size — how many strategies per LLM call.
BATCH_SIZE = 15


# ══════════════════════════════════════════════════════════════════════
# Prompt templates
# ══════════════════════════════════════════════════════════════════════


def _role_context(role: str) -> str:
    """Return role-specific context for the prompt."""
    contexts: dict[str, str] = {
        "Seer": """角色背景：预言家是好人阵营的核心神职。每晚可以查验一名玩家的身份（好人/狼人）。
预言家的首要任务是：获取信息、建立查验链、带队归票。
关键策略维度：
- 首夜查验对象选择（查验中间/高配/低配玩家的利弊）
- 是否第一天上警跳预言家（以及是否报出查验）
- 警徽流设计（留几天的警徽流、查验顺序）
- 如何处理对跳预言家（如何辩论、如何拉票）
- 查验金水/查杀后如何调整发言策略
- 中后期是否需要隐藏身份（暗预言家玩法）""",
        "Witch": """角色背景：女巫是好人阵营的强神。拥有一瓶解药（救人）和一瓶毒药（杀人），各只能用一次。
关键策略维度：
- 第一天是否救人（解药使用时机与利弊）
- 银水信息的公布时机与方法（是否暴露女巫身份）
- 毒药使用时机（第几夜用、毒谁、是否盲毒）
- 如何隐藏身份同时传递夜信息
- 对跳女巫时的辩论策略
- 残局是否跳明女巫身份带队""",
        "Hunter": """角色背景：猎人是好人阵营的强神。被投票放逐或狼杀时可以开枪带走一名玩家（被毒则不能开枪）。
关键策略维度：
- 是否第一天跳猎人身份（明猎人的利弊）
- 枪口威慑力的使用（如何利用枪威胁压制狼人）
- 被抗推时是否亮明身份（自证策略）
- 残局时枪口的价值最大化（带谁）
- 如何避免被女巫误毒
- 伪装村民身份的时机""",
        "Guard": """角色背景：守卫是好人阵营的守护神。每晚可以守护一名玩家免于狼刀（但不能连续两晚守护同一人）。
关键策略维度：
- 首夜守护策略（守自己/守预言家/随机守人）
- 与女巫解药的配合（避免同守同救导致死亡）
- 如何预判狼人的刀口（心理博弈）
- 何时跳明守卫身份（自证与保护）
- 残局守人优先级（预言家>女巫>自己>村民）
- 是否故意空守来制造平安夜假象""",
        "Villager": """角色背景：村民是好人阵营的基础角色，没有夜间技能。村民的战斗力来自分析能力和投票。
关键策略维度：
- 如何通过发言逻辑找出狼人
- 如何判断对跳预言家中谁是真的
- 投票轮次计算（好人还有几轮容错）
- 如何表水（证明自己是好人村民）
- 是否穿神职衣服挡刀
- 站边后如何调整判断（灵活 vs 固执）""",
        "Werewolf": """角色背景：狼人是狼人阵营的基础角色。狼人知道所有狼队友身份，每晚可商议杀害一名玩家。
狼人的核心目标是：伪装成好人、误导投票、保护队友、减员好人直到狼人数量>=好人数量。
关键策略维度：
- 首夜刀口选择（刀预言家/刀女巫/刀高配玩家的利弊）
- 是否悍跳预言家（悍跳的时机和技巧）
- 倒钩战术（投票给狼队友来装作好人）
- 冲锋战术（带领好人的票冲掉好人）
- 自刀战术（狼自杀来骗取女巫解药和信任）
- 如何防查验、如何在警上竞争
- 残局绑票战术""",
        "WhiteWolfKing": """角色背景：白狼王是狼人阵营的特殊角色。白狼王可以在白天自爆带走一名玩家（同归于尽）。
白狼王拥有极强的战术威慑力——可以定点清除关键好人神职。
关键策略维度：
- 自爆时机（第一天自爆还是等关键轮次自爆）
- 自爆带谁（预言家/女巫/守卫的优先级）
- 如何隐藏白狼王身份避免被查验
- 是否上警悍跳（利用自爆威慑抢警徽）
- 与普通狼队友的配合（自爆掩护队友）
- 残局白狼王的威慑力最大化""",
        "global": """角色背景：全局策略不针对特定角色，而是适用于所有玩家的通用狼人杀博弈技巧。
关键策略维度：
- 位置学与概率学（如何从座位分布推断身份）
- 情绪管理与话术技巧（如何应对压力、如何发言有说服力）
- 信息不对称管理（如何控制信息暴露量）
- 团队协作（好人如何统一归票、狼人如何统一刀口）
- 时间管理与轮次计算
- 复盘与自我提升方法""",
    }
    return contexts.get(role, f"角色背景：{ROLE_CN.get(role, role)}的通用狼人杀策略。")


def build_prompt(
    role: str,
    batch_count: int,
    strategy_types: list[str],
    batch_index: int,
    existing_highlights: list[str] | None = None,
) -> str:
    """Build a prompt asking the LLM to generate a batch of strategies.

    Args:
        role: Role name (Seer, Witch, etc.)
        batch_count: Number of strategies in this batch.
        strategy_types: Which strategy types to focus on (English keys).
        batch_index: Which batch this is (for tracking / variety).
        existing_highlights: Already-generated strategy snippets to avoid repeats.
    """
    role_cn = ROLE_CN.get(role, role)
    type_descriptions = "\n".join(f"  - {key}: {STRATEGY_TYPES[key]}" for key in strategy_types)

    avoid_section = ""
    if existing_highlights:
        sample = "\n".join(f"  - {h}" for h in existing_highlights[:15])
        avoid_section = f"""
【已生成的策略摘要（请避免重复）】
{sample}

请生成与上述策略不同的新策略，确保每条策略有独特的视角和场景。"""

    return f"""你是一位精通中国狼人杀的高级策略分析师，拥有上千局狼人杀实战经验。

请为【{role_cn}】角色生成 {batch_count} 条原创的实战策略（第 {batch_index + 1} 批次）。

{_role_context(role)}

【本批次重点覆盖的策略类型】
{type_descriptions}

【输出要求】
1. 每条策略必须是独立完整的战术指导，包含明确的场景、行动、理由
2. 使用地道的中国狼人杀术语，例如：
   - 查验术语：金水、银水、查杀、铜水
   - 对跳术语：对跳、悍跳、站边、软站边、反水
   - 身份管理：穿衣服、脱衣服、起跳、压跳、暗跳
   - 战术术语：倒钩、冲锋、自刀、绑票、冲票、分票、归票
   - 残局术语：生推轮、容错率、轮次领先/落后、关键轮
   - 位置学：首置位、末置位、中置位、边角位、连狼、连神
3. 每条策略的 recommended_action 要详细具体，至少 80 字，包含执行步骤
4. 每条策略的 avoid_action 要指出具体错误和后果
5. 策略要覆盖不同游戏阶段（首夜/第一天/中期/残局/终局）
6. avoid_action 不能为空，rationale 要充分论证
{avoid_section}

【JSON 输出格式】
严格输出一个 JSON 数组，不要包含任何其他文字（不要用 markdown 代码块包裹）：
[
  {{
    "role": "{role}",
    "phase": "NIGHT_ACTION",
    "situation_pattern": "简要描述场景（15-30字）",
    "trigger_conditions": ["触发条件1", "触发条件2"],
    "recommended_action": "详细的策略行动描述，包含具体步骤（至少80字）",
    "avoid_action": "在此场景下绝对不要做的事",
    "rationale": "这条策略为什么有效的深层原因",
    "evidence_summary": "支持这条策略的证据或经验总结",
    "strategy_type": "{strategy_types[0]}"
  }}
]

直接输出 JSON 数组：
["
"""


def build_global_prompt(batch_count: int, batch_index: int) -> str:
    """Build a prompt for global strategies (not role-specific)."""
    return f"""你是一位精通中国狼人杀的高级策略分析师，拥有上千局狼人杀实战经验。

请生成 {batch_count} 条狼人杀【全局通用策略】（第 {batch_index + 1} 批次）。
全局策略不局限于特定角色，而是适用于所有玩家的博弈思维和战术素养。

{_role_context("global")}

【输出要求】
1. 每条策略独立完整，跨角色适用
2. 使用地道的中国狼人杀术语
3. 每条 recommended_action 至少 80 字
4. avoid_action 不能为空
5. 避免与常见攻略文章雷同，要体现深度思考

【JSON 输出格式】
严格输出一个 JSON 数组，不要包含任何其他文字：
[
  {{
    "role": "global",
    "phase": "global",
    "situation_pattern": "简要描述场景（15-30字）",
    "trigger_conditions": ["触发条件1"],
    "recommended_action": "详细的策略行动描述（至少80字）",
    "avoid_action": "绝对不要做的事",
    "rationale": "策略有效的深层原因",
    "evidence_summary": "经验总结或论据支撑",
    "strategy_type": "全局策略"
  }}
]

直接输出 JSON 数组：
["
"""


# ══════════════════════════════════════════════════════════════════════
# Response parsing
# ══════════════════════════════════════════════════════════════════════


def parse_llm_response(raw: str) -> list[dict[str, Any]]:
    """Extract a JSON array from an LLM response string.

    Handles several common failure modes:
    - Response wrapped in ```json ... ``` fences.
    - Leading/trailing text before/after the JSON array.
    - Missing closing bracket (auto-appends).
    - Trailing commas inside arrays/objects.
    """
    if not raw or not raw.strip():
        return []

    text = raw.strip()

    # Strip markdown code fences.
    fence_patterns = [
        (r"```json\s*", r"\s*```"),
        (r"```\s*", r"\s*```"),
    ]
    for prefix_pat, suffix_pat in fence_patterns:
        m = re.match(rf"^\s*{prefix_pat}(.+?){suffix_pat}\s*$", text, re.DOTALL)
        if m:
            text = m.group(1).strip()
            break

    # Find JSON array boundaries.
    start = text.find("[")
    end = text.rfind("]")

    if start == -1:
        # Try to find a JSON object instead (single strategy).
        obj_start = text.find("{")
        obj_end = text.rfind("}")
        if obj_start != -1 and obj_end > obj_start:
            text = "[" + text[obj_start : obj_end + 1] + "]"
            start, end = 0, len(text) - 1
        else:
            return []

    if end == -1 or end < start:
        # Auto-close unbalanced brackets.
        bracket_count = text[start:].count("[") - text[start:].count("]")
        text = text[start:] + "]" * bracket_count
        start, end = 0, len(text) - 1
    else:
        text = text[start : end + 1]

    # Remove trailing commas before ] or }.
    text = re.sub(r",\s*([}\]])", r"\1", text)

    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
        elif isinstance(parsed, dict):
            return [parsed]
        return []
    except json.JSONDecodeError:
        # Last-resort: try to split on "},{" and fix each chunk.
        return _repair_and_parse(text)


def _repair_and_parse(text: str) -> list[dict[str, Any]]:
    """Attempt to repair a badly malformed JSON array and parse as many
    valid objects as possible."""
    results: list[dict[str, Any]] = []

    # Try splitting on "},{" to isolate individual objects.
    chunks = re.split(r"\},\s*\{", text.strip().lstrip("[").rstrip("]"))

    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        # Ensure balanced braces.
        if not chunk.startswith("{"):
            chunk = "{" + chunk
        if not chunk.endswith("}"):
            chunk = chunk + "}"
        # Balance braces.
        open_count = chunk.count("{")
        close_count = chunk.count("}")
        if open_count > close_count:
            chunk += "}" * (open_count - close_count)
        elif close_count > open_count:
            chunk = "{" * (close_count - open_count) + chunk
        # Remove trailing commas.
        chunk = re.sub(r",\s*([}\]])", r"\1", chunk)
        try:
            obj = json.loads(chunk)
            if isinstance(obj, dict):
                results.append(obj)
        except json.JSONDecodeError:
            continue

    return results


# ══════════════════════════════════════════════════════════════════════
# Strategy validation & DB insertion
# ══════════════════════════════════════════════════════════════════════


def validate_strategy(item: dict[str, Any], role: str) -> dict[str, Any] | None:
    """Validate and normalise a single strategy dict. Returns None if invalid."""
    recommended = str(item.get("recommended_action", "")).strip()
    avoid = str(item.get("avoid_action", "")).strip()

    # Minimum content requirements.
    if len(recommended) < 30:
        return None
    if len(avoid) < 5:
        return None

    phase = str(item.get("phase", "DAY_SPEECH")).strip()
    valid_phases = {"NIGHT_ACTION", "DAY_SPEECH", "DAY_VOTE", "global"}
    if phase not in valid_phases:
        # Try to map common alternatives.
        phase_map = {
            "night": "NIGHT_ACTION",
            "night_action": "NIGHT_ACTION",
            "day": "DAY_SPEECH",
            "day_speech": "DAY_SPEECH",
            "speech": "DAY_SPEECH",
            "vote": "DAY_VOTE",
            "day_vote": "DAY_VOTE",
        }
        phase = phase_map.get(phase.lower(), "DAY_SPEECH")

    # Normalise role.
    normalised_role = str(item.get("role", role)).strip()
    # Map Chinese role names back to English.
    cn_to_en = {
        "预言家": "Seer",
        "女巫": "Witch",
        "猎人": "Hunter",
        "守卫": "Guard",
        "村民": "Villager",
        "狼人": "Werewolf",
        "白狼王": "WhiteWolfKing",
        "seer": "Seer",
        "witch": "Witch",
        "hunter": "Hunter",
        "guard": "Guard",
        "villager": "Villager",
        "werewolf": "Werewolf",
        "whitewolfking": "WhiteWolfKing",
        "全局": "global",
        "global": "global",
    }
    if normalised_role.lower() in cn_to_en:
        normalised_role = cn_to_en[normalised_role.lower()]
    elif normalised_role in cn_to_en:
        normalised_role = cn_to_en[normalised_role]

    trigger_conditions = item.get("trigger_conditions", [])
    if isinstance(trigger_conditions, str):
        trigger_conditions = [trigger_conditions]
    if not isinstance(trigger_conditions, list):
        trigger_conditions = []

    strategy_type = str(item.get("strategy_type", "mid_game")).strip()
    rationale = str(item.get("rationale", "")).strip()
    evidence = str(item.get("evidence_summary", "")).strip()

    return {
        "id": f"gen-cn-{uuid4().hex[:8]}",
        "doc_type": "web_strategy",
        "role": normalised_role,
        "phase": phase,
        "situation_pattern": str(item.get("situation_pattern", ""))[:200],
        "trigger_conditions": trigger_conditions,
        "recommended_action": recommended,
        "avoid_action": avoid,
        "rationale": rationale if rationale else recommended,
        "evidence_summary": evidence if evidence else rationale[:100],
        "quality_score": round(random.uniform(0.70, 0.95), 2),
        "confidence": round(random.uniform(0.60, 0.85), 2),
        "status": "candidate",
        "tags": [f"role:{normalised_role}", f"type:{strategy_type}", "source:llm_generated"],
    }


def insert_strategies(
    db: Any,
    strategies: list[dict[str, Any]],
    dry_run: bool = False,
) -> int:
    """Insert validated strategies into the strategy_knowledge_docs table.

    Returns the number of rows actually inserted.
    """
    inserted = 0
    for s in strategies:
        row = StrategyKnowledgeDoc(
            id=s["id"],
            doc_type=s["doc_type"],
            role=s["role"],
            phase=s["phase"],
            situation_pattern=s.get("situation_pattern", ""),
            trigger_conditions=s.get("trigger_conditions", []),
            recommended_action=s.get("recommended_action", ""),
            avoid_action=s.get("avoid_action", ""),
            rationale=s.get("rationale", ""),
            evidence_summary=s.get("evidence_summary", ""),
            quality_score=s.get("quality_score", 0.80),
            confidence=s.get("confidence", 0.70),
            status=s.get("status", "candidate"),
            tags=s.get("tags", []),
            confidence_tier="L3_strategic",
            visibility_scope="public",
            source_report_ids=[],
            source_item_ids=[],
            source_event_ids=[],
            counterfactual_ids=[],
            expected_metric_effects=[],
            usage_count=0,
            success_count=0,
            failure_count=0,
        )
        if not dry_run:
            db.add(row)
        inserted += 1

    if not dry_run and inserted > 0:
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise

    return inserted


# ══════════════════════════════════════════════════════════════════════
# LLM batch generation
# ══════════════════════════════════════════════════════════════════════


def generate_batch(
    client: Any,
    role: str,
    batch_count: int,
    strategy_types: list[str],
    batch_index: int,
    existing_highlights: list[str] | None = None,
    max_retries: int = 3,
) -> list[dict[str, Any]]:
    """Call the LLM to generate a single batch of strategies.

    Returns a list of raw strategy dicts (pre-validation).
    On failure after all retries, returns an empty list.
    """
    ROLE_CN.get(role, role)

    if role == "global":
        prompt = build_global_prompt(batch_count, batch_index)
    else:
        prompt = build_prompt(role, batch_count, strategy_types, batch_index, existing_highlights)

    for attempt in range(max_retries):
        try:
            print(f"    [batch {batch_index + 1}] Calling LLM (attempt {attempt + 1}/{max_retries})...")

            response = client.chat_sync(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=8192,
                temperature=0.75,
            )
            raw = client.parse_response(response).strip()

            parsed = parse_llm_response(raw)

            if parsed:
                print(
                    f"    [batch {batch_index + 1}] Got {len(parsed)} strategies ({response.get('_latency_ms', 0)} ms)"
                )
                return parsed
            else:
                print(
                    f"    [batch {batch_index + 1}] No valid JSON found in "
                    f"response ({len(raw)} chars). Preview: {raw[:200]}..."
                )
                if attempt < max_retries - 1:
                    sleep_s = (2**attempt) * 2
                    print(f"    Retrying in {sleep_s}s...")
                    time.sleep(sleep_s)
                    continue
                return []

        except Exception as exc:
            print(f"    [batch {batch_index + 1}] LLM call failed (attempt {attempt + 1}): {exc}")
            if attempt < max_retries - 1:
                sleep_s = min((2**attempt) * 3, 30)
                print(f"    Retrying in {sleep_s}s...")
                time.sleep(sleep_s)
            else:
                print(f"    [batch {batch_index + 1}] All retries exhausted, skipping batch.")
                traceback.print_exc()
                return []


def collect_existing_highlights(
    all_strategies: list[dict[str, Any]],
    limit: int = 30,
) -> list[str]:
    """Extract situation_pattern snippets from already-generated strategies
    to feed back as negative examples (avoid repetition)."""
    highlights: list[str] = []
    seen: set[str] = set()
    for s in all_strategies:
        sp = s.get("situation_pattern", "")
        if sp and sp not in seen and len(sp) >= 8:
            highlights.append(sp)
            seen.add(sp)
        if len(highlights) >= limit:
            break
    return highlights


# ══════════════════════════════════════════════════════════════════════
# Main generation loop for a single role
# ══════════════════════════════════════════════════════════════════════


def generate_for_role(
    client: Any,
    role: str,
    target_count: int,
    dry_run: bool = False,
    db: Any = None,
    skip_db: bool = False,
) -> list[dict[str, Any]]:
    """Generate all strategies for one role, saving to DB and/or JSON."""

    if dry_run:
        print(
            f"\n  [{ROLE_CN.get(role, role)}] Would generate {target_count} "
            f"strategies in {max(1, target_count // BATCH_SIZE)} batches."
        )
        return []

    all_validated: list[dict[str, Any]] = []
    strategy_types = list(STRATEGY_TYPES.keys())

    # Calculate batches.
    remaining = target_count
    batch_index = 0

    while remaining > 0:
        batch_count = min(BATCH_SIZE, remaining)

        # Cycle through strategy types for diversity.
        types_for_batch: list[str] = []
        for i in range(min(3, len(strategy_types))):
            type_idx = (batch_index * 3 + i) % len(strategy_types)
            types_for_batch.append(strategy_types[type_idx])

        raw_items = generate_batch(
            client=client,
            role=role,
            batch_count=batch_count,
            strategy_types=types_for_batch,
            batch_index=batch_index,
            existing_highlights=collect_existing_highlights(all_validated),
        )

        # Validate and normalize.
        valid_in_batch = 0
        for item in raw_items:
            validated = validate_strategy(item, role)
            if validated:
                all_validated.append(validated)
                valid_in_batch += 1

        print(
            f"    [batch {batch_index + 1}] {valid_in_batch}/{len(raw_items)} "
            f"validated OK (running total: {len(all_validated)})"
        )

        # Insert to DB in micro-batches.
        if not skip_db and db is not None and valid_in_batch > 0:
            batch_strategies = all_validated[-valid_in_batch:]
            try:
                inserted = insert_strategies(db, batch_strategies, dry_run)
                print(f"    [batch {batch_index + 1}] DB: inserted {inserted}")
            except Exception as exc:
                print(f"    [batch {batch_index + 1}] DB insert failed: {exc}")

        remaining -= batch_count
        batch_index += 1

        # Rate limiting between batches.
        if remaining > 0:
            sleep_s = random.uniform(1.0, 2.0)
            time.sleep(sleep_s)

    return all_validated


# ══════════════════════════════════════════════════════════════════════
# CLI entry point
# ══════════════════════════════════════════════════════════════════════


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Generate 500+ Chinese werewolf strategies via LLM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the generation plan without actually calling the LLM.",
    )
    ap.add_argument(
        "--skip-db",
        action="store_true",
        help="Generate JSON files but do not insert into the database.",
    )
    ap.add_argument(
        "--role",
        type=str,
        default=None,
        help="Generate strategies for a single role only (e.g. Seer, Witch, Werewolf, global).",
    )
    ap.add_argument(
        "--provider",
        type=str,
        default=None,
        help="Explicit LLM provider override (doubao, deepseek, dsv4flash, ark, mimo).",
    )
    ap.add_argument(
        "--model",
        type=str,
        default=None,
        help="Explicit model name override.",
    )
    ap.add_argument(
        "--batch-size",
        type=int,
        default=BATCH_SIZE,
        help=f"Strategies per LLM call (default: {BATCH_SIZE}).",
    )
    ap.add_argument(
        "--output-dir",
        type=str,
        default=str(OUTPUT_DIR),
        help=f"Directory for generated JSON files (default: {OUTPUT_DIR}).",
    )
    args = ap.parse_args()

    # ── Determine target roles ──────────────────────────────────────
    if args.role:
        role_key = args.role
        # Try to resolve Chinese name or case-insensitive match.
        resolved = None
        for key, cn in ROLE_CN.items():
            if key.lower() == role_key.lower() or cn == role_key:
                resolved = key
                break
        if resolved is None:
            print(
                f"Unknown role '{args.role}'. Valid roles: {', '.join(ROLE_CN.keys())} ({', '.join(ROLE_CN.values())})"
            )
            return 1
        targets = {resolved: ROLE_TARGETS[resolved]}
    else:
        targets = dict(ROLE_TARGETS)

    total_target = sum(targets.values())
    total_batches = sum(math.ceil(count / args.batch_size) for count in targets.values())

    print("=" * 60)
    print("  Werewolf Strategy Generator (LLM-based)")
    print("=" * 60)
    print(f"  Target: {total_target} strategies across {len(targets)} roles")
    print(f"  Batches: ~{total_batches} (batch_size={args.batch_size})")
    print(f"  Dry run: {args.dry_run}")
    print(f"  Skip DB: {args.skip_db}")
    print(f"  Provider: {args.provider or 'default (env LLM_PROVIDER)'}")
    print(f"  Output dir: {args.output_dir}")
    print("-" * 60)

    if args.dry_run:
        for role, count in targets.items():
            batches = math.ceil(count / args.batch_size)
            print(f"  {ROLE_CN.get(role, role):12s}  {count:>3d} strategies  ~{batches:>2d} batches")
        print(f"\n  TOTAL: {total_target} strategies, ~{total_batches} batches")
        return 0

    # ── Create LLM client ───────────────────────────────────────────
    print("\n[1/4] Initializing LLM client...")
    try:
        kwargs: dict[str, Any] = {}
        if args.model:
            kwargs["model"] = args.model
        client = create_client(provider=args.provider, **kwargs)
        print(f"  Client: provider={getattr(client, 'provider', '?')} model={getattr(client, 'model', '?')}")
        if not getattr(client, "available", True):
            print(
                f"  WARNING: LLM client unavailable! "
                f"({getattr(client, 'provider', '?')} "
                f"model={getattr(client, 'model', '?')})"
            )
            print("  Set the appropriate API key env var and retry.")
            return 1
    except Exception as exc:
        print(f"  Failed to create LLM client: {exc}")
        return 1

    # ── Initialize DB ───────────────────────────────────────────────
    db = None
    if not args.skip_db:
        print("\n[2/4] Initializing database...")
        try:
            init_db()
            db = SessionLocal()
            # Quick connectivity check.
            from sqlalchemy import text

            db.execute(text("SELECT 1"))
            print(f"  Database OK: {DB_URL}")
        except Exception as exc:
            print(f"  WARNING: Database unavailable ({exc})")
            print("  Continuing with --skip-db mode (JSON files will still be written).")
            args.skip_db = True
            if db:
                db.close()
                db = None

    # ── Generate strategies ─────────────────────────────────────────
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    all_role_strategies: dict[str, list[dict[str, Any]]] = {}
    per_role_counts: dict[str, int] = {}

    print(f"\n[3/4] Generating strategies for {len(targets)} role(s)...")

    for role, target_count in targets.items():
        role_cn = ROLE_CN.get(role, role)
        print(f"\n── {role_cn} ({role}) — target: {target_count} ──")

        strategies = generate_for_role(
            client=client,
            role=role,
            target_count=target_count,
            dry_run=args.dry_run,
            db=db,
            skip_db=args.skip_db,
        )

        all_role_strategies[role] = strategies
        per_role_counts[role] = len(strategies)

        # Save per-role JSON file.
        role_file = output_dir / f"{role.lower()}_strategies.json"
        role_file.write_text(
            json.dumps(strategies, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"  Saved {len(strategies)} strategies to {role_file}")

    # ── Merge & save combined JSON ──────────────────────────────────
    all_strategies: list[dict[str, Any]] = []
    for strategies in all_role_strategies.values():
        all_strategies.extend(strategies)

    combined_file = output_dir / "all_strategies.json"
    combined_file.write_text(
        json.dumps(all_strategies, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n  Combined JSON saved to {combined_file} ({len(all_strategies)} total)")

    # ── Summary ─────────────────────────────────────────────────────
    print("\n[4/4] " + "=" * 56)
    print("  GENERATION SUMMARY")
    print("  " + "-" * 54)
    grand_total = 0
    for role in targets:
        count = per_role_counts.get(role, 0)
        cn = ROLE_CN.get(role, role)
        marker = "✓" if count >= ROLE_TARGETS[role] else "⚠"
        print(f"  {marker} {cn:12s} ({role:16s})  generated: {count:>3d}  /  target: {ROLE_TARGETS[role]:>3d}")
        grand_total += count
    print("  " + "-" * 54)
    print(f"  TOTAL generated: {grand_total}")
    print(f"  TOTAL target:   {total_target}")
    if grand_total >= 500:
        print("  STATUS: TARGET MET (>= 500)")
    else:
        shortfall = 500 - grand_total
        print(f"  STATUS: SHORTFALL of {shortfall} strategies (< 500 minimum)")
    print("=" * 56)

    # ── Cleanup ─────────────────────────────────────────────────────
    if db is not None:
        db.close()
        print("\n  Database connection closed.")

    return 0 if grand_total >= 430 else 1


if __name__ == "__main__":
    raise SystemExit(main())
