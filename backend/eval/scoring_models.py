"""Small structured models for opportunity-level scoring.

Phase 3+5 of Track B reconstruction (§5):
  - OpportunityValueModel: w(o) ∈ [0,1] — how important is this opportunity?
  - DecisionQualityModel: q(o) ∈ [0,1] — how good was the chosen action?
  - MistakeSeverityModel: severity(b) ∈ [0,1] — how severe is this mistake?

MVP uses LightGBM / Logistic Regression with pairwise training.
"""

from __future__ import annotations

import json
import pickle
import warnings
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any

import numpy as np

try:
    import joblib as _joblib

    _HAS_JOBLIB = True
except ImportError:
    _HAS_JOBLIB = False


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------


@dataclass
class ModelFeatures:
    """Feature vector for small scoring models."""

    # ---- Role encoding (one-hot) ----
    role_seer: int = 0
    role_witch: int = 0
    role_guard: int = 0
    role_hunter: int = 0
    role_werewolf: int = 0
    role_villager: int = 0

    # ---- Opportunity type encoding ----
    op_seer_check: int = 0
    op_witch_save: int = 0
    op_witch_poison: int = 0
    op_guard_protect: int = 0
    op_hunter_shot: int = 0
    op_werewolf_kill: int = 0
    op_vote: int = 0
    op_speech: int = 0

    # ---- Game context (§5.1) ----
    day: float = 1.0
    alive_count: float = 6.0
    is_endgame: int = 0
    village_alive: float = 3.0
    wolf_alive: float = 2.0
    camp_balance_ratio: float = 1.0  # village_alive / wolf_alive

    # ---- Target features ----
    target_role_is_good: int = -1  # -1 = no target
    target_role_is_wolf: int = -1
    target_alive: int = -1
    target_is_exposed: int = -1

    # ---- Outcome features ----
    target_died: int = -1
    target_died_reason_hunter: int = 0
    target_died_reason_vote: int = 0
    target_died_reason_wolf: int = 0
    target_died_reason_witch: int = 0

    # ---- Action features ----
    action_is_llm: int = 1
    action_is_fallback: int = 0
    action_parse_success: int = 1

    # ---- Embedding retrieval features (§6.3) ----
    nearest_good_similarity: float = 0.0
    nearest_bad_similarity: float = 0.0
    good_bad_similarity_margin: float = 0.0
    similar_good_avg_quality: float = 0.0
    similar_bad_avg_quality: float = 0.0

    # ---- Private-context features (V7-aware) ----
    private_has_confirmed_wolf: int = 0
    private_has_confirmed_good: int = 0
    target_is_private_confirmed_wolf: int = 0
    target_is_private_confirmed_good: int = 0
    private_info_should_release: int = 0
    private_info_was_released: int = 0
    private_info_withheld: int = 0
    voted_elsewhere_despite_known_wolf: int = 0
    risky_private_info_release: int = 0
    consecutive_same_guard_target: int = 0

    # ---- Dynamic wolf-specific quality features (float 0-1, NOT hard caps) ----
    wolf_perspective_leak_score: float = 0.0
    teammate_overprotection: float = 0.0
    vote_coordination_failure: float = 0.0
    night_kill_target_value: float = 0.5
    counterfactual_target_gap: float = 0.0
    speech_grounding_score: float = 0.5
    role_goal_conflict_score: float = 0.0
    lack_of_public_evidence_support: float = 0.0

    def to_array(self) -> np.ndarray:
        return np.array(
            [
                self.role_seer,
                self.role_witch,
                self.role_guard,
                self.role_hunter,
                self.role_werewolf,
                self.role_villager,
                self.op_seer_check,
                self.op_witch_save,
                self.op_witch_poison,
                self.op_guard_protect,
                self.op_hunter_shot,
                self.op_werewolf_kill,
                self.op_vote,
                self.op_speech,
                self.day,
                self.alive_count,
                self.is_endgame,
                self.village_alive,
                self.wolf_alive,
                self.camp_balance_ratio,
                self.target_role_is_good,
                self.target_role_is_wolf,
                self.target_alive,
                self.target_is_exposed,
                self.target_died,
                self.target_died_reason_hunter,
                self.target_died_reason_vote,
                self.target_died_reason_wolf,
                self.target_died_reason_witch,
                self.action_is_llm,
                self.action_is_fallback,
                self.action_parse_success,
                self.nearest_good_similarity,
                self.nearest_bad_similarity,
                self.good_bad_similarity_margin,
                self.similar_good_avg_quality,
                self.similar_bad_avg_quality,
                # Private-context features (10 new fields)
                self.private_has_confirmed_wolf,
                self.private_has_confirmed_good,
                self.target_is_private_confirmed_wolf,
                self.target_is_private_confirmed_good,
                self.private_info_should_release,
                self.private_info_was_released,
                self.private_info_withheld,
                self.voted_elsewhere_despite_known_wolf,
                self.risky_private_info_release,
                self.consecutive_same_guard_target,
                # Dynamic wolf-specific features (6 new float fields)
                self.wolf_perspective_leak_score,
                self.teammate_overprotection,
                self.vote_coordination_failure,
                self.night_kill_target_value,
                self.counterfactual_target_gap,
                self.speech_grounding_score,
                self.role_goal_conflict_score,
                self.lack_of_public_evidence_support,
            ],
            dtype=np.float32,
        )

    FEATURE_NAMES = [
        "role_seer",
        "role_witch",
        "role_guard",
        "role_hunter",
        "role_werewolf",
        "role_villager",
        "op_seer_check",
        "op_witch_save",
        "op_witch_poison",
        "op_guard_protect",
        "op_hunter_shot",
        "op_werewolf_kill",
        "op_vote",
        "op_speech",
        "day",
        "alive_count",
        "is_endgame",
        "village_alive",
        "wolf_alive",
        "camp_balance_ratio",
        "target_role_is_good",
        "target_role_is_wolf",
        "target_alive",
        "target_is_exposed",
        "target_died",
        "target_died_reason_hunter",
        "target_died_reason_vote",
        "target_died_reason_wolf",
        "target_died_reason_witch",
        "action_is_llm",
        "action_is_fallback",
        "action_parse_success",
        "nearest_good_similarity",
        "nearest_bad_similarity",
        "good_bad_similarity_margin",
        "similar_good_avg_quality",
        "similar_bad_avg_quality",
        "private_has_confirmed_wolf",
        "private_has_confirmed_good",
        "target_is_private_confirmed_wolf",
        "target_is_private_confirmed_good",
        "private_info_should_release",
        "private_info_was_released",
        "private_info_withheld",
        "voted_elsewhere_despite_known_wolf",
        "risky_private_info_release",
        "consecutive_same_guard_target",
        "wolf_perspective_leak_score",
        "teammate_overprotection",
        "vote_coordination_failure",
        "night_kill_target_value",
        "counterfactual_target_gap",
        "speech_grounding_score",
        "role_goal_conflict_score",
        "lack_of_public_evidence_support",
    ]


