"""Personal post-game reflection — MBTI-differentiated knowledge extraction.

After each game, every agent writes a personal "review" from their own
MBTI + Role perspective. Same game, different MBTI → different learnings.

Design references:
  - Claude Code learnings.md: "what worked / what failed / patterns / errors"
  - wolfcha generateGameAnalysis(): Timeline + PersonalStats + PlayerReview
  - Anthropic Context Engineering: Write → Select → Compress → Isolate

Single Responsibility: convert game state + persona info → structured knowledge docs.
No game logic, no LLM calls outside of the reflection prompt itself.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import Runnable

from backend.agents.cognitive.profiles import PersonaTraits, MindTraits

logger = logging.getLogger(__name__)

_DEFAULT_CONN = "postgresql://werewolf:wolf_secret_2026@127.0.0.1:5433/werewolf"


# ============================================================
# Reflection Output Types
# ============================================================

@dataclass
class ReflectionResult:
    """Result of one agent's post-game reflection."""

    player_id: str
    player_name: str
    role: str
    persona_scope: str  # e.g. "mbti:INTJ" or "mbti:INTJ+role:Werewolf"
    won: bool

    # Core learnings (Claude Code learnings.md structure)
    what_worked: List[str] = field(default_factory=list)
    what_failed: List[str] = field(default_factory=list)
    patterns_discovered: List[str] = field(default_factory=list)
    mistakes_to_avoid: List[str] = field(default_factory=list)

    # Meta
    key_insight: str = ""       # single most important lesson
    confidence: float = 0.5      # how confident the agent is in this reflection
    raw_reflection: str = ""     # full LLM output for debugging

    def to_strategy_docs(self) -> list[dict]:
        """Convert reflection to strategy docs for PG storage."""
        docs = []
        role = self.role.lower()
        mapping = [
            (self.what_worked, "reflection_what_worked"),
            (self.what_failed, "reflection_what_failed"),
            (self.patterns_discovered, "reflection_patterns"),
            (self.mistakes_to_avoid, "reflection_mistakes"),
        ]
        for items, doc_type in mapping:
            for item in items:
                docs.append({
                    "situation": "",
                    "strategy": item if isinstance(item, str) else str(item),
                    "rationale": "",
                    "role": role,
                    "phase": "global",
                    "quality": self.confidence,
                    "doc_type": doc_type,
                })
        return docs


# ============================================================
# MBTI Reflection Angles
# ============================================================

_MBTI_REFLECTION_ANGLE: Dict[str, str] = {
    "INTJ": "关注全局策略模式。分析你本局的长线规划在哪个节点出了问题。你的判断是否被局部信息误导了？",
    "INTP": "关注逻辑一致性。你本局的推理链路有没有自相矛盾的地方？哪些假设被证实是错误的？",
    "ENTJ": "关注决策效率和执行力。你做关键决定的速度够快吗？有没有犹豫导致机会流失？",
    "ENTP": "关注信息利用和创新。你有没有尝试非传统的打法？哪些被验证有效、哪些被证伪？",
    "INFJ": "关注深层动机和人际信号。你能察觉到其他玩家的隐藏意图吗？哪些信号你忽略了的？",
    "INFP": "关注价值判断和直觉。你的直觉本局对了几次、错了几次？什么时候该坚持本能？",
    "ENFJ": "关注对他人的影响力。你说服了几个玩家跟你的站边？你的发言对票型有多大影响？",
    "ENFP": "关注关系动态和信息流。你和其他玩家之间信息传递是否顺畅？谁给了你关键线索？",
    "ISTJ": "关注流程正确性和事实核对。你的行动是否严格遵守了自己角色的最优流程？",
    "ISFJ": "关注保护和支持。你是否在关键时刻保护了正确的目标？有没有忽略了需要保护的人？",
    "ESTJ": "关注结果和效率。你本局投入最值得的决策是什么？最浪费的又是什么？",
    "ESFJ": "关注团队和谐和协调。你是否帮助了好人阵营维持协作？还是制造了不必要的混乱？",
    "ISTP": "关注临场应变和瞬时判断。你的快速反应本局有没有成功案例？哪里反应慢了？",
    "ISFP": "关注风格适配和情感表达。你的发言风格本局是否有效地传达了你的真实判断？",
    "ESTP": "关注机会把握和实战表现。你有没有在关键时刻打出高光操作？",
    "ESFP": "关注氛围感知和即兴发挥。你是否准确把握了桌面的情绪温度？什么时候该更主动、什么时候该退让？",
}

