"""Post-game Track B→C pipeline: score decisions → extract lessons → store.

Called from the engine after game end with access to ground truth
(true roles/alignments) for accurate per-step scoring.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

from backend.db.database import DEFAULT_DB_URL as _DEFAULT_CONN


def run_post_game_scoring(game_state: Any, game_id: str) -> int:
    """Score all decisions and extract knowledge after game end.

    Has access to ground truth (true roles/alignments from game_state)
    for accurate deterministic scoring.

    Returns number of knowledge lessons stored.
    """
    try:
        from collections import defaultdict

        import psycopg2

        from backend.eval.knowledge_abstractor import KnowledgeAbstractor
        from backend.eval.knowledge_abstractor import store_lessons_to_db
        from backend.eval.per_step_scorer import PerStepScorer
        from backend.eval.per_step_scorer import PlayerReviewReport
        from backend.eval.per_step_scorer import ScoredStep
        from backend.llm import create_client
    except ImportError as e:
        logger.warning(f"Post-game scoring skipped (import error): {e}")
        return 0

    # 1. Build ground-truth state dict from game state
    state_dict = _build_state_dict(game_state)
    if not state_dict["players"]:
        return 0

    # 2. Read decisions from agent_decisions table
    conn = psycopg2.connect(_DEFAULT_CONN)
    conn.set_isolation_level(0)
    cur = conn.cursor()
    cur.execute(
        """SELECT id, player_id, day, phase, parsed_action, raw_output
           FROM agent_decisions WHERE game_id = %s""",
        (game_id,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        logger.info(f"No decisions found for game {game_id}, skipping scoring")
        return 0

    # 2.5. Check if this game already has per_step lessons (Track B may have scored it)
    import json as _check_json

    try:
        check_conn = psycopg2.connect(_DEFAULT_CONN)
        check_conn.set_isolation_level(0)
        check_cur = check_conn.cursor()
        check_cur.execute(
            "SELECT COUNT(*) FROM strategy_knowledge_docs WHERE source_report_ids @> %s::jsonb",
            (_check_json.dumps([game_id]),),
        )
        existing = int(check_cur.fetchone()[0] or 0)
        check_cur.close()
        check_conn.close()
        if existing > 0:
            logger.info(
                f"Game {game_id} already has {existing} per_step lessons (from Track B), skipping post_game scoring"
            )
            return 0
    except Exception:
        logger.debug(f"Could not check existing lessons for game {game_id}, continuing", exc_info=True)

    # 3. Build decision dicts for scoring
    decision_dicts: list[dict] = []
    for row in rows:
        pa = row[4] or {}
        player_id = str(row[1] or "")
        decision_dicts.append(
            {
                "id": str(row[0] or ""),
                "player_id": player_id,
                "player_name": _player_name(state_dict, player_id),
                "player_role": _player_role(state_dict, player_id),
                "day": int(row[2] or 0),
                "phase": str(row[3] or ""),
                "target_id": str(pa.get("target_id", "") or ""),
                "action_type": str(pa.get("action_type", "") or ""),
                "raw_text": str(row[5] or pa.get("speech", "") or ""),
                "vote_weight": float(pa.get("vote_weight", 1.0) or 1.0),
            }
        )

    # 4. Build speech_acts from decisions (rule-based, no LLM)
    speech_acts = build_speech_acts_from_decisions(decision_dicts)
    logger.info(f"Speech acts extracted: {len(speech_acts)} from {len(decision_dicts)} decisions")

    # 5. Try to create LLM client for Tier 2/3 scoring
    llm_client = None
    light_llm = False
    heavy_llm = False
    try:
        llm_client = create_client()
        if getattr(llm_client, "available", True):
            light_llm = True
            heavy_llm = True
            logger.info(
                "Post-game scoring tiers: Tier1=deterministic, Tier2=light_llm (enabled), Tier3=heavy_llm (enabled)"
            )
        else:
            logger.warning("Tier 2/3 disabled: LLM client unavailable: %s", getattr(llm_client, "provider", "unknown"))
            logger.warning(
                "Post-game scoring tiers: Tier1=deterministic, Tier2=light_llm (disabled), Tier3=heavy_llm (disabled)"
            )
    except Exception as e:
        logger.warning(f"Tier 2/3 disabled: LLM client unavailable: {e}")
        logger.warning(
            "Post-game scoring tiers: Tier1=deterministic, Tier2=light_llm (disabled), Tier3=heavy_llm (disabled)"
        )

    # 6. Run PerStepScorer
    scorer = PerStepScorer(llm_client=llm_client)
    if not light_llm:
        scorer._tiers_disabled = True  # signal for downstream consumers
    scores = scorer.score_all(decision_dicts, state_dict, speech_acts, light_llm=light_llm, heavy_llm=heavy_llm)

    tier_counts = scorer.tally_tiers(scores)
    logger.info(f"Post-game scoring for {game_id}: {tier_counts}, {len(scores)} decisions")

    # 7. Build ScoredStep objects per player
    by_player: dict[str, list[ScoredStep]] = defaultdict(list)
    for s in scores:
        d = next((x for x in decision_dicts if x["id"] == s.decision_id), {})
        step_type = _phase_to_step_type(s.phase)
        by_player[s.player_id].append(
            ScoredStep(
                step_id=s.decision_id,
                step_type=step_type,
                day=s.day,
                phase=s.phase,
                role=s.role,
                step_score=s.overall_score,
                scoring_tier=s.scoring_tier,
                action_summary=str(d.get("raw_text", ""))[:200],
                is_highlight=s.overall_score >= 0.75,
                is_mistake=s.overall_score <= 0.30,
                mistake_type=_infer_mistake_type(s, d),
                lesson_abstract=s.evidence[0] if s.evidence else "",
                lesson_tags=[s.role, step_type],
                evidence_event_ids=[s.decision_id],
            )
        )

    # 8. Run KnowledgeAbstractor
    abstractor = KnowledgeAbstractor()
    reviews: list[PlayerReviewReport] = []
    for player_id, steps in by_player.items():
        role = _player_role(state_dict, player_id)
        reviews.append(
            PlayerReviewReport(
                game_id=game_id,
                player_id=player_id,
                role=role,
                scored_steps=steps,
            )
        )

    by_role_lessons = abstractor.abstract_from_game(reviews)
    all_lessons = []
    for lessons in by_role_lessons.values():
        all_lessons.extend(lessons)

    if not all_lessons:
        return 0

    # 9. Store lessons as candidate docs
    stored = store_lessons_to_db(all_lessons)
    logger.info(f"Post-game knowledge: {stored} lessons stored for game {game_id}")
    return stored


def build_speech_acts_from_decisions(decision_dicts: list[dict]) -> list[dict]:
    """Extract speech acts from decisions using rule/keyword-based analysis.

    Analyzes raw_text for claim_role, accuse, defend, vote_intent, and
    self_defense patterns. Returns a list of speech act dicts suitable for
    PerStepScorer.score_all().

    No LLM calls — purely regex/keyword matching.
    """
    speech_acts: list[dict] = []

    for d in decision_dicts:
        phase = str(d.get("phase", ""))
        action_type = str(d.get("action_type", ""))
        raw_text = str(d.get("raw_text", ""))

        # Filter: only decisions with speech content
        if action_type not in ("talk", "speech") and "SPEECH" not in phase and "TALK" not in phase:
            continue
        if not raw_text.strip():
            continue

        player_id = str(d.get("player_id", ""))
        day = int(d.get("day", 0))

        # 1. Detect claimed_role
        claimed_role = None
        if re.search(r"预言家|预言|查验|查杀", raw_text):
            claimed_role = "Seer"
        elif re.search(r"女巫|解药|毒药|救", raw_text):
            claimed_role = "Witch"
        elif re.search(r"猎人|开枪", raw_text):
            claimed_role = "Hunter"
        elif re.search(r"守卫|守护|守", raw_text):
            claimed_role = "Guard"
        elif re.search(r"村民|平民|好人[^\w]|^民|我是民|一张民|普通民", raw_text):
            claimed_role = "Villager"

        # 2. Detect suspected players (accuse patterns)
        suspected_players: list[str] = []
        # Pattern: 怀疑X号/踩X号/X号是狼/X号像狼/X号铁狼/X号狼
        accuse_patterns = [
            r"怀疑\s*(\d+)号",
            r"踩\s*(\d+)号",
            r"(\d+)号\s*(?:是|像|为|很|都|就)?\s*狼",
            r"(\d+)号\s*(?:铁狼|像狼|是狼|狼人)",
        ]
        for pat in accuse_patterns:
            for m in re.finditer(pat, raw_text):
                num = m.group(1)
                label = f"{num}号"
                if label not in suspected_players:
                    suspected_players.append(label)

        # 3. Detect defended players (defend patterns)
        defended_players: list[str] = []
        defend_patterns = [
            r"保\s*(\d+)号",
            r"站边\s*(\d+)号",
            r"(\d+)号\s*(?:好人|不像狼|是好人|不是狼|铁好人)",
        ]
        for pat in defend_patterns:
            for m in re.finditer(pat, raw_text):
                num = m.group(1)
                label = f"{num}号"
                if label not in defended_players and label not in suspected_players:
                    defended_players.append(label)

        # 4. Detect vote intent
        vote_targets: list[str] = []
        vote_patterns = [
            r"(?:归票|投|票|出|放逐)\s*(\d+)号",
        ]
        for pat in vote_patterns:
            for m in re.finditer(pat, raw_text):
                num = m.group(1)
                label = f"{num}号"
                if label not in vote_targets:
                    vote_targets.append(label)

        # Add vote targets as suspected if not already there
        for vt in vote_targets:
            if vt not in suspected_players:
                suspected_players.append(vt)

        # 5. Detect self-defense
        has_self_defense = bool(
            re.search(
                r"表水|我是好人|我不是狼|自证|解释|听我说",
                raw_text,
            )
        )

        # Determine stance
        if claimed_role:
            stance = "claim"
        elif suspected_players:
            stance = "accuse"
        elif defended_players:
            stance = "defend"
        else:
            stance = "neutral"

        # Build risk flags
        risk_flags: list[str] = []
        if claimed_role and len(claimed_role) > 0:
            risk_flags.append("claim_role")
        if len(suspected_players) > 2:
            risk_flags.append("accuses_many")
        if len(raw_text) < 20:
            risk_flags.append("short_speech")
        if has_self_defense and claimed_role is None:
            risk_flags.append("self_defense")

        speech_acts.append(
            {
                "player_id": player_id,
                "day": day,
                "phase": phase,
                "stance": stance,
                "suspected_players": suspected_players,
                "defended_players": defended_players,
                "claimed_role": claimed_role,
                "risk_flags": risk_flags,
                "grounded_event_ids": [],
                "raw_text_snippet": raw_text[:100],
            }
        )

    return speech_acts


# ---- helpers ----


def _build_state_dict(game_state: Any) -> dict:
    players = []
    for p in getattr(game_state, "players", []):
        role = getattr(p, "role", None)
        alignment = getattr(p, "alignment", None)
        players.append(
            {
                "id": getattr(p, "id", ""),
                "name": getattr(p, "name", ""),
                "role": role.value if hasattr(role, "value") else str(role or ""),
                "alignment": alignment.value if hasattr(alignment, "value") else str(alignment or ""),
                "alive": getattr(p, "alive", True),
            }
        )
    return {"players": players}


def _player_name(state: dict, pid: str) -> str:
    for p in state["players"]:
        if p["id"] == pid:
            return p["name"]
    return ""


def _player_role(state: dict, pid: str) -> str:
    for p in state["players"]:
        if p["id"] == pid:
            return p["role"]
    return ""


def _phase_to_step_type(phase: str) -> str:
    if "SPEECH" in phase or "TALK" in phase or "LAST_WORDS" in phase:
        return "speech"
    if "VOTE" in phase or "BADGE" in phase:
        return "vote"
    return "night_action"


def _infer_mistake_type(score: Any, decision: dict) -> str:
    """Infer mistake type from scoring evidence and decision context."""
    correct = getattr(score, "correctness", 0.5)
    phase = str(decision.get("phase", ""))
    str(decision.get("action_type", ""))
    raw = str(decision.get("raw_text", ""))
    if correct < 0.2 and "VOTE" in phase:
        return "wrong_vote"
    if correct < 0.3 and "SPEECH" in phase and len(raw) < 30:
        return "empty_speech"
    if correct < 0.3 and "NIGHT" in phase:
        return "bad_target"
    return ""