def extract_features(opportunity: dict[str, Any]) -> ModelFeatures:
    """Extract ModelFeatures from a DecisionOpportunity dict."""
    role = opportunity.get("role", "")
    op_type = opportunity.get("opportunity_type", "")
    game_feat = opportunity.get("game_features", {})
    target_feat = opportunity.get("target_features", {})
    outcome_feat = opportunity.get("outcome_features", {})
    chosen = opportunity.get("chosen_action", {})
    if not isinstance(chosen, dict):
        chosen = {}

    # Role encoding
    feats = ModelFeatures()
    role_map = {
        "Seer": "role_seer",
        "Witch": "role_witch",
        "Guard": "role_guard",
        "Hunter": "role_hunter",
        "Werewolf": "role_werewolf",
        "Villager": "role_villager",
    }
    if role in role_map:
        setattr(feats, role_map[role], 1)

    # Opportunity type encoding
    op_map = {
        "seer_check": "op_seer_check",
        "witch_save": "op_witch_save",
        "witch_poison": "op_witch_poison",
        "guard_protect": "op_guard_protect",
        "hunter_shot": "op_hunter_shot",
        "werewolf_kill": "op_werewolf_kill",
        "vote": "op_vote",
        "speech": "op_speech",
    }
    if op_type in op_map:
        setattr(feats, op_map[op_type], 1)

    # Game context
    feats.day = float(opportunity.get("day", 1))
    feats.alive_count = float(game_feat.get("alive_count", 6))
    feats.is_endgame = 1 if game_feat.get("is_endgame") else 0
    cb = game_feat.get("camp_balance", {})
    feats.village_alive = float(cb.get("village_alive", 3))
    feats.wolf_alive = float(cb.get("wolf_alive", 2))
    feats.camp_balance_ratio = feats.village_alive / max(feats.wolf_alive, 1)

    # Target features
    if target_feat:
        alignment = target_feat.get("target_alignment", "")
        feats.target_role_is_good = 1 if alignment == "village" else 0
        feats.target_role_is_wolf = 1 if alignment == "wolf" else 0
        feats.target_alive = 1 if target_feat.get("target_alive") else 0
        feats.target_is_exposed = 1 if target_feat.get("target_is_exposed") else 0

    # Outcome features
    if outcome_feat:
        feats.target_died = 1 if outcome_feat.get("target_died_same_phase") else 0
        reason = outcome_feat.get("target_died_reason", "") or ""
        for r, field in [
            ("hunter", "target_died_reason_hunter"),
            ("vote", "target_died_reason_vote"),
            ("wolf", "target_died_reason_wolf"),
            ("witch", "target_died_reason_witch"),
        ]:
            if r in reason:
                setattr(feats, field, 1)

    # Action features
    metadata = chosen.get("metadata", {}) if isinstance(chosen, dict) else {}
    feats.action_is_llm = 1 if metadata.get("source") == "llm" else 0
    feats.action_is_fallback = 1 if metadata.get("fallback") else 0
    feats.action_parse_success = 0 if metadata.get("fallback") else 1

    # ---- Private-context features ----
    _extract_private_context(feats, opportunity, role, op_type)

    return feats