_MBTI_FALLBACK_ANGLE = "关注决策质量和信息利用效率。回顾本局，你的判断在哪些地方偏离了最优解？"


def _get_reflection_angle(mbti: str) -> str:
    """Get the MBTI-specific reflection angle prompt."""
    return _MBTI_REFLECTION_ANGLE.get(mbti, _MBTI_FALLBACK_ANGLE)


# ============================================================
# Refector
# ============================================================

class Reflector:
    """Post-game personal reflection engine.

    For each agent in a completed game, generates an MBTI-differentiated
    reflection and extracts structured knowledge docs for storage.
    """

    def __init__(
        self,
        llm: Runnable,
        conn_str: str = "",
    ):
        self._llm = llm
        self._conn_str = conn_str or _DEFAULT_CONN

    # ---- Main entry point ----

    def reflect_game(
        self,
        game_id: str,
        agent_states: List[Dict[str, Any]],
    ) -> List[ReflectionResult]:
        """Run personal reflection for every agent in a finished game.

        Args:
            game_id: Game identifier.
            agent_states: List of per-agent state dicts, each containing:
                - player_id, player_name, role
                - persona: PersonaTraits (or dict with mbti, style_label, etc.)
                - mind: MindTraits (or dict)
                - won: bool
                - game_events: relevant events this agent observed
                - decisions: this agent's decisions

        Returns:
            List of ReflectionResult, one per agent.
        """
        results = []
        for state in agent_states:
            try:
                result = self._reflect_one(state)
                results.append(result)
                logger.info(
                    f"Reflection done: {state.get('player_name','?')} "
                    f"({state.get('role','?')}) → {len(result.what_worked)} learnings"
                )
            except Exception as e:
                logger.error(f"Reflection failed for {state.get('player_id','?')}: {e}")
        return results

    # ---- Per-agent reflection ----

    def _reflect_one(self, state: Dict[str, Any]) -> ReflectionResult:
        """Run reflection for a single agent."""
        persona = state.get("persona")
        mbti = self._extract_mbti(persona)
        role = state.get("role", "unknown")
        name = state.get("player_name", "unknown")
        player_id = state.get("player_id", "")

        prompt = self._build_reflection_prompt(state, mbti)
        system = self._build_reflection_system(mbti, role)

        raw = self._call_llm(system, prompt)
        parsed = self._parse_reflection(raw)
        if not self._has_reflection_items(parsed):
            parsed = self._fallback_reflection_from_state(state, mbti, raw)

        return ReflectionResult(
            player_id=player_id,
            player_name=name,
            role=role,
            persona_scope=f"mbti:{mbti}",
            won=bool(state.get("won", False)),
            what_worked=parsed.get("what_worked", []),
            what_failed=parsed.get("what_failed", []),
            patterns_discovered=parsed.get("patterns_discovered", []),
            mistakes_to_avoid=parsed.get("mistakes_to_avoid", []),
            key_insight=parsed.get("key_insight", ""),
            confidence=float(parsed.get("confidence", 0.5)),
            raw_reflection=raw,
        )

    @staticmethod
    def _has_reflection_items(parsed: Dict[str, Any]) -> bool:
        return any(
            parsed.get(key)
            for key in (
                "what_worked",
                "what_failed",
                "patterns_discovered",
                "mistakes_to_avoid",
            )
        )

    def _fallback_reflection_from_state(
        self,
        state: Dict[str, Any],
        mbti: str,
        raw: str,
    ) -> Dict[str, Any]:
        role = state.get("role", "unknown")
        won = bool(state.get("won", False))
        decisions = state.get("decisions", [])
        events = state.get("game_events", [])
        action_count = len(decisions)
        event_count = len(events)
        outcome_text = "胜利" if won else "失败"
        key_insight = raw[:160].strip() if raw else ""
        if not key_insight:
            key_insight = (
                f"{role} 的复盘至少要绑定可见事实、合法目标和行动理由，"
                "否则后续策略库无法判断经验是否可复用。"
            )
        return {
            "what_worked": [
                f"本局作为 {role} 完成了 {action_count} 次可审计行动，结果为{outcome_text}。",
            ],
            "what_failed": [
                f"反思输出没有提供完整结构化字段，需要在后续 {mbti} 复盘中补足具体成功/失败证据。",
            ],
            "patterns_discovered": [
                f"该视角累计观察到 {event_count} 条事件，复盘知识必须保留来源对局和角色信息。",
            ],
            "mistakes_to_avoid": [
                "不要让格式异常导致反思知识静默丢失；缺字段时也要生成低置信度候选经验。",
            ],
            "key_insight": key_insight,
            "confidence": 0.35,
        }

    # ---- Prompt builders ----

    def _build_reflection_system(self, mbti: str, role: str) -> str:
        """Build system prompt for the reflection LLM call."""
        return (
            f"你是一个 {mbti} 型人格的狼人杀玩家，刚刚完成了一局作为 {role} 的游戏。\n"
            f"现在请以你的 MBTI 视角回顾这局游戏，总结经验和教训。\n\n"
            f"你的 MBTI 特征会自然影响你关注什么:\n"
            f"{_get_reflection_angle(mbti)}\n\n"
            "请用中文回答。输出严格的 JSON 格式。"
        )

    def _build_reflection_prompt(self, state: Dict[str, Any], mbti: str) -> str:
        """Build the user prompt for reflection."""
        role = state.get("role", "unknown")
        name = state.get("player_name", "unknown")
        won = "赢了" if state.get("won") else "输了"

        lines = [
            f"玩家: {name}",
            f"身份: {role}",
            f"结果: {won}",
            "",
            "=== 你的关键决策记录 ===",
        ]

        decisions = state.get("decisions", [])
        if decisions:
            for d in decisions[-10:]:
                action_type = d.get("action_type", "?")
                target = d.get("target", "无")
                speech = (d.get("speech") or "")[:120]
                lines.append(f"  [{action_type}] 目标={target} | {speech}")
        else:
            lines.append("  (无详细决策记录)")

        lines.extend([
            "",
            "=== 游戏事件摘要 ===",
        ])
        events = state.get("game_events", [])
        if events:
            for e in events[-12:]:
                etype = e.get("type", "?")
                desc = str(e.get("description", e))[:150]
                lines.append(f"  [{etype}] {desc}")
        else:
            lines.append("  (无事件记录)")

        lines.extend([
            "",
            "=== 复盘任务 ===",
            f"作为 {mbti} 型人格，请从你的视角总结这局游戏:",
            "",
            "1. what_worked: 你本局做得好的 2-3 件事（具体描述）",
            "2. what_failed: 你本局做错的 2-3 件事（具体描述，不要泛泛而谈）",
            "3. patterns_discovered: 你发现的 1-2 个规律或模式",
            "4. mistakes_to_avoid: 下次应该避免的 2-3 个错误",
            "5. key_insight: 本局最重要的一个教训（1-2句话）",
            "6. confidence: 你对自己这个复盘结论的置信度（0-1之间的数字）",
            "",
            "输出格式（严格 JSON，不要额外解释）:",
            '{',
            '  "what_worked": ["...", "..."],',
            '  "what_failed": ["...", "..."],',
            '  "patterns_discovered": ["...", "..."],',
            '  "mistakes_to_avoid": ["...", "..."],',
            '  "key_insight": "...",',
            '  "confidence": 0.7',
            '}',
        ])

        return "\n".join(lines)

    # ---- LLM call ----

    def _call_llm(self, system: str, user: str, max_tokens: int = 800) -> str:
        """Call LLM for reflection."""
        try:
            resp = self._llm.invoke([
                SystemMessage(content=system),
                HumanMessage(content=user),
            ])
            return resp.content.strip()
        except Exception as e:
            logger.error(f"Reflection LLM call failed: {e}")
            return '{"what_worked":[],"what_failed":[],"patterns_discovered":[],"mistakes_to_avoid":[],"key_insight":"","confidence":0.0}'

    # ---- Parse ----

    def _parse_reflection(self, raw: str) -> Dict[str, Any]:
        """Parse LLM reflection output to structured dict."""
        try:
            # Try to extract JSON
            import re
            m = re.search(r'\{[^}]*\}', raw, re.DOTALL)
            if m:
                data = json.loads(m.group())
                return {
                    "what_worked": data.get("what_worked", []),
                    "what_failed": data.get("what_failed", []),
                    "patterns_discovered": data.get("patterns_discovered", []),
                    "mistakes_to_avoid": data.get("mistakes_to_avoid", []),
                    "key_insight": data.get("key_insight", ""),
                    "confidence": float(data.get("confidence", 0.5)),
                }
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(f"Failed to parse reflection JSON: {e}")

        # Fallback: treat raw text as key insight
        return {
            "what_worked": [],
            "what_failed": [],
            "patterns_discovered": [],
            "mistakes_to_avoid": [],
            "key_insight": raw[:200] if raw else "",
            "confidence": 0.3,
        }

    # ---- Helpers ----

    @staticmethod
    def _extract_mbti(persona: Any) -> str:
        """Extract MBTI string from persona object/dict."""
        if persona is None:
            return "INTJ"  # default
        if isinstance(persona, PersonaTraits):
            return persona.mbti or "INTJ"
        if isinstance(persona, dict):
            return persona.get("mbti", "INTJ")
        if hasattr(persona, "mbti"):
            return persona.mbti or "INTJ"
        return "INTJ"


