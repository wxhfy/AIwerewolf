"""Locked rubric definitions for LLM-as-Judge werewolf scoring.

RULERS-style: every rubric item has version-locked anchors, evidence requirements,
and typed scales. The rubric YAML is hashed — any change is a new version.

Design references:
  - RULERS (Hong et al., 2026): locked rubrics + evidence-anchored scoring
  - Auto-Arena (ICLR 2025): 3-judge panel with committee debate
  - CourtEval (ACL 2025): Grader + Critic + Defender adversarial validation
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class RubricItem:
    """One scoring dimension with locked anchors and evidence requirements."""

    id: str
    dimension: str  # "strategy" | "logic" | "social"
    question: str  # What the judge is asked to evaluate
    scale: tuple[int, ...]  # (0, 2, 4, 6, 8, 10)
    anchors: dict[int, str]  # score → description
    evidence_required: bool = True
    evidence_type: str = "event_id"  # "event_id" | "vote_ids" | "chat_ids"


# ============================================================
# Game-Level Rubrics (3 judges × 2 items = 6 dimensions)
# ============================================================

STRATEGIST_RUBRIC = [
    RubricItem(
        id="S1",
        dimension="strategy",
        question="该玩家是否在每个夜晚/白天阶段做出了最优或接近最优的决策？考虑技能使用时机、投票目标和整体战略方向。",
        scale=(0, 2, 4, 6, 8, 10),
        anchors={
            0: "几乎每个关键决策都是错误的——技能浪费、投票偏航、战略方向完全失当",
            2: "大部分决策有问题，仅偶尔正确",
            4: "部分决策正确，但整体战略缺乏一致性，有明显失误",
            6: "多数决策合理，偶有失误但总体方向正确",
            8: "绝大部分决策都是正确的，战略清晰，失误极少",
            10: "近乎完美的战略执行——每个技能/投票都在最佳时机指向最优目标",
        },
        evidence_required=True,
        evidence_type="event_id",
    ),
    RubricItem(
        id="S2",
        dimension="strategy",
        question="该玩家的投票策略是否有效推进了阵营目标？是否在关键轮次做出了正确的投票选择？",
        scale=(0, 2, 4, 6, 8, 10),
        anchors={
            0: "每轮都投了好人/队友，且关键轮次完全投错",
            2: "大部分轮次投错，仅1-2次正确",
            4: "投票正确率接近50%，关键轮次表现一般",
            6: "多数轮次投票正确，关键轮次基本无误",
            8: "投票几乎全对，关键轮次精准击中敌方",
            10: "每次投票都是最优选择，且通过发言引导了他人投票",
        },
        evidence_required=True,
        evidence_type="vote_ids",
    ),
]

LOGICIAN_RUBRIC = [
    RubricItem(
        id="L1",
        dimension="logic",
        question="该玩家的发言内容与投票/行动之间逻辑自洽吗？是否存在发言表达A但行动做B的矛盾？",
        scale=(0, 2, 4, 6, 8, 10),
        anchors={
            0: "发言与行动严重矛盾——说了投A却投B，或推理链路完全断裂",
            2: "多处逻辑不一致，言行频繁不符",
            4: "大体一致但存在1-2处明显矛盾",
            6: "逻辑基本自洽，无明显矛盾",
            8: "逻辑链条清晰，发言准确预示了后续行动",
            10: "完美的逻辑一致性——每句话都能对应后续行动，推演环环相扣",
        },
        evidence_required=True,
        evidence_type="chat_ids + vote_ids",
    ),
    RubricItem(
        id="L2",
        dimension="logic",
        question="该玩家的推理是否基于游戏中的真实信息（而非凭空编造）？是否引用了具体事件或发言？",
        scale=(0, 2, 4, 6, 8, 10),
        anchors={
            0: "完全凭空编造，引用不存在的事件或发言",
            2: "大部分推理缺乏事实支撑",
            4: "偶尔引用真实信息，但推理经常脱离事实",
            6: "基本引用真实信息，偶有不准确",
            8: "几乎每条推理都有具体事件/发言作为证据",
            10: "所有推理都精确锚定于真实游戏事件，引用准确无误",
        },
        evidence_required=True,
        evidence_type="chat_ids + event_ids",
    ),
]

PSYCHOLOGIST_RUBRIC = [
    RubricItem(
        id="P1",
        dimension="social",
        question="该玩家的发言对桌面产生了多大影响？后续玩家的投票和发言是否参考了该玩家的观点？",
        scale=(0, 2, 4, 6, 8, 10),
        anchors={
            0: "发言完全被忽略，无任何人跟进或参考",
            2: "偶有人提及但无人真正跟进",
            4: "有一定影响力，少数人参考其意见",
            6: "明显影响了部分玩家的决策方向",
            8: "成为桌面核心声音之一，多人跟随其判断",
            10: "完全主导了桌面走向——发言后票型和站边显著变化",
        },
        evidence_required=True,
        evidence_type="chat_ids + subsequent_vote_ids",
    ),
    RubricItem(
        id="P2",
        dimension="social",
        question="如果该玩家是狼人——欺骗是否成功？如果该玩家是好人——是否成功获得信任并引导了正确判断？",
        scale=(0, 2, 4, 6, 8, 10),
        anchors={
            0: "完全失败——立即被识破（狼）/完全不被信任（好人）",
            2: "大部分时间未被信任，言行频繁被质疑",
            4: "有时被信任有时被怀疑，表现一般",
            6: "基本获得信任，能力得到部分认可",
            8: "高度被信任——狼成功隐藏到最后/好人成为信息中枢",
            10: "完美表现——狼全程未被怀疑/好人的每个判断都被跟随",
        },
        evidence_required=True,
        evidence_type="chat_ids + vote_ids",
    ),
]

# ============================================================
# Per-Step Rubrics (lightweight, single judge)
# ============================================================

PER_STEP_RUBRIC = [
    RubricItem(
        id="T1",
        dimension="per_step",
        question="在当时的可见信息下，这个决策是否合理？考虑该玩家已知的信息（非全局信息）。",
        scale=(0, 2, 4, 6, 8, 10),
        anchors={
            0: "即使在当时信息下，这个决策也是明显错误的",
            2: "信息有限但仍有更好的选择",
            4: "有一定合理性但不是最优",
            6: "在当时信息下是合理的决策",
            8: "基于当时信息做出了很好的判断",
            10: "在当时信息下几乎是最优解",
        },
        evidence_required=True,
        evidence_type="event_id",
    ),
    RubricItem(
        id="T2",
        dimension="per_step",
        question="该决策的推理是否充分？是否考虑了关键因素并给出了清晰的逻辑？",
        scale=(0, 2, 4, 6, 8, 10),
        anchors={
            0: "完全无推理或推理明显荒谬",
            2: "推理非常薄弱或明显错误",
            4: "推理基本通顺但不够深入",
            6: "有合理的推理链条",
            8: "推理深入，考虑了多方面因素",
            10: "推理极其充分，展现了对局势的深刻理解",
        },
        evidence_required=True,
        evidence_type="event_id",
    ),
]

# ============================================================
# Version Locking
# ============================================================

ALL_RUBRICS = {
    "strategist": STRATEGIST_RUBRIC,
    "logician": LOGICIAN_RUBRIC,
    "psychologist": PSYCHOLOGIST_RUBRIC,
    "per_step": PER_STEP_RUBRIC,
}


def compute_rubric_hash() -> str:
    """Compute a sha256 hash of all rubric definitions for version locking."""
    raw = json.dumps(
        {
            name: [{"id": r.id, "question": r.question, "anchors": r.anchors} for r in rubric]
            for name, rubric in ALL_RUBRICS.items()
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


RUBRIC_VERSION = "werewolf-v1.0"
RUBRIC_HASH = compute_rubric_hash()
