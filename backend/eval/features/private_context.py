"""Private-context features — what the agent knew at decision time."""

from __future__ import annotations

import json
import re
from typing import Any


class PrivateContextFeatures:
    name = "private_context"
    version = "v2"

    def supports(self, opportunity: dict[str, Any]) -> bool:
        return True

    def extract(
        self, opportunity: dict[str, Any], context: dict[str, Any] | None = None
    ) -> dict[str, float | int | str]:
        role = opportunity.get("role", "")
        op_type = opportunity.get("opportunity_type", "")
        private_ctx_raw = opportunity.get("private_context_summary", "") or ""
        chosen = opportunity.get("chosen_action", {}) or {}
        speech_text = str(chosen.get("speech", "") or "")
        target_id = str(chosen.get("target_id", "") or "")
        player_id = opportunity.get("player_id", "")
        target_feat = opportunity.get("target_features", {}) or {}
        game_feat = opportunity.get("game_features", {}) or {}

        # Parse JSON private context
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

        # Parse known wolves/goods
        known_wolf_ids: set[str] = set()
        known_good_ids: set[str] = set()

        for match in re.finditer(r"P\d+", private_ctx):
            word = match.group(0).strip().upper()
            start = max(0, match.start() - 20)
            end = min(len(private_ctx), match.end() + 30)
            ctx_around = private_ctx[start:end]
            if any(kw in ctx_around for kw in ["狼", "wolf", "查杀", "队友"]):
                known_wolf_ids.add(word)
            if any(kw in ctx_around for kw in ["金水", "好人", "good"]):
                known_good_ids.add(word)

        if role in ("Werewolf", "WhiteWolfKing"):
            if any(kw in private_ctx for kw in ["我是狼", "我是狼人", "狼人身份", "狼队友"]):
                if player_id:
                    known_wolf_ids.add(player_id)

        feats: dict[str, float | int | str] = {}
        feats["private_has_confirmed_wolf"] = 1 if known_wolf_ids else 0
        feats["private_has_confirmed_good"] = 1 if known_good_ids else 0
        feats["target_is_private_confirmed_wolf"] = 1 if (target_id and target_id in known_wolf_ids) else 0
        feats["target_is_private_confirmed_good"] = 1 if (target_id and target_id in known_good_ids) else 0

        # Seer release detection
        should_release = 0
        was_released = 0
        if role == "Seer" and known_wolf_ids:
            if op_type in ("speech", "seer_release", "vote"):
                should_release = 1
            release_kw = ["查杀", "查了", "验了", "查验", "狼", "wolf"]
            for wid in known_wolf_ids:
                if str(wid) in speech_text and any(kw in speech_text.lower() for kw in release_kw):
                    was_released = 1
                    break
        feats["private_info_should_release"] = should_release
        feats["private_info_was_released"] = was_released
        feats["private_info_withheld"] = 1 if (should_release and not was_released) else 0

        # Seer voted elsewhere despite known wolf
        vedw = 0
        if role == "Seer" and known_wolf_ids and op_type == "vote":
            if target_id and target_id not in known_wolf_ids:
                if target_feat.get("target_alignment") == "village":
                    vedw = 1
        feats["voted_elsewhere_despite_known_wolf"] = vedw

        # Risky private info release
        risky = 0
        if op_type in ("speech", "seer_release"):
            risky_kw = ["被刀", "刀口", "昨晚刀", "解药", "毒药", "女巫", "守了", "守卫身份", "我是守卫", "我是女巫"]
            if any(kw in speech_text for kw in risky_kw) and role in ("Witch", "Guard"):
                risky = 1
        feats["risky_private_info_release"] = risky

        # Guard consecutive
        cg = 0
        day = int(opportunity.get("day", 1))
        if role == "Guard" and op_type == "guard_protect" and day >= 2:
            if target_id and target_id == player_id:
                cg = 1
        feats["consecutive_same_guard_target"] = cg

        # Wolf dynamic features
        is_wolf = role in ("Werewolf", "WhiteWolfKing")
        feats.update(
            self._wolf_features(
                is_wolf, role, op_type, speech_text, target_id, known_wolf_ids, target_feat, game_feat, player_id
            )
        )
        return feats

    def _wolf_features(
        self, is_wolf, role, op_type, speech_text, target_id, known_wolf_ids, target_feat, game_feat, player_id
    ) -> dict:
        feats: dict[str, float | int | str] = {}

        # Wolf perspective leak
        leak = 0.0
        if is_wolf and op_type in ("speech", "seer_release") and speech_text:
            exact = ["我们狼", "我狼", "狼队刀", "是我们刀"]
            for kw in exact:
                if kw in speech_text:
                    leak = max(leak, 0.9)
                    break
            if leak < 0.9:
                leak_kw = ["我们狼", "刀口不是", "昨晚刀", "狼队友", "狼队", "同伴", "夜里"]
                kw_count = sum(1 for kw in leak_kw if kw in speech_text)
                if kw_count >= 1:
                    leak = 0.6 + 0.1 * min(kw_count - 1, 3)
        feats["wolf_perspective_leak_score"] = round(min(1.0, leak), 4)

        # Teammate overprotection
        overprot = 0.0
        if is_wolf and known_wolf_ids and op_type in ("speech", "seer_release", "vote") and speech_text:
            other_wolves = {w for w in known_wolf_ids if w != player_id}
            defending = any(w in speech_text for w in other_wolves)
            light_cut = any(kw in speech_text for kw in ["不强保", "不硬保", "按查杀走", "先出", "不保", "切割"])
            has_evidence = any(
                kw in speech_text.lower() for kw in ["因为", "证据", "查验", "投票记录", "发言记录", "行为", "逻辑"]
            )
            if defending:
                if light_cut:
                    overprot = 0.0
                elif not has_evidence:
                    overprot = 0.7
                    if any(kw in speech_text for kw in ["一定好", "肯定是好", "绝对是好", "铁好人"]):
                        overprot = 0.9
                else:
                    overprot = 0.3
        feats["teammate_overprotection"] = round(min(1.0, overprot), 4)

        # Vote coordination
        vf = 0.0
        if is_wolf and op_type == "vote" and target_id:
            target_is_known = target_id in known_wolf_ids
            if target_is_known:
                key_exposed = game_feat.get("key_roles_exposed", [])
                if "预言家" in str(key_exposed) or "Seer" in str(key_exposed):
                    vf = 0.0  # Smart sacrifice
                else:
                    vf = 0.5
            elif target_feat.get("target_alignment") == "wolf":
                vf = 0.9
            elif target_feat.get("target_alignment") == "village":
                if known_wolf_ids:
                    vf = 0.5
                tr = target_feat.get("target_role", "")
                if tr in ("Seer", "Witch"):
                    vf = max(0.0, vf - 0.3)
                elif tr in ("Guard", "Hunter"):
                    vf = max(0.0, vf - 0.1)
        feats["vote_coordination_failure"] = round(min(1.0, vf), 4)

        # Kill target value
        if op_type == "werewolf_kill" and target_id:
            tv = {"Seer": 0.95, "Witch": 0.90, "Guard": 0.80, "Hunter": 0.70, "Villager": 0.30}.get(
                target_feat.get("target_role", ""), 0.40
            )
            if target_feat.get("target_is_exposed") and target_feat.get("target_alignment") == "village":
                tv = min(1.0, tv + 0.15)
            feats["night_kill_target_value"] = tv
        elif op_type == "werewolf_kill":
            feats["night_kill_target_value"] = 0.3

        # Counterfactual gap
        if op_type == "werewolf_kill":
            cv = feats.get("night_kill_target_value", 0.3)
            bv = 0.3
            ke = game_feat.get("key_roles_exposed", [])
            if "预言家" in str(ke) or "Seer" in str(ke):
                bv = max(bv, 0.95)
            if "女巫" in str(ke) or "Witch" in str(ke):
                bv = max(bv, 0.90)
            if "守卫" in str(ke) or "Guard" in str(ke):
                bv = max(bv, 0.80)
            if not ke:
                bv = max(bv, 0.5)
            feats["counterfactual_target_gap"] = round(max(0.0, bv - cv), 4)
        else:
            feats["night_kill_target_value"] = feats.get("night_kill_target_value", 0.5)
            feats["counterfactual_target_gap"] = feats.get("counterfactual_target_gap", 0.0)

        # Speech grounding
        grounding = 0.5
        if op_type in ("speech", "seer_release") and speech_text:
            refs = [
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
            ]
            rc = sum(1 for r in refs if r in speech_text)
            grounding = 0.3 + 0.07 * min(rc, 10)
            pure = ["一定", "肯定", "就是", "绝对是", "铁", "不用想"]
            if sum(1 for a in pure if a in speech_text) >= 2 and rc < 3:
                grounding = max(0.1, grounding - 0.3)
        feats["speech_grounding_score"] = round(min(1.0, max(0.0, grounding)), 4)

        # Role goal conflict
        gc = 0.0
        if is_wolf:
            if op_type == "speech" and feats.get("wolf_perspective_leak_score", 0) > 0.3:
                gc = 0.7
            if op_type == "vote" and feats.get("vote_coordination_failure", 0) > 0.3:
                gc = max(gc, 0.5)
            if op_type == "werewolf_kill" and feats.get("counterfactual_target_gap", 0) > 0.5:
                gc = max(gc, 0.6)
        if role == "Seer" and feats.get("private_info_withheld", 0):
            gc = 0.8
        if role == "Witch" and op_type == "witch_poison" and feats.get("target_is_village", 0) == 1:
            gc = 0.9
        if role == "Hunter" and op_type == "hunter_shot" and feats.get("target_is_village", 0) == 1:
            gc = 0.9
        feats["role_goal_conflict_score"] = round(min(1.0, gc), 4)

        # Evidence lack
        el = 0.0
        if op_type in ("speech", "seer_release", "vote"):
            gg = max(0.0, 0.5 - feats.get("speech_grounding_score", 0.5))
            if is_wolf and feats.get("teammate_overprotection", 0) > 0.5:
                el = 0.7
            if gg > 0.2:
                el = max(el, 0.4)
            if feats.get("voted_elsewhere_despite_known_wolf", 0):
                el = max(el, 0.8)
        feats["lack_of_public_evidence_support"] = round(min(1.0, el), 4)

        return feats