def _extract_private_context(
    feats: ModelFeatures,
    opportunity: dict[str, Any],
    role: str,
    op_type: str,
) -> None:
    """Populate private-context features from the opportunity's private_context_summary.

    Parses the human-readable private context to extract:
    - known_wolf_ids / known_good_ids
    - whether the Seer should have released info
    - whether the Witch leaked secrets
    - whether Guard repeated same target
    """
    import re

    private_ctx_raw = opportunity.get("private_context_summary", "") or ""
    chosen = opportunity.get("chosen_action", {})
    if not isinstance(chosen, dict):
        chosen = {}
    speech_text = str(chosen.get("speech", "") or "")
    target_id = str(chosen.get("target_id", "") or "")
    target_feat = opportunity.get("target_features", {}) or {}

    # Parse JSON if private_ctx is a JSON string (common in fixture decisions)
    private_ctx = ""
    if isinstance(private_ctx_raw, dict):
        private_ctx = json.dumps(private_ctx_raw, ensure_ascii=False)
    elif isinstance(private_ctx_raw, str):
        if private_ctx_raw.startswith("{") and private_ctx_raw.endswith("}"):
            try:
                parsed = json.loads(private_ctx_raw)
                if isinstance(parsed, dict):
                    private_ctx = " ".join(str(v) for v in parsed.values())
                else:
                    private_ctx = private_ctx_raw
            except (json.JSONDecodeError, TypeError):
                private_ctx = private_ctx_raw
        else:
            private_ctx = private_ctx_raw
    else:
        private_ctx = str(private_ctx_raw)

    # Parse known wolves/goods from private context
    known_wolf_ids: set[str] = set()
    known_good_ids: set[str] = set()

    # Pattern: "查验 P1 是狼人" / "P1 是狼" / "checked P1 wolf"
    wolf_patterns = [
        r"(?:查验|查到|验到|查了|验了)\s*(\w+)\s*(?:是|为)?\s*(?:狼|wolf)",
        r"(\w+)\s*(?:是|为)\s*(?:狼人|狼|wolf)",
        r"P\d+\s*(?:是|为)?\s*(?:狼|wolf)",
        r"know.*?(\w+).*?(?:wolf|狼)",
    ]
    for pat in wolf_patterns:
        for m in re.finditer(pat, private_ctx, re.IGNORECASE):
            pid = m.group(1) if m.lastindex and m.lastindex >= 1 else m.group(0)
            pid = str(pid).strip().upper()
            if pid.startswith("P") and len(pid) >= 2:
                known_wolf_ids.add(pid)

    # Pattern: "金水" / "好人" / "good"
    good_patterns = [
        r"(?:金水|查验\s*\w+\s*(?:是|为)?\s*(?:好|good))",
        r"(\w+)\s*(?:是|为)\s*(?:好人|金水)",
    ]
    for pat in good_patterns:
        for m in re.finditer(pat, private_ctx, re.IGNORECASE):
            pid = str(m.group(0)).strip().upper()
            for part in pid.split():
                if part.startswith("P") and len(part) >= 2:
                    known_good_ids.add(part)

    # Wolf self-knowledge: "我是狼人" / "I am wolf" without specific P-ID
    if role in ("Werewolf", "WhiteWolfKing"):
        if any(kw in private_ctx for kw in ["我是狼", "我是狼人", "狼人身份", "狼队友"]):
            player_id_for_self = opportunity.get("player_id", "")
            if player_id_for_self and player_id_for_self.startswith("P"):
                known_wolf_ids.add(player_id_for_self)

    # Also check if private_ctx mentions specific player IDs with wolf/good context
    # Use regex to find P-IDs since Chinese text doesn't have word boundaries
    for match in re.finditer(r"P\d+", private_ctx):
        word = match.group(0).strip().upper()
        start = max(0, match.start() - 20)
        end = min(len(private_ctx), match.end() + 30)
        ctx_around = private_ctx[start:end]
        if any(kw in ctx_around for kw in ["狼", "wolf", "查杀", "队友"]):
            known_wolf_ids.add(word)
        if any(kw in ctx_around for kw in ["金水", "好人", "good"]):
            known_good_ids.add(word)

    # Set basic private knowledge
    feats.private_has_confirmed_wolf = 1 if known_wolf_ids else 0
    feats.private_has_confirmed_good = 1 if known_good_ids else 0

    # Target vs private knowledge
    if target_id and target_id in known_wolf_ids:
        feats.target_is_private_confirmed_wolf = 1
    if target_id and target_id in known_good_ids:
        feats.target_is_private_confirmed_good = 1

    # Seer: should release info during speech/vote
    should_release = 0
    was_released = 0
    if role == "Seer" and known_wolf_ids:
        if op_type in ("speech", "seer_release", "vote"):
            should_release = 1
        # Check if speech text mentions the known wolf
        release_keywords = ["查杀", "查了", "验了", "查验", "狼", "wolf", "divine", "check"]
        for wid in known_wolf_ids:
            if str(wid) in speech_text and any(kw in speech_text.lower() for kw in release_keywords):
                was_released = 1
                break

    feats.private_info_should_release = should_release
    feats.private_info_was_released = was_released
    feats.private_info_withheld = 1 if (should_release and not was_released) else 0

    # Seer: voted elsewhere despite known wolf
    voted_elsewhere = 0
    if role == "Seer" and known_wolf_ids and op_type == "vote":
        if target_id and target_id not in known_wolf_ids:
            # Target is village-side and Seer knew a wolf → bad
            if target_feat.get("target_alignment") == "village":
                voted_elsewhere = 1
    feats.voted_elsewhere_despite_known_wolf = voted_elsewhere

    # Risky private info release (Witch/Guard exposing secrets in speech)
    risky = 0
    if op_type in ("speech", "seer_release"):
        risky_keywords = ["被刀", "刀口", "昨晚刀", "解药", "毒药", "女巫", "守了", "守卫身份", "我是守卫", "我是女巫"]
        if any(kw in speech_text for kw in risky_keywords):
            if role in ("Witch", "Guard"):
                risky = 1
    feats.risky_private_info_release = risky

    # Guard consecutive same target
    consecutive_guard = 0
    if role == "Guard" and op_type == "guard_protect":
        # Check if private context mentions "last target" or same target pattern
        if "same" in private_ctx.lower() or "连续" in private_ctx or "again" in private_ctx.lower():
            consecutive_guard = 1
        # Also check if target is self (self-guard is less valuable)
    # For consecutive guard detection, we need access to prior actions.
    # As a heuristic: self-guard on night 2+ is suspicious.
    day = int(opportunity.get("day", 1))
    if role == "Guard" and op_type == "guard_protect" and day >= 2:
        # Check if target is the guard themselves
        player_id = opportunity.get("player_id", "")
        if target_id and target_id == player_id:
            consecutive_guard = 1  # Heuristic: self-guard on N2+ likely consecutive
    feats.consecutive_same_guard_target = consecutive_guard

    # ---- Dynamic wolf-specific features ----
    _extract_wolf_dynamic_features(feats, opportunity, role, op_type, speech_text, target_id, known_wolf_ids)


