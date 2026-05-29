"""Kill target value features — role-aware, counterfactual-aware.

Evaluates werewolf_kill target quality based on role value, public exposure,
narrative consistency, and counterfactual alternatives.
No player_id shortcuts. PreAction-safe.
"""

from __future__ import annotations

import json, re
from typing import Any


class KillTargetValueFeatures:
    name = "kill_target_value"
    version = "v1"

    def supports(self, opportunity: dict[str, Any]) -> bool:
        return opportunity.get("opportunity_type") in (
            "werewolf_kill", "attack", "night_kill",
        )

    def extract(self, opportunity: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, float | int | str]:
        target_feat = opportunity.get("target_features", {}) or {}
        game_feat = opportunity.get("game_features", {}) or {}
        chosen = opportunity.get("chosen_action", {}) or {}
        target_id = str(chosen.get("target_id", "") or "")
        target_role = target_feat.get("target_role", "")
        target_align = target_feat.get("target_alignment", "")
        public_ctx = str(opportunity.get("public_context_summary", "") or "")
        private_ctx_raw = opportunity.get("private_context_summary", "") or ""

        # Parse private context
        private_ctx = ""
        if isinstance(private_ctx_raw, dict):
            private_ctx = json.dumps(private_ctx_raw, ensure_ascii=False)
        elif isinstance(private_ctx_raw, str) and private_ctx_raw.startswith("{"):
            try:
                parsed = json.loads(private_ctx_raw)
                if isinstance(parsed, dict):
                    private_ctx = " ".join(str(v) for v in parsed.values())
                else:
                    private_ctx = private_ctx_raw
            except (json.JSONDecodeError, TypeError):
                private_ctx = private_ctx_raw
        else:
            private_ctx = str(private_ctx_raw)

        feats: dict[str, float | int | str] = {}

        # 1. kill_target_role_value: base value by role
        role_value = {"Seer": 0.95, "Witch": 0.90, "Guard": 0.80,
                       "Hunter": 0.70, "Villager": 0.25,
                       "Werewolf": 0.05, "WhiteWolfKing": 0.05}
        tv = role_value.get(target_role, 0.35)
        feats["kill_target_role_value"] = round(tv, 4)

        # 2. kill_target_public_claim_strength: has target publicly claimed a role?
        claim_strength = 0.0
        if target_id and target_id in public_ctx:
            if any(f"{target_id}.*?预言家" in public_ctx for _ in [1]):
                pass
            claim_kw = ["我是预言家", "我是女巫", "我是守卫", "我是猎人", "查验", "查杀",
                        "预言家", "女巫", "守卫", "猎人"]
            matches = sum(1 for kw in claim_kw if kw in public_ctx and target_id in public_ctx)
            claim_strength = min(1.0, 0.3 + 0.2 * matches)
        feats["kill_target_public_claim_strength"] = round(claim_strength, 4)

        # 3. kill_target_public_influence: target's public impact
        influence = 0.3
        if target_id:
            mentions = public_ctx.count(target_id)
            influence = min(1.0, 0.3 + 0.05 * mentions)
        feats["kill_target_public_influence"] = round(influence, 4)

        # 4. kill_removes_confirmed_info: killing confirmed info source
        removes_info = 0.0
        if target_role in ("Seer", "Witch"):
            removes_info = 0.7
        elif target_claim_strength > 0.5:
            removes_info = 0.5
        feats["kill_removes_confirmed_info"] = round(removes_info, 4)

        # 5. kill_is_high_value: composite
        high_value = 1.0 if (
            tv >= 0.70 and target_align == "village"
        ) else 0.2 if tv <= 0.30 else 0.5
        feats["kill_is_high_value"] = round(high_value, 4)

        # 6. kill_counterfactual_best_target_value: best available target value
        best_value = 0.30
        key_exposed = game_feat.get("key_roles_exposed", [])
        if "预言家" in str(key_exposed) or "Seer" in str(key_exposed):
            best_value = max(best_value, 0.95)
        if "女巫" in str(key_exposed) or "Witch" in str(key_exposed):
            best_value = max(best_value, 0.90)
        if "守卫" in str(key_exposed) or "Guard" in str(key_exposed):
            best_value = max(best_value, 0.80)
        if "猎人" in str(key_exposed) or "Hunter" in str(key_exposed):
            best_value = max(best_value, 0.70)
        feats["kill_counterfactual_best_value"] = round(best_value, 4)

        # 7. kill_target_value_gap: best - current
        gap = max(0.0, best_value - tv)
        feats["kill_target_value_gap"] = round(gap, 4)

        # 8. kill_low_value_target: flag for clearly suboptimal kills
        low_value = 1 if (tv <= 0.30 and gap >= 0.40) else 0
        feats["kill_low_value_target"] = low_value

        # 9. kill_narrative_consistent: does this kill align with wolf public stance?
        narrative = 0.5
        # Simple proxy: if the target was mentioned in public context by wolves as suspicious
        if target_id and target_id in public_ctx:
            if "狼" not in public_ctx.split(target_id)[0][-30:]:
                narrative = 0.4
            else:
                narrative = 0.6
        feats["kill_narrative_consistent"] = round(narrative, 4)

        # 10. kill_feature_confidence
        confidence = 1.0
        if not target_id:
            confidence = 0.3
        elif not target_role:
            confidence = 0.5
        feats["kill_feature_confidence"] = round(confidence, 4)

        return feats
