"""Base action features — role, action type, game context, target, outcome."""

from __future__ import annotations

from typing import Any

from backend.eval.features.registry import FeatureExtractor


class BaseActionFeatures:
    """Extract base structural features: role, action type, game context, target, outcome."""

    name = "base_action"
    version = "v1"

    def supports(self, opportunity: dict[str, Any]) -> bool:
        return True

    def extract(self, opportunity: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, float | int | str]:
        role = opportunity.get("role", "")
        op_type = opportunity.get("opportunity_type", "")
        game_feat = opportunity.get("game_features", {}) or {}
        target_feat = opportunity.get("target_features", {}) or {}
        outcome_feat = opportunity.get("outcome_features", {}) or {}
        chosen = opportunity.get("chosen_action", {}) or {}

        feats: dict[str, float | int | str] = {}

        # Role one-hot
        for r in ["Seer", "Witch", "Guard", "Hunter", "Werewolf", "Villager"]:
            feats[f"role_{r.lower()}"] = 1 if role == r else 0

        # Opportunity type one-hot
        for ot in ["seer_check", "witch_save", "witch_poison", "guard_protect",
                    "hunter_shot", "werewolf_kill", "vote", "speech"]:
            feats[f"op_{ot}"] = 1 if op_type == ot else 0

        # Game context
        feats["day"] = float(opportunity.get("day", 1))
        feats["alive_count"] = float(game_feat.get("alive_count", 6))
        feats["is_endgame"] = 1 if game_feat.get("is_endgame") else 0
        cb = game_feat.get("camp_balance", {})
        feats["village_alive"] = float(cb.get("village_alive", 3))
        feats["wolf_alive"] = float(cb.get("wolf_alive", 2))
        feats["camp_balance_ratio"] = round(feats["village_alive"] / max(feats["wolf_alive"], 1), 4)

        # Target features
        if target_feat:
            align = target_feat.get("target_alignment", "")
            feats["target_is_village"] = 1 if align == "village" else 0
            feats["target_is_wolf"] = 1 if align == "wolf" else 0
            feats["target_alive"] = 1 if target_feat.get("target_alive") else 0
            feats["target_is_exposed"] = 1 if target_feat.get("target_is_exposed") else 0
        else:
            for k in ["target_is_village", "target_is_wolf", "target_alive", "target_is_exposed"]:
                feats[k] = -1

        # Outcome features
        if outcome_feat:
            feats["target_died"] = 1 if outcome_feat.get("target_died_same_phase") else 0
            reason = outcome_feat.get("target_died_reason", "") or ""
            for r in ["hunter", "vote", "wolf", "witch"]:
                feats[f"target_died_{r}"] = 1 if r in reason else 0
        else:
            feats["target_died"] = -1

        # Action metadata
        meta = chosen.get("metadata", {}) if isinstance(chosen, dict) else {}
        feats["action_is_llm"] = 1 if meta.get("source") == "llm" else 0
        feats["action_is_fallback"] = 1 if meta.get("fallback") else 0
        feats["action_parse_success"] = 0 if meta.get("fallback") else 1
        feats["action_target_id"] = str(chosen.get("target_id", "") or "")

        return feats