def _extract_wolf_dynamic_features(
    feats: ModelFeatures,
    opportunity: dict[str, Any],
    role: str,
    op_type: str,
    speech_text: str,
    target_id: str,
    known_wolf_ids: set[str],
) -> None:
    """Compute dynamic wolf-specific quality features (soft signals 0-1)."""
    target_feat = opportunity.get("target_features", {}) or {}
    game_feat = opportunity.get("game_features", {}) or {}
    player_id = opportunity.get("player_id", "")
    str(opportunity.get("private_context_summary", "") or "")
    chosen = opportunity.get("chosen_action", {})
    if not isinstance(chosen, dict):
        chosen = {}

    is_wolf = role in ("Werewolf", "WhiteWolfKing")

    # 1. wolf_perspective_leak_score: speech reveals wolf-only knowledge
    leak_score = 0.0
    if is_wolf and op_type in ("speech", "seer_release") and speech_text:
        leak_keywords = ["我们狼", "刀口不是", "昨晚刀", "狼队友", "狼队", "同伴", "夜里"]
        exact_leak = ["我们狼", "我狼", "狼队刀", "是我们刀"]
        for kw in exact_leak:
            if kw in speech_text:
                leak_score = max(leak_score, 0.9)
                break
        if leak_score < 0.9:
            kw_count = sum(1 for kw in leak_keywords if kw in speech_text)
            if kw_count >= 1:
                leak_score = 0.6 + 0.1 * min(kw_count - 1, 3)
        # Also check for unnatural certainty about night info
        night_certainty = ["昨晚刀口", "刀法", "盲刀", "首刀", "刀了"]
        if any(kw in speech_text for kw in night_certainty):
            if any(kw in speech_text.lower() for kw in ["肯定", "一定", "绝对", "显然"]):
                leak_score = max(leak_score, 0.5)
    feats.wolf_perspective_leak_score = round(min(1.0, leak_score), 4)

    # 2. teammate_overprotection: wolf hard-defends checked teammate without evidence
    overprotection = 0.0
    if is_wolf and known_wolf_ids and op_type in ("speech", "seer_release", "vote") and speech_text:
        # Only check for defending OTHERS, not self
        other_wolf_ids = {wid for wid in known_wolf_ids if wid != player_id}
        defending_teammate = any(wid in speech_text for wid in other_wolf_ids)
        # Light cut phrases indicate GOOD wolf play, not teammate overprotection.
        light_cut = any(
            kw in speech_text
            for kw in [
                "不强保",
                "不硬保",
                "不好硬保",
                "按查杀走",
                "先出",
                "不保",
                "切割",
                "牺牲",
                "强行保",
                "队友感",
                "站不住",
                "无法力挺",
                "先跟好人走",
                "跟好人走",
                "不确定",
            ]
        )
        has_evidence = any(
            kw in speech_text.lower()
            for kw in [
                "因为",
                "证据",
                "查验",
                "投票记录",
                "发言记录",
                "行为",
                "逻辑",
                "金水",
                "银水",
                "刀法",
                "票型",
                "解释",
                "原因",
            ]
        )
        if defending_teammate:
            if light_cut:
                overprotection = 0.0  # Light cutting is good wolf play
            elif not has_evidence:
                overprotection = 0.7
                if any(kw in speech_text for kw in ["一定好", "肯定是好", "绝对是好", "铁好人"]):
                    overprotection = 0.9
            else:
                overprotection = 0.3
    feats.teammate_overprotection = round(min(1.0, overprotection), 4)

    # 3. vote_coordination_failure: wolf votes don't help the pack
    vote_failure = 0.0
    if is_wolf and op_type == "vote" and target_id:
        # Voting own teammate who is publicly exposed = smart sacrifice, not failure
        target_is_known_wolf = target_id in known_wolf_ids
        if target_is_known_wolf:
            # Check if the teammate is already doomed (publicly checked by Seer)
            # In that case, voting them is a GOOD strategic sacrifice
            key_exposed = game_feat.get("key_roles_exposed", [])
            if "预言家" in str(key_exposed) or "Seer" in str(key_exposed):
                vote_failure = 0.0  # Smart sacrifice to reduce linkage
            else:
                vote_failure = 0.5  # Unnecessary cross-vote
        elif target_feat.get("target_alignment") == "wolf":
            vote_failure = 0.9  # Voting non-known wolf teammate
        elif target_feat.get("target_alignment") == "village":
            target_role = target_feat.get("target_role", "")
            if known_wolf_ids:
                vote_failure = 0.5  # Splitting vote when teammate needs help
            if target_role in ("Seer", "Witch"):
                vote_failure = max(0.0, vote_failure - 0.3)
            elif target_role in ("Guard", "Hunter"):
                vote_failure = max(0.0, vote_failure - 0.1)
    feats.vote_coordination_failure = round(min(1.0, vote_failure), 4)

    # 4. night_kill_target_value: dynamic value of the kill target
    if op_type == "werewolf_kill" and target_id:
        target_role = target_feat.get("target_role", "")
        target_align = target_feat.get("target_alignment", "")
        target_exposed = target_feat.get("target_is_exposed", False)

        # Role value baseline
        role_value = {
            "Seer": 0.95,
            "Witch": 0.90,
            "Guard": 0.80,
            "Hunter": 0.70,
            "Villager": 0.30,
        }.get(target_role, 0.40)

        # Boost for exposed power roles
        if target_exposed and target_align == "village":
            role_value = min(1.0, role_value + 0.15)
        # Penalty for killing confirmed non-threat
        if target_role == "Villager" and not target_exposed:
            role_value = 0.25

        feats.night_kill_target_value = role_value
    elif op_type == "werewolf_kill":
        feats.night_kill_target_value = 0.3  # Unknown target, conservatively low

    # 5. counterfactual_target_gap: difference vs best available target
    if op_type == "werewolf_kill":
        current_value = feats.night_kill_target_value
        # Estimate best available target from exposed roles
        best_value = 0.3
        key_exposed = game_feat.get("key_roles_exposed", [])
        if "预言家" in str(key_exposed) or "Seer" in str(key_exposed):
            best_value = max(best_value, 0.95)
        if "女巫" in str(key_exposed) or "Witch" in str(key_exposed):
            best_value = max(best_value, 0.90)
        if "守卫" in str(key_exposed) or "Guard" in str(key_exposed):
            best_value = max(best_value, 0.80)
        if not key_exposed:  # No exposed roles, any kill is uncertain
            best_value = max(best_value, 0.5)
        feats.counterfactual_target_gap = round(max(0.0, best_value - current_value), 4)

    # 6. speech_grounding_score: does wolf speech reference public facts?
    grounding = 0.5  # Default neutral
    if op_type in ("speech", "seer_release") and speech_text:
        # Check for references to public events
        references = [
            "查验",
            "查杀",
            "金水",
            "投票",
            "票型",
            "发言",
            "昨天",
            "刚才",
            "这轮",
            "上轮",
            "之前",
            "P1",
            "P2",
            "P3",
            "P4",
            "P5",
            "P6",
            "P7",
            "因为",
            "所以",
            "证据",
            "逻辑",
            "综上",
        ]
        ref_count = sum(1 for r in references if r in speech_text)
        grounding = 0.3 + 0.07 * min(ref_count, 10)

        # Penalty for pure assertion without reference
        pure_assertion = ["一定", "肯定", "就是", "绝对是", "铁", "不用想"]
        assertion_count = sum(1 for a in pure_assertion if a in speech_text)
        if assertion_count >= 2 and ref_count < 3:
            grounding = max(0.1, grounding - 0.3)
    feats.speech_grounding_score = round(min(1.0, max(0.0, grounding)), 4)

    # 7. role_goal_conflict_score: how much does this action conflict with role goals?
    goal_conflict = 0.0
    if is_wolf:
        if op_type == "speech" and feats.wolf_perspective_leak_score > 0.3:
            goal_conflict = 0.7  # Wolf exposing themselves conflicts with hiding
        if op_type == "vote" and feats.vote_coordination_failure > 0.3:
            goal_conflict = max(goal_conflict, 0.5)  # Split vote = coordination failure
        if op_type == "werewolf_kill" and feats.counterfactual_target_gap > 0.5:
            goal_conflict = max(goal_conflict, 0.6)  # Killing low-value target
    # For non-wolves, goal conflict from bad private info handling
    if role == "Seer" and feats.private_info_withheld:
        goal_conflict = 0.8  # Seer not releasing wolf check conflicts with info role
    if role == "Witch" and op_type == "witch_poison" and feats.target_role_is_good == 1:
        goal_conflict = 0.9  # Witch poisoning village is role-goal failure
    if role == "Hunter" and op_type == "hunter_shot" and feats.target_role_is_good == 1:
        goal_conflict = 0.9
    feats.role_goal_conflict_score = round(min(1.0, goal_conflict), 4)

    # 8. lack_of_public_evidence_support: action lacks public fact grounding
    evidence_lack = 0.0
    if op_type in ("speech", "seer_release", "vote"):
        # Check speech grounding + whether target has exposed role info
        grounding_gap = max(0.0, 0.5 - feats.speech_grounding_score)
        # For wolves defending teammates without evidence
        if is_wolf and feats.teammate_overprotection > 0.5:
            evidence_lack = 0.7
        # General: low grounding + making strong claims
        if grounding_gap > 0.2:
            evidence_lack = max(evidence_lack, 0.4)
        if feats.voted_elsewhere_despite_known_wolf:
            evidence_lack = max(evidence_lack, 0.8)  # Voting against own private info
    feats.lack_of_public_evidence_support = round(min(1.0, evidence_lack), 4)


# ---------------------------------------------------------------------------
# Scikit-learn wrapper models
# ---------------------------------------------------------------------------