# ============================================================
# Knowledge Doc Extraction
# ============================================================

def reflections_to_knowledge_docs(
    reflections: List[ReflectionResult],
    game_id: str,
) -> List[Dict[str, Any]]:
    """Convert reflection results to StrategyKnowledgeDoc-compatible dicts.

    Each experience item (what_worked, what_failed, patterns_discovered,
    mistakes_to_avoid) becomes one strategy_knowledge_docs row with
    doc_type='reflection'. Status is 'active' so the retriever picks them up
    immediately for the next game.

    Args:
        reflections: List of reflection results.
        game_id: Source game ID for provenance tracking.

    Returns:
        List of dicts ready for _upsert_strategy_knowledge_rows().
    """
    docs = []
    for r in reflections:
        persona_scope = r.persona_scope
        role = r.role

        # what_worked → positive experience reflections
        for item in r.what_worked:
            docs.append({
                "doc_id": _make_doc_id(game_id, r.player_id, item[:40]),
                "doc_type": "reflection",
                "role": role,
                "phase": "global",
                "persona_scope": persona_scope,
                "situation_pattern": f"{r.player_name}({role}, {persona_scope}) 对局总结 — 成功经验",
                "recommended_action": item,
                "rationale": f"来自 {persona_scope} 视角的成功经验。{r.key_insight}" if r.key_insight else "",
                "evidence_summary": f"对局 {game_id} 中验证有效",
                "source_report_ids": [game_id],
                "quality_score": r.confidence,
                "confidence": r.confidence,
                "usage_count": 0,
                "success_count": 0,
                "failure_count": 0,
                "status": "candidate",
                "tags": [persona_scope, role, "reflection", "success"],
            })

        # what_failed + mistakes_to_avoid → negative experience reflections
        for item in r.what_failed + r.mistakes_to_avoid:
            docs.append({
                "doc_id": _make_doc_id(game_id, r.player_id, item[:40]),
                "doc_type": "reflection",
                "role": role,
                "phase": "global",
                "persona_scope": persona_scope,
                "situation_pattern": f"{r.player_name}({role}, {persona_scope}) 对局教训 — 失败/应避免",
                "avoid_action": item,
                "rationale": f"来自 {persona_scope} 视角的失败教训。{r.key_insight}" if r.key_insight else "",
                "evidence_summary": f"对局 {game_id} 中验证应避免",
                "source_report_ids": [game_id],
                "quality_score": r.confidence,
                "confidence": r.confidence,
                "usage_count": 0,
                "success_count": 0,
                "failure_count": 0,
                "status": "candidate",
                "tags": [persona_scope, role, "reflection", "failure"],
            })

        # patterns_discovered → pattern reflection
        for item in r.patterns_discovered:
            docs.append({
                "doc_id": _make_doc_id(game_id, r.player_id, item[:40]),
                "doc_type": "reflection",
                "role": role,
                "phase": "global",
                "persona_scope": persona_scope,
                "situation_pattern": item,
                "recommended_action": f"{persona_scope} 视角发现的规律: {item}",
                "rationale": r.key_insight or "",
                "evidence_summary": f"对局 {game_id} 中观察到的模式",
                "source_report_ids": [game_id],
                "quality_score": r.confidence * 0.8,
                "confidence": r.confidence,
                "usage_count": 0,
                "success_count": 0,
                "failure_count": 0,
                "status": "candidate",
                "tags": [persona_scope, role, "reflection", "pattern"],
            })

    return docs


