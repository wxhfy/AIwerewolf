"""Vote quality features — role-aware, evidence-grounded, coordination-aware.

Each feature is continuous [0,1] or binary. No player_id shortcuts.
Only uses PreAction-available information (public context, private context, target features).
"""

from __future__ import annotations

import json
import re
from typing import Any


class VoteQualityFeatures:
    name = "vote_quality"
    version = "v1"

    def supports(self, opportunity: dict[str, Any]) -> bool:
        return opportunity.get("opportunity_type") == "vote"

    def extract(
        self, opportunity: dict[str, Any], context: dict[str, Any] | None = None
    ) -> dict[str, float | int | str]:
        role = opportunity.get("role", "")
        target_feat = opportunity.get("target_features", {}) or {}
        game_feat = opportunity.get("game_features", {}) or {}
        chosen = opportunity.get("chosen_action", {}) or {}
        target_id = str(chosen.get("target_id", "") or "")
        target_role = target_feat.get("target_role", "")
        target_align = target_feat.get("target_alignment", "")
        public_ctx = str(opportunity.get("public_context_summary", "") or "")
        private_ctx_raw = opportunity.get("private_context_summary", "") or ""
        player_id = opportunity.get("player_id", "")

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

        # Parse known wolves from private context
        known_wolf_ids: set[str] = set()
        for match in re.finditer(r"P\d+", private_ctx):
            wid = match.group(0).strip().upper()
            ctx_around = private_ctx[max(0, match.start() - 20) : min(len(private_ctx), match.end() + 30)]
            if any(kw in ctx_around for kw in ["狼", "wolf", "查杀", "队友"]):
                known_wolf_ids.add(wid)
        if role in ("Werewolf", "WhiteWolfKing"):
            if any(kw in private_ctx for kw in ["我是狼", "我是狼人", "狼人身份", "狼队友"]):
                if player_id:
                    known_wolf_ids.add(player_id)

        is_wolf = role in ("Werewolf", "WhiteWolfKing")
        is_village = role not in ("Werewolf", "WhiteWolfKing") and role != "Unknown"
        feats: dict[str, float | int | str] = {}

        # 1. vote_target_alignment_score: how well target alignment matches role goal
        if is_wolf:
            if target_align == "village":
                feats["vote_target_alignment_score"] = 0.9
            elif target_align == "wolf":
                feats["vote_target_alignment_score"] = 0.1
            else:
                feats["vote_target_alignment_score"] = 0.5
        else:  # village team
            if target_align == "wolf":
                feats["vote_target_alignment_score"] = 0.95
            elif target_align == "village":
                feats["vote_target_alignment_score"] = 0.05
            else:
                feats["vote_target_alignment_score"] = 0.5

        # 2. vote_target_role_value: how valuable is this target to eliminate
        role_value = {
            "Seer": 0.95,
            "Witch": 0.90,
            "Guard": 0.80,
            "Hunter": 0.70,
            "Villager": 0.30,
            "Werewolf": 0.10,
            "WhiteWolfKing": 0.10,
        }
        tv = role_value.get(target_role, 0.40)
        if target_feat.get("target_is_exposed") and target_align == "village":
            tv = min(1.0, tv + 0.10)
        feats["vote_target_role_value"] = round(tv, 4)

        # 3. vote_matches_public_evidence: Seer check, public claims
        public_evidence_match = 0.5
        # Check if public context mentions seer check on this target
        if target_id and target_id in public_ctx:
            if any(kw in public_ctx for kw in ["查杀", "查验", "狼人", "预言家"]):
                # Target is publicly implicated
                if is_village and target_align == "wolf" or is_wolf and target_align == "village":
                    public_evidence_match = 0.85
        # Check if public context mentions wolf check that this voter is ignoring
        seer_check_match = re.search(r"(?:查验|查杀)\s*(P\d+)\s*(?:是|为)?\s*(?:狼|wolf)", public_ctx)
        if seer_check_match:
            checked_wolf = seer_check_match.group(1)
            if checked_wolf != target_id and is_village:
                public_evidence_match = 0.2  # Voting elsewhere when seer gave wolf check
            elif checked_wolf == target_id:
                public_evidence_match = 0.9
        feats["vote_matches_public_evidence"] = round(public_evidence_match, 4)

        # 4. vote_matches_private_info: Seer known wolf check
        private_info_match = 0.5
        if known_wolf_ids and is_village:
            if target_id in known_wolf_ids:
                private_info_match = 0.95  # Voting known wolf — correct
            elif target_align == "village" and any(wid not in public_ctx for wid in known_wolf_ids):
                private_info_match = 0.15  # Ignoring known wolf info
        feats["vote_matches_private_info"] = round(private_info_match, 4)

        # 5. vote_team_coordination_score: wolf pack voting together
        coordination = 0.5
        if is_wolf:
            # Good coordination: voting for high-value village target
            if target_align == "village":
                if tv >= 0.70:  # Power role target
                    coordination = 0.85
                else:
                    coordination = 0.60
            # Bad: cross-voting own teammate
            if target_id in known_wolf_ids:
                key_exposed = game_feat.get("key_roles_exposed", [])
                if "预言家" in str(key_exposed) or "Seer" in str(key_exposed):
                    coordination = 0.80  # Strategic sacrifice under pressure
                else:
                    coordination = 0.15  # Unnecessary cross-vote
        feats["vote_team_coordination_score"] = round(coordination, 4)

        # 6. vote_wagon_power: whether this vote joins an effective wagon
        wagon_power = 0.3
        # Count how many votes for this target in public context
        target_votes = public_ctx.count(f"-> {target_id}")
        if target_votes >= 4:
            wagon_power = 0.9  # Strong wagon
        elif target_votes >= 2:
            wagon_power = 0.6
        elif target_votes >= 1:
            wagon_power = 0.4
        feats["vote_wagon_power"] = round(wagon_power, 4)

        # 7. vote_wastes_vote: low-value, no-impact, no-evidence vote
        wastes = 0.0
        if tv < 0.40 and wagon_power < 0.4 and public_evidence_match < 0.5:
            wastes = 0.7
        elif wagon_power < 0.3:
            wastes = 0.4
        feats["vote_wastes_vote"] = round(wastes, 4)

        # 8. vote_buses_teammate_reasonably: cutting doomed teammate is smart
        buses = 0.0
        if is_wolf and target_id in known_wolf_ids:
            key_exposed = game_feat.get("key_roles_exposed", [])
            if "预言家" in str(key_exposed) or "Seer" in str(key_exposed):
                buses = 0.80  # Smart bus under seer pressure
            else:
                buses = 0.10  # Unnecessary bus
        feats["vote_buses_teammate_reasonably"] = round(buses, 4)

        # 9. vote_is_stance_consistent: matches prior speech
        stance_consistent = 0.5
        # Check if this player had a prior speech that mentioned the target
        speech_texts = re.findall(rf"{player_id}[^]]*?(?:speech|发言)", public_ctx)
        if target_id and target_id in public_ctx:
            # Simple heuristic: if target_id appears in nearby context of voter's speeches
            stance_consistent = 0.6
        feats["vote_is_stance_consistent"] = round(stance_consistent, 4)

        # 10. vote_coordination_failure (refined)
        vcf = 0.0
        if is_wolf and known_wolf_ids:
            if target_id not in known_wolf_ids and target_align == "village":
                if tv < 0.50:
                    vcf = 0.6  # Voting low-value target when teammate needs help
                elif tv >= 0.70:
                    vcf = 0.1  # Good target choice
            elif target_id in known_wolf_ids:
                # Voting teammate — check if strategic
                if feats.get("vote_buses_teammate_reasonably", 0) > 0.5:
                    vcf = 0.1  # Strategic sacrifice
                else:
                    vcf = 0.8  # Unnecessary cross-vote
        feats["vote_coordination_failure"] = round(vcf, 4)

        # 11. vote_target_pressure_score: public pressure on target
        pressure = 0.3
        if target_id and target_id in public_ctx:
            target_mentions = public_ctx.count(target_id)
            suspicious = any(kw in public_ctx for kw in ["查杀", "狼", "可疑", "出"])
            pressure = min(1.0, 0.3 + 0.1 * target_mentions + (0.3 if suspicious else 0))
        feats["vote_target_pressure_score"] = round(pressure, 4)

        # 12. vote_target_public_claimed_role: whether target publicly claimed power role
        claimed_role = 0.0
        if target_role in ("Seer", "Witch", "Guard", "Hunter"):
            claimed_role = 0.5
            if target_id and target_id in public_ctx:
                if any(
                    kw in public_ctx for kw in [f"我是{target_role}", "我是预言家", "我是女巫", "我是守卫", "我是猎人"]
                ):
                    claimed_role = 0.9
        feats["vote_target_public_claimed_role"] = round(claimed_role, 4)

        # 13. vote_public_checked_wolf_target: target is publicly checked wolf
        pub_checked_wolf = 0
        if target_id and target_id in public_ctx:
            if re.search(rf"{target_id}.*?(?:查杀|查验.*?狼|是狼)", public_ctx):
                pub_checked_wolf = 1
        feats["vote_public_checked_wolf_target"] = pub_checked_wolf

        # 14. vote_away_from_public_checked_wolf: public wolf exists but vote elsewhere
        away_from_pub_wolf = 0
        pub_wolf_match = re.search(r"(?:查杀|查验)\s*(P\d+)\s*(?:是|为)?\s*(?:狼|wolf)", public_ctx)
        if pub_wolf_match and is_village:
            pub_wolf = pub_wolf_match.group(1)
            if target_id != pub_wolf:
                away_from_pub_wolf = 1
        feats["vote_away_from_public_checked_wolf"] = away_from_pub_wolf

        # 15. vote_private_known_wolf_target: target is privately known wolf
        priv_known_wolf = 1 if (target_id and target_id in known_wolf_ids) else 0
        feats["vote_private_known_wolf_target"] = priv_known_wolf

        # 16. vote_away_from_private_known_wolf: knows wolf but votes elsewhere
        away_from_priv = 0
        if is_village and known_wolf_ids and target_id not in known_wolf_ids:
            away_from_priv = 1
        feats["vote_away_from_private_known_wolf"] = away_from_priv

        # 17. vote_prior_speech_target_match: prior speech mentioned this target
        speech_match = 0
        if target_id and player_id and player_id in public_ctx:
            # Check if in public context this voter mentioned the target before voting
            voter_speeches = public_ctx.split(f"{player_id}")[1:] if player_id in public_ctx else []
            for seg in voter_speeches[:2]:
                if target_id in seg and any(kw in seg for kw in ["出", "投", "嫌疑", "狼", "可疑"]):
                    speech_match = 1
                    break
        feats["vote_prior_speech_target_match"] = speech_match

        # 18. vote_prior_speech_target_conflict: vote contradicts speech stance
        speech_conflict = 0
        if (
            player_id and target_id and target_id not in public_ctx.split(player_id)[-1][:200]
            if player_id in public_ctx
            else False
        ):
            pass  # Will be set below
        if player_id and target_id and is_wolf:
            # Wolf who spoke about saving X but votes Y = conflict
            for wid in known_wolf_ids:
                if wid != player_id and wid in public_ctx and target_id != wid:
                    if any(kw in public_ctx for kw in [f"保{wid}", f"{wid}是好", f"{wid}一定好"]):
                        speech_conflict = 1
                        break
        feats["vote_prior_speech_target_conflict"] = speech_conflict

        # 19. vote_strategic_bus_score: cutting doomed teammate is smart
        strategic_bus = 0.0
        if is_wolf and target_id in known_wolf_ids:
            if pressure >= 0.6 or pub_checked_wolf:
                strategic_bus = 0.8  # Smart cut under heavy pressure
            else:
                strategic_bus = 0.2
        feats["vote_strategic_bus_score"] = round(strategic_bus, 4)

        # 20. vote_bad_save_teammate_score: trying to save exposed teammate
        bad_save = 0.0
        if is_wolf and known_wolf_ids and target_id not in known_wolf_ids:
            for wid in known_wolf_ids:
                if wid != player_id and wid in public_ctx:
                    wid_pressure = public_ctx.count(wid)
                    if wid_pressure >= 3:
                        bad_save = min(1.0, 0.5 + 0.1 * wid_pressure)
                        break
        feats["vote_bad_save_teammate_score"] = round(bad_save, 4)

        # 21. vote_feature_confidence
        confidence = 1.0
        if not target_id:
            confidence = 0.3
        elif not public_ctx:
            confidence = 0.4
        elif len(known_wolf_ids) == 0 and is_wolf:
            confidence = 0.6  # Wolf without teammate info
        feats["vote_feature_confidence"] = round(confidence, 4)

        return feats