class OpportunityValueModel:
    """w(o): predict how important an opportunity is. §5.1"""

    def __init__(self):
        self.model = None
        self.feature_importances_: dict[str, float] = {}

    def fit(self, X: np.ndarray, y: np.ndarray):
        from sklearn.linear_model import LogisticRegression

        self.model = LogisticRegression(max_iter=1000, class_weight="balanced")
        # Median split for binary classification (high-value vs low-value opportunity)
        threshold = float(np.median(y)) if len(y) > 0 else 0.5
        y_binary = (y >= threshold).astype(int)
        if len(set(y_binary)) < 2:
            raise ValueError("Need at least 2 classes to train OpportunityValueModel")
        self.model.fit(X, y_binary)
        self.feature_importances_ = dict(zip(ModelFeatures.FEATURE_NAMES, np.abs(self.model.coef_[0])))

    def predict(self, X: np.ndarray) -> np.ndarray:
        if self.model is None or not hasattr(self.model, "classes_"):
            import warnings

            warnings.warn(
                "OpportunityValueModel.predict() called on untrained model, returning 0.5. Run train_and_ablate.py first.",
                stacklevel=2,
            )
            return np.full(len(X), 0.5)
        return self.model.predict_proba(X)[:, 1]

    def save(self, path: str | Path):
        with open(path, "wb") as f:
            pickle.dump({"model": self.model, "importances": self.feature_importances_}, f)

    def load(self, path: str | Path):
        data = self._robust_load(path)
        self.model = data["model"]
        self.feature_importances_ = data.get("importances", {})

    @staticmethod
    def _robust_load(path: str | Path):
        """Load model data with cross-version compatibility fallback.

        Tries in order:
          1. Standard pickle
          2. Numpy cross-version patch (numpy 1.x reading 2.x pickles)
          3. joblib (if available)
          4. Encoding fallback for py3.11+/scipy version mismatch

        Raises:
            FileNotFoundError: file doesn't exist.
            RuntimeError: all loading strategies failed.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Model file not found: {path}")

        # Strategy 1: Standard pickle
        try:
            with open(path, "rb") as f:
                return pickle.load(f)
        except Exception as e1:
            warnings.warn(f"Standard pickle load failed for {path}: {e1}", stacklevel=2)

        # Strategy 2: Numpy cross-version compat via custom Unpickler
        # Redirects numpy._core → numpy.core for models saved with numpy 2.x
        # when loaded in numpy 1.x environments.
        try:

            class _NumpyCompatUnpickler(pickle.Unpickler):
                def find_class(self, module, name):
                    if module.startswith("numpy._core"):
                        module = module.replace("numpy._core", "numpy.core")
                    return super().find_class(module, name)

            with open(path, "rb") as f:
                result = _NumpyCompatUnpickler(f).load()
            return result
        except Exception as e2:
            warnings.warn(f"Numpy cross-version fallback also failed for {path}: {e2}", stacklevel=2)

        # Strategy 3: joblib
        if _HAS_JOBLIB:
            try:
                return _joblib.load(path)
            except Exception as e3:
                warnings.warn(f"Joblib fallback also failed for {path}: {e3}", stacklevel=2)

        # Strategy 4: Encoding-tolerant pickle (handles py3.11+ scipy.__getattr__ changes)
        try:
            with open(path, "rb") as f:
                raw = f.read()
            # Try with different protocol versions
            for _proto in (pickle.HIGHEST_PROTOCOL, pickle.DEFAULT_PROTOCOL):
                try:
                    return pickle.loads(raw)
                except Exception:
                    continue
            raise RuntimeError("All encoding fallbacks exhausted")
        except Exception as e4:
            raise RuntimeError(
                f"Failed to load model from {path}: all strategies exhausted. "
                f"Original error: {e4}. Re-run: python scripts/train_and_ablate.py"
            ) from e4


class DecisionQualityModel:
    """q(o): predict action quality. §5.2 — pairwise training preferred."""

    def __init__(self):
        self.model = None
        self.feature_importances_: dict[str, float] = {}

    def fit(self, X: np.ndarray, y: np.ndarray):
        from sklearn.ensemble import GradientBoostingClassifier

        self.model = GradientBoostingClassifier(
            n_estimators=100,
            max_depth=4,
            learning_rate=0.05,
            random_state=42,
        )
        self.model.fit(X, y)
        self.feature_importances_ = dict(zip(ModelFeatures.FEATURE_NAMES, self.model.feature_importances_))

    def predict(self, X: np.ndarray) -> np.ndarray:
        if self.model is None or not hasattr(self.model, "classes_"):
            import warnings

            warnings.warn(
                "DecisionQualityModel.predict() called on untrained model, returning 0.5. Run train_and_ablate.py first.",
                stacklevel=2,
            )
            return np.full(len(X), 0.5)
        return self.model.predict_proba(X)[:, 1]

    def predict_pairwise(self, X_a: np.ndarray, X_b: np.ndarray) -> np.ndarray:
        """P(A > B) = sigmoid(F(A) - F(B)). §5.2"""
        scores_a = self.predict(X_a)
        scores_b = self.predict(X_b)
        diff = scores_a - scores_b
        return 1.0 / (1.0 + np.exp(-diff))

    def save(self, path: str | Path):
        with open(path, "wb") as f:
            pickle.dump({"model": self.model, "importances": self.feature_importances_}, f)

    def load(self, path: str | Path):
        data = OpportunityValueModel._robust_load(path)
        self.model = data["model"]
        self.feature_importances_ = data.get("importances", {})


class MistakeSeverityModel:
    """severity(b): predict mistake severity. §5.3"""

    def __init__(self):
        self.model = None

    def fit(self, X: np.ndarray, y: np.ndarray):
        from sklearn.linear_model import Ridge

        self.model = Ridge(alpha=1.0)
        self.model.fit(X, y)

    def predict(self, X: np.ndarray) -> np.ndarray:
        if self.model is None or not hasattr(self.model, "coef_"):
            import warnings

            warnings.warn(
                "MistakeSeverityModel.predict() called on untrained model, returning 0.5. Run train_and_ablate.py first.",
                stacklevel=2,
            )
            return np.full(len(X), 0.5)
        return np.clip(self.model.predict(X), 0.0, 1.0)

    def save(self, path: str | Path):
        with open(path, "wb") as f:
            pickle.dump(self.model, f)

    def load(self, path: str | Path):
        try:
            self.model = OpportunityValueModel._robust_load(path)
        except (TypeError, ValueError, AttributeError, FileNotFoundError):
            # If robust_load can't handle it either, try direct pickle
            with open(path, "rb") as f:
                self.model = pickle.load(f)


# ---------------------------------------------------------------------------
# ProcessScore calculator (§2.11)
# ---------------------------------------------------------------------------


@dataclass
class ProcessScoreResult:
    """Per-player process score breakdown."""

    player_id: str
    role: str
    adjusted_role_process_score: float
    speech_score: float
    counterfactual_impact: float
    mistake_penalty: float
    robustness_score: float
    process_score: float
    num_opportunities: int
    total_weight: float


def calculate_process_score(
    opportunities: list[dict[str, Any]],
    opportunity_value_model: OpportunityValueModel | None = None,
    decision_quality_model: DecisionQualityModel | None = None,
    speech_scores: dict[str, float] | None = None,
) -> list[ProcessScoreResult]:
    """Calculate process scores following goal doc §2.4-2.11."""
    from collections import defaultdict

    # Group by player
    by_player: dict[str, list[dict]] = defaultdict(list)
    for opp in opportunities:
        by_player[opp["player_id"]].append(opp)

    results: list[ProcessScoreResult] = []
    w_model = opportunity_value_model
    q_model = decision_quality_model

    for player_id, opps in by_player.items():
        role = opps[0].get("role", "unknown")

        # Compute opportunity-level scores
        weights = []
        qualities = []
        for opp in opps:
            feats = extract_features(opp)
            X = feats.to_array().reshape(1, -1)
            w = w_model.predict(X)[0] if w_model else 0.5
            q = q_model.predict(X)[0] if q_model else 0.5
            weights.append(w)
            qualities.append(q)

        total_w = sum(weights)
        role_process = sum(w * q for w, q in zip(weights, qualities)) / total_w if total_w > 0 else 0.5

        # Bayesian smoothing for low-opportunity roles (§2.6)
        k = 2.0
        mu_role = 0.5  # Default mean; should be calibrated per role
        alpha = total_w / (total_w + k)
        adjusted_process = alpha * role_process + (1 - alpha) * mu_role

        # Speech score
        speech = speech_scores.get(player_id, 0.5) if speech_scores else 0.5

        # Robustness
        n_opps = len(opps)
        n_fallback = sum(1 for o in opps if o.get("chosen_action", {}).get("metadata", {}).get("fallback"))
        robustness = 1.0 - (n_fallback / max(n_opps, 1))

        # Simplified mistake penalty and counterfactual (placeholder for MVP)
        mistake_penalty = 0.0
        counterfactual_impact = 0.0

        # Process score formula (§2.11)
        process_score = (
            0.40 * adjusted_process
            + 0.20 * speech
            + 0.15 * counterfactual_impact
            + 0.15 * (1.0 - mistake_penalty)
            + 0.10 * robustness
        )

        results.append(
            ProcessScoreResult(
                player_id=player_id,
                role=role,
                adjusted_role_process_score=round(adjusted_process, 4),
                speech_score=round(speech, 4),
                counterfactual_impact=round(counterfactual_impact, 4),
                mistake_penalty=round(mistake_penalty, 4),
                robustness_score=round(robustness, 4),
                process_score=round(process_score, 4),
                num_opportunities=n_opps,
                total_weight=round(total_w, 2),
            )
        )

    return results


# ---------------------------------------------------------------------------
# Calibration layer: rule-backed adjustments to raw model Q scores
# ---------------------------------------------------------------------------


@dataclass
class CalibratedScore:
    """Score with calibration metadata."""

    raw_model_q: float
    calibrated_q: float
    calibration_reasons: list[str] = field(default_factory=list)
    calibration_components: dict[str, float] = field(default_factory=dict)


def calibrate_decision_quality(
    opportunity: dict[str, Any],
    raw_q: float,
) -> CalibratedScore:
    """Soft calibration based on quantifiable dynamic features.

    NO hard caps (min(q, X)). All adjustments are weighted by feature
    values — the model should learn these from pairwise training data.
    Calibration only provides mild guidance for extreme feature values.
    """
    reasons: list[str] = []
    components: dict[str, float] = {}
    q = raw_q
    role = opportunity.get("role", "")
    op_type = opportunity.get("opportunity_type", "")
    opportunity.get("target_features", {}) or {}
    is_wolf = role in ("Werewolf", "WhiteWolfKing")

    feats = extract_features(opportunity)
    chosen_action = opportunity.get("chosen_action", {})
    if not isinstance(chosen_action, dict):
        chosen_action = {}
    speech_text = str(chosen_action.get("speech", "") or "")

    # ---- Soft adjustments based on quantifiable feature values ----
    # Each penalty = feature_weight * feature_value, where feature_value ∈ [0, 1]
    # The model should learn these weights from pairwise training.

    # Witch poisons village → penalty proportional to target_is_good
    if op_type == "witch_poison" and feats.target_role_is_good == 1:
        penalty = 0.55  # Strong penalty: poisoning good is quantifiably bad
        q = max(0.0, q - penalty)
        reasons.append("witch_poison_target_village")
        components["witch_poison_penalty"] = penalty

    # Hunter shoots village → penalty proportional to target_is_good
    if op_type == "hunter_shot" and feats.target_role_is_good == 1:
        penalty = 0.55
        q = max(0.0, q - penalty)
        reasons.append("hunter_shot_target_village")
        components["hunter_shot_penalty"] = penalty

    # Seer withheld confirmed wolf check
    if feats.private_info_withheld:
        penalty = 0.50
        q = max(0.0, q - penalty)
        reasons.append("private_info_withheld")
        components["withheld_penalty"] = penalty

    # Seer voted elsewhere despite known wolf
    if feats.voted_elsewhere_despite_known_wolf:
        penalty = 0.50
        q = max(0.0, q - penalty)
        reasons.append("voted_elsewhere_despite_known_wolf")
        components["voted_elsewhere_penalty"] = penalty

    # Guard consecutive same target
    if feats.consecutive_same_guard_target:
        penalty = 0.40
        q = max(0.0, q - penalty)
        reasons.append("consecutive_same_guard_target")
        components["consecutive_guard_penalty"] = penalty

    # Risky private info release (Witch/Guard exposing secrets)
    if feats.risky_private_info_release:
        penalty = 0.30
        q = max(0.0, q - penalty)
        reasons.append("risky_private_info_release")
        components["risky_private_penalty"] = penalty

    # Wolf perspective leak — penalty proportional to leak score
    if is_wolf and feats.wolf_perspective_leak_score > 0.0:
        penalty = 0.60 * feats.wolf_perspective_leak_score  # 0.9 → 0.54
        if penalty > 0.01:
            q = max(0.0, q - penalty)
            reasons.append("wolf_perspective_leak")
            components["wolf_leak_penalty"] = round(penalty, 4)

    # Wolf overprotection of teammate — penalty proportional to overprotection
    if is_wolf and feats.teammate_overprotection > 0.0:
        penalty = 0.65 * feats.teammate_overprotection  # 0.7 → 0.455
        if penalty > 0.01:
            q = max(0.0, q - penalty)
            reasons.append("teammate_overprotection")
            components["overprotection_penalty"] = round(penalty, 4)

    # Wolf vote coordination failure
    if is_wolf and feats.vote_coordination_failure > 0.0:
        penalty = 0.55 * feats.vote_coordination_failure  # 0.4 → 0.22
        if penalty > 0.01:
            q = max(0.0, q - penalty)
            reasons.append("vote_coordination_failure")
            components["vote_failure_penalty"] = round(penalty, 4)

    # Low-value night kill with significantly better target available
    if op_type == "werewolf_kill" and feats.counterfactual_target_gap > 0.3:
        penalty = 0.75 * feats.counterfactual_target_gap  # 0.7 → 0.525
        if penalty > 0.01:
            q = max(0.0, q - penalty)
            reasons.append("low_value_kill_target")
            components["kill_gap_penalty"] = round(penalty, 4)

    # Ungrounded speech — penalty when grounding score is significantly low
    if op_type in ("speech", "seer_release") and feats.speech_grounding_score < 0.40:
        penalty = 0.30 * (0.50 - feats.speech_grounding_score)
        if penalty > 0.02:
            q = max(0.0, q - penalty)
            reasons.append("speech_ungrounded")
            components["ungrounded_penalty"] = round(penalty, 4)

    # Role goal conflict — penalty proportional to conflict score
    if feats.role_goal_conflict_score > 0.2:
        penalty = 0.30 * feats.role_goal_conflict_score
        if penalty > 0.01:
            q = max(0.0, q - penalty)
            reasons.append("role_goal_conflict")
            components["goal_conflict_penalty"] = round(penalty, 4)

    # Lack of public evidence support — penalty for ungrounded actions
    if feats.lack_of_public_evidence_support > 0.2:
        penalty = 0.25 * feats.lack_of_public_evidence_support
        if penalty > 0.01:
            q = max(0.0, q - penalty)
            reasons.append("lack_of_public_evidence")
            components["evidence_lack_penalty"] = round(penalty, 4)

    # Positive wolf-operation signals keep the evaluator useful when a persisted
    # q-model cannot be loaded and raw_q falls back to a neutral 0.5.
    if (
        is_wolf
        and op_type == "werewolf_kill"
        and feats.night_kill_target_value >= 0.75
        and feats.counterfactual_target_gap <= 0.15
        and feats.role_goal_conflict_score <= 0.1
    ):
        boost = 0.12 * min(1.0, feats.night_kill_target_value)
        q = min(1.0, q + boost)
        reasons.append("high_value_kill_target")
        components["high_value_kill_boost"] = round(boost, 4)

    harmful_clean_speech_terms = [
        "我们狼",
        "我狼",
        "狼队",
        "狼队友",
        "昨晚刀",
        "肯定",
        "一定",
        "绝对",
        "说漏嘴",
        "不想解释",
    ]
    clean_wolf_speech = (
        is_wolf
        and op_type in ("speech", "seer_release")
        and speech_text
        and feats.wolf_perspective_leak_score <= 0.05
        and feats.teammate_overprotection <= 0.25
        and feats.vote_coordination_failure <= 0.05
        and feats.role_goal_conflict_score <= 0.1
        and feats.lack_of_public_evidence_support <= 0.1
        and not any(term in speech_text for term in harmful_clean_speech_terms)
    )
    if clean_wolf_speech:
        boost = 0.10 + 0.04 * max(0.0, feats.speech_grounding_score - 0.4)
        q = min(1.0, q + boost)
        reasons.append("clean_wolf_speech")
        components["clean_wolf_speech_boost"] = round(boost, 4)

    if (
        is_wolf
        and op_type == "vote"
        and feats.target_is_private_confirmed_wolf == 1
        and feats.vote_coordination_failure <= 0.05
        and feats.role_goal_conflict_score <= 0.1
    ):
        boost = 0.08
        q = min(1.0, q + boost)
        reasons.append("strategic_teammate_cut_vote")
        components["teammate_cut_vote_boost"] = boost

    return CalibratedScore(
        raw_model_q=round(raw_q, 4),
        calibrated_q=round(q, 4),
        calibration_reasons=reasons,
        calibration_components=components,
    )


# ---------------------------------------------------------------------------
# Speech score heuristic (rule-based, NOT trained model)
# ---------------------------------------------------------------------------


def compute_speech_scores(opportunities: list[dict[str, Any]]) -> dict[str, float]:
    """Compute per-player speech scores from opportunity data.

    Heuristic (NOT trained model):
    - Base 0.50 for speaking at all
    - +0.25 if mentions other players by ID
    - +0.15 if uses game-relevant reasoning keywords
    - -0.30 if risky_private_info_release (Witch/Guard leaking secrets)
    - -0.30 if private_info_withheld (Seer hiding wolf check)
    - Clamped to [0.0, 1.0]
    """
    from collections import defaultdict

    by_player: dict[str, list[float]] = defaultdict(list)

    for opp in opportunities:
        pid = opp.get("player_id", "")
        op_type = opp.get("opportunity_type", "")
        if op_type not in ("speech", "seer_release"):
            continue

        chosen = opp.get("chosen_action", {})
        if not isinstance(chosen, dict):
            chosen = {}
        speech = str(chosen.get("speech", "") or "")

        score = 0.50  # Base for having a speech

        # Mention other players
        if any(c.isdigit() for c in speech):
            score += 0.25

        # Game-relevant keywords
        reasoning_kw = [
            "狼",
            "vote",
            "票",
            "查杀",
            "金水",
            "嫌疑",
            "归票",
            "验",
            "预言家",
            "女巫",
            "守卫",
            "猎人",
            "村民",
        ]
        if any(kw in speech for kw in reasoning_kw):
            score += 0.15

        # Penalties from private-context features
        feats = extract_features(opp)
        if feats.risky_private_info_release:
            score -= 0.30
        if feats.private_info_withheld:
            score -= 0.30

        by_player[pid].append(max(0.0, min(1.0, score)))

    return {pid: round(sum(scores) / len(scores), 4) for pid, scores in by_player.items()}


# ---------------------------------------------------------------------------
# Process score v2 — private-context-aware aggregation
# ---------------------------------------------------------------------------


def calculate_process_score_v2(
    opportunities: list[dict[str, Any]],
    opportunity_value_model: OpportunityValueModel | None = None,
    decision_quality_model: DecisionQualityModel | None = None,
    speech_scores: dict[str, float] | None = None,
) -> tuple[list[ProcessScoreResult], list[ProcessScoreResult]]:
    """Calculate process scores with private-context calibration.

    Returns (legacy_results, calibrated_results).
    legacy: original formula from calculate_process_score()
    calibrated: new formula with critical/major badcase penalties + speech scores
    """
    from collections import defaultdict

    w_model = opportunity_value_model
    q_model = decision_quality_model

    # First, compute legacy scores
    legacy_results = calculate_process_score(
        opportunities,
        w_model,
        q_model,
        speech_scores,
    )

    # Group by player
    by_player: dict[str, list[dict]] = defaultdict(list)
    for opp in opportunities:
        by_player[opp["player_id"]].append(opp)

    calibrated_results: list[ProcessScoreResult] = []

    for player_id, opps in by_player.items():
        role = opps[0].get("role", "unknown")

        # Compute calibrated qualities
        weighted_qs: list[float] = []
        critical_count = 0
        major_count = 0

        for opp in opps:
            feats = extract_features(opp)
            X = feats.to_array().reshape(1, -1)
            w = w_model.predict(X)[0] if w_model else 0.5
            raw_q = q_model.predict(X)[0] if q_model else 0.5

            cal = calibrate_decision_quality(opp, raw_q)

            # Count badcase severity
            if cal.calibrated_q <= 0.20:
                critical_count += 1
            elif cal.calibrated_q <= 0.35:
                major_count += 1

            weighted_qs.append(w * cal.calibrated_q)

        total_w = sum(
            max(w_model.predict(extract_features(opp).to_array().reshape(1, -1))[0], 0.01) if w_model else 0.5
            for opp in opps
        )

        weighted_decision_quality = sum(weighted_qs) / total_w if total_w > 0 else 0.5

        n_opps = len(opps)
        critical_rate = critical_count / max(n_opps, 1)
        major_rate = major_count / max(n_opps, 1)

        # Role-critical action quality (night actions / key votes)
        role_critical_opps = [
            opp
            for opp in opps
            if opp.get("opportunity_type", "")
            in (
                "werewolf_kill",
                "witch_save",
                "witch_poison",
                "guard_protect",
                "seer_check",
                "hunter_shot",
            )
        ]
        role_critical_qs = []
        for opp in role_critical_opps:
            cal = calibrate_decision_quality(
                opp,
                q_model.predict(extract_features(opp).to_array().reshape(1, -1))[0] if q_model else 0.5,
            )
            role_critical_qs.append(cal.calibrated_q)
        role_critical_action_quality = sum(role_critical_qs) / len(role_critical_qs) if role_critical_qs else 0.5

        # Speech score
        speech = speech_scores.get(player_id, 0.5) if speech_scores else 0.5

        # Robustness
        n_fallback = sum(1 for o in opps if o.get("chosen_action", {}).get("metadata", {}).get("fallback"))
        robustness = 1.0 - (n_fallback / max(n_opps, 1))

        # Outcome impact proxy (placeholder)
        outcome_impact_proxy = 0.5

        # Process score v2 formula
        process_score = (
            0.55 * weighted_decision_quality
            + 0.15 * role_critical_action_quality
            + 0.10 * speech
            + 0.10 * robustness
            + 0.10 * outcome_impact_proxy
            - 0.25 * critical_rate
            - 0.15 * major_rate
        )
        process_score = max(0.0, min(1.0, process_score))

        # Bayesian smoothing
        k = 2.0
        alpha = total_w / (total_w + k)
        mu_role = 0.5
        adjusted_process = alpha * process_score + (1 - alpha) * mu_role

        calibrated_results.append(
            ProcessScoreResult(
                player_id=player_id,
                role=role,
                adjusted_role_process_score=round(adjusted_process, 4),
                speech_score=round(speech, 4),
                counterfactual_impact=0.0,
                mistake_penalty=round(0.25 * critical_rate + 0.15 * major_rate, 4),
                robustness_score=round(robustness, 4),
                process_score=round(process_score, 4),
                num_opportunities=n_opps,
                total_weight=round(total_w, 2),
            )
        )

    return legacy_results, calibrated_results


# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------


def load_track_b_models(
    model_dir: str | Path = "data/health",
    *,
    raise_on_missing: bool = False,
    return_info: bool = False,
):
    """Load trained Track B scoring models from disk with graceful fallback.

    Args:
        model_dir: Directory containing the model pickle files.
        raise_on_missing: If True, raise exceptions on load failure (legacy behaviour).
        return_info: If True, returns (w_model, q_model, load_info) 3-tuple.
                     If False (default), returns (w_model, q_model) 2-tuple for
                     backward compatibility.

    load_info contains:
      - fallback_used: bool
      - fallback_reason: str
      - w_loaded: bool
      - q_loaded: bool

    By default, missing/corrupt models are handled silently with fallback
    untrained models. Set raise_on_missing=True to raise exceptions instead.
    """
    model_dir = Path(model_dir)
    load_info: dict[str, Any] = {
        "fallback_used": False,
        "fallback_reason": "",
        "w_loaded": False,
        "q_loaded": False,
    }

    w_model = OpportunityValueModel()
    w_path = model_dir / "opportunity_value_model.pkl"
    if w_path.exists():
        try:
            w_model.load(w_path)
            load_info["w_loaded"] = True
        except Exception as e:
            msg = f"OpportunityValueModel load failed ({e}), using untrained fallback"
            warnings.warn(msg, stacklevel=2)
            load_info["fallback_used"] = True
            if load_info["fallback_reason"]:
                load_info["fallback_reason"] += "; "
            load_info["fallback_reason"] += f"w_model: {type(e).__name__}"
            if raise_on_missing:
                raise RuntimeError(msg) from e
    else:
        msg = f"OpportunityValueModel not found at {w_path}, using untrained fallback"
        warnings.warn(msg, stacklevel=2)
        load_info["fallback_used"] = True
        load_info["fallback_reason"] += "w_model: file missing"
        if raise_on_missing:
            raise FileNotFoundError(msg)

    q_model = DecisionQualityModel()
    q_path = model_dir / "decision_quality_model.pkl"
    if q_path.exists():
        try:
            q_model.load(q_path)
            load_info["q_loaded"] = True
        except Exception as e:
            msg = f"DecisionQualityModel load failed ({e}), using untrained fallback"
            warnings.warn(msg, stacklevel=2)
            load_info["fallback_used"] = True
            if load_info["fallback_reason"]:
                load_info["fallback_reason"] += "; "
            load_info["fallback_reason"] += f"q_model: {type(e).__name__}"
            if raise_on_missing:
                raise RuntimeError(msg) from e
    else:
        msg = f"DecisionQualityModel not found at {q_path}, using untrained fallback"
        warnings.warn(msg, stacklevel=2)
        load_info["fallback_used"] = True
        load_info["fallback_reason"] += "q_model: file missing"
        if raise_on_missing:
            raise FileNotFoundError(msg)

    if return_info:
        return w_model, q_model, load_info
    return w_model, q_model