def _make_doc_id(game_id: str, player_id: str, content_hash: str) -> str:
    """Generate a stable doc_id from game + player + content."""
    import hashlib
    raw = f"{game_id}:{player_id}:{content_hash}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ============================================================
# Save reflection results to DB
# ============================================================

def save_reflections_to_db(
    reflections: List[ReflectionResult],
    game_id: str,
    conn_str: str = "",
) -> int:
    """Save reflection results as StrategyKnowledgeDocs to PostgreSQL.

    Args:
        reflections: Reflection results from Reflector.reflect_game().
        game_id: Source game ID.
        conn_str: PostgreSQL connection string.

    Returns:
        Number of knowledge docs saved.
    """
    docs = reflections_to_knowledge_docs(reflections, game_id)
    if not docs:
        return 0

    try:
        from backend.db.database import SessionLocal, init_db
        from backend.db.models import StrategyKnowledgeDoc

        init_db()
        db = SessionLocal()
        try:
            saved = 0
            for doc in docs:
                row = db.query(StrategyKnowledgeDoc).filter(
                    StrategyKnowledgeDoc.id == doc["doc_id"]
                ).first()
                if row is not None:
                    # Update quality/confidence if reflection improved
                    if doc["quality_score"] > (row.quality_score or 0):
                        row.quality_score = doc["quality_score"]
                        row.confidence = doc["confidence"]
                        saved += 1
                    continue

                row = StrategyKnowledgeDoc(
                    id=doc["doc_id"],
                    doc_type=doc["doc_type"],
                    role=doc["role"],
                    phase=doc.get("phase", "global"),
                    persona_scope=doc.get("persona_scope"),
                    situation_pattern=doc.get("situation_pattern", ""),
                    recommended_action=doc.get("recommended_action", ""),
                    avoid_action=doc.get("avoid_action"),
                    rationale=doc.get("rationale", ""),
                    evidence_summary=doc.get("evidence_summary", ""),
                    source_report_ids=doc.get("source_report_ids", []),
                    quality_score=doc["quality_score"],
                    confidence=doc["confidence"],
                    usage_count=0,
                    success_count=0,
                    failure_count=0,
                    status=doc.get("status", "candidate"),
                    tags=doc.get("tags", []),
                )
                db.add(row)
                saved += 1

            db.commit()
            logger.info(f"Saved {saved} reflection knowledge docs for game {game_id}")
            return saved
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Failed to save reflections to DB: {e}")
        return 0


# ============================================================
# Raw PG batch insert — direct psycopg2 path
# ============================================================

def save_reflections_to_pg(reflections: list, conn_str: str = "") -> int:
    """Save reflection results to PostgreSQL strategy_knowledge_docs."""
    import psycopg2
    conn = psycopg2.connect(conn_str or _DEFAULT_CONN)
    cur = conn.cursor()
    count = 0
    for ref in reflections:
        for doc in ref.to_strategy_docs():
            cur.execute("""
                INSERT INTO strategy_knowledge_docs
                (situation_pattern, recommended_action, rationale, role, phase, quality_score, doc_type, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'candidate')
            """, (doc["situation"], doc["strategy"], doc["rationale"],
                  doc["role"], doc["phase"], doc["quality"], doc["doc_type"]))
            count += 1
    conn.commit()
    cur.close()
    conn.close()
    return count
