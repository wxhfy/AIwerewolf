"""Phase 7+8: SpeechScore + CounterfactualImpact computation.

SpeechScore (§2.7):
  Uses speech_acts from replay_bundle to compute:
  - groundedness (0-25): based on real public events
  - stance_clarity (0-20): clear accusation/defense/call-to-vote
  - consistency (0-20): speech-vote alignment
  - strategic_value (0-20): advances camp objective
  - information_safety (0-15): no leaks of private info

CounterfactualImpact (§2.9):
  vote_flip exact: what if one vote changed?
  skill_swap local: what if witch/guard/hunter acted differently?

Run: python scripts/compute_speech_and_counterfactual.py
"""

from __future__ import annotations

import ast, json, statistics, sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.db.database import SessionLocal, init_db
from backend.db.models import PublishedReview
from sqlalchemy import text


def load_replay_bundles() -> list[dict]:
    """Load replay bundles for all clean games."""
    init_db()
    db = SessionLocal()
    clean_ids = set(json.loads(Path("/tmp/clean_llm_game_ids.json").read_text()))
    bundles = []
    for review in db.query(PublishedReview).filter(
        PublishedReview.game_id.in_(clean_ids),
        PublishedReview.publish_allowed == True,
        PublishedReview.replay_bundle != None,
    ).all():
        bundles.append(review.replay_bundle)
    db.close()
    return bundles


def parse_field(val: Any) -> Any:
    if not isinstance(val, str):
        return val
    val = val.strip()
    if not val:
        return {}
    try:
        return json.loads(val)
    except (json.JSONDecodeError, ValueError):
        pass
    try:
        return ast.literal_eval(val)
    except (ValueError, SyntaxError):
        pass
    return val


# ---- SpeechScore ----

def compute_speech_scores(bundles: list[dict]) -> list[dict]:
    """Compute SpeechScore components from replay bundle speech_acts and events."""
    all_scores = []

    for bundle in bundles:
        game_id = bundle["game_id"]
        players = bundle.get("players", [])
        events = bundle.get("events", [])
        decisions = bundle.get("decisions", [])
        votes = bundle.get("votes", [])

        player_names = {p["id"]: p.get("name", p["id"]) for p in players}
        player_roles = {p["id"]: p.get("role", "") for p in players}

        # Build vote history per player
        player_votes: dict[str, list[dict]] = defaultdict(list)
        for v in votes:
            voter = v.get("voter_id", "")
            if voter:
                player_votes[voter].append(v)

        # Build public event timeline
        public_events_by_day: dict[int, list[dict]] = defaultdict(list)
        for e in events:
            day = int(e.get("day", 0))
            if e.get("event_type") in ("CHAT_MESSAGE", "VOTE_CAST", "PLAYER_DIED", "BADGE_AWARDED"):
                public_events_by_day[day].append(e)

        # Score each speech decision
        for dec in decisions:
            role = dec.get("role", "")
            player_id = dec.get("player_id", "")
            phase = dec.get("phase", "")
            day = int(dec.get("day", 0))

            if "SPEECH" not in phase:
                continue

            sa = parse_field(dec.get("selected_action", "{}"))
            if not isinstance(sa, dict):
                continue

            speech_text = str(sa.get("speech") or sa.get("text") or "")
            if not speech_text or len(speech_text) < 5:
                continue

            # ---- groundedness: references to real public events ----
            groundedness = 10  # base
            day_events = public_events_by_day.get(day, [])
            for e in day_events:
                pub_text = str(e.get("public_text", "") or "")
                # Check if speech references the event content
                ref_names = []
                for p in players:
                    name = p.get("name", "")
                    if name and name in speech_text:
                        ref_names.append(name)
                # Bonus for referencing real events
                if ref_names:
                    groundedness = min(25, groundedness + len(ref_names) * 3)
                if pub_text and any(word in speech_text for word in pub_text.split()[:10] if len(word) > 2):
                    groundedness = min(25, groundedness + 5)

            # ---- stance_clarity: clear accusation/defense ----
            stance_clarity = 5  # base
            accusatory = any(kw in speech_text for kw in ["狼", "踩", "投", "出", "查杀", "怀疑", "可疑"])
            defensive = any(kw in speech_text for kw in ["好人", "平民", "保", "认好"])
            vote_guidance = any(kw in speech_text for kw in ["归票", "跟我投", "建议投", "必须出"])
            if vote_guidance:
                stance_clarity = 18
            elif accusatory:
                stance_clarity = 14
            elif defensive:
                stance_clarity = 10

            # ---- consistency: speech matches later vote ----
            consistency = 10  # base
            my_votes = player_votes.get(player_id, [])
            my_votes_same_day = [v for v in my_votes if v.get("day") == day]
            if my_votes_same_day:
                voted_target = my_votes_same_day[-1].get("target_id", "")
                if voted_target and voted_target in speech_text:
                    consistency = 18  # Spoke about the player they voted for
                else:
                    consistency = 8  # Speech didn't match vote
            else:
                consistency = 12  # No vote to compare

            # ---- strategic_value: advances camp objective ----
            strategic_value = 8  # base
            if role == "Werewolf":
                if any(kw in speech_text for kw in ["好人", "平民", "认好", "保", "信", "跟"]):
                    strategic_value = 15  # Deflects suspicion
            else:
                if accusatory or vote_guidance:
                    strategic_value = 14  # Advances wolf-hunting
                if any(kw in speech_text for kw in ["查验", "金水", "银水", "解药", "守护"]):
                    strategic_value = min(20, strategic_value + 3)

            # ---- information_safety: no private info leaks ----
            info_safety = 15  # Start perfect
            leak_keywords = ["我被刀了", "我查了", "我毒了", "我守了", "我是女巫", "我是预言家", "我是守卫", "我是猎人",
                            "昨晚", "刀口", "银水", "解药", "毒药"]
            for kw in leak_keywords:
                if kw in speech_text:
                    if role in ["Witch", "Guard", "Hunter", "Seer"] and ("我是" + {"Seer": "预言家", "Witch": "女巫", "Guard": "守卫", "Hunter": "猎人"}.get(role, "")) in speech_text:
                        pass  # Explicit claim of own role is strategic, not a leak
                    elif kw == "昨晚" and role in ["Seer", "Witch", "Guard"]:
                        info_safety = max(0, info_safety - 8)  # Referencing night info
                    else:
                        info_safety = max(0, info_safety - 3)

            speech_quality = groundedness + stance_clarity + consistency + strategic_value + info_safety

            all_scores.append({
                "game_id": game_id,
                "player_id": player_id,
                "role": role,
                "day": day,
                "phase": phase,
                "groundedness": min(25, max(0, groundedness)),
                "stance_clarity": min(20, max(0, stance_clarity)),
                "consistency": min(20, max(0, consistency)),
                "strategic_value": min(20, max(0, strategic_value)),
                "information_safety": min(15, max(0, info_safety)),
                "speech_quality": min(100, max(0, speech_quality)),
                "speech_text_preview": speech_text[:100],
            })

    return all_scores


# ---- CounterfactualImpact ----

def compute_counterfactual_impact(bundles: list[dict]) -> list[dict]:
    """Compute vote_flip and skill_swap counterfactual impacts."""
    impacts = []

    for bundle in bundles:
        game_id = bundle["game_id"]
        players = bundle.get("players", [])
        events = bundle.get("events", [])
        votes = bundle.get("votes", [])
        deaths = bundle.get("deaths", [])
        decisions = bundle.get("decisions", [])

        player_roles = {p["id"]: p.get("role", "") for p in players}
        player_alignments = {p["id"]: p.get("alignment", "") for p in players}

        # ---- Vote flip counterfactuals ----
        # For each vote event, simulate what if the vote went the other way
        vote_events = [e for e in events if e.get("event_type") == "VOTE_CAST"]
        vote_groups: dict[tuple, list[dict]] = defaultdict(list)
        for ve in vote_events:
            day = int(ve.get("day", 0))
            target = ve.get("target_id", "")
            vote_groups[(day, target)].append(ve)

        for ve in vote_events[-20:]:  # Sample for MVP
            day = int(ve.get("day", 0))
            voter_id = ve.get("actor_id", "")
            original_target = ve.get("target_id", "")
            voter_role = player_roles.get(voter_id, "")

            # Find alternative target (different player)
            alt_targets = [t for (d, t) in vote_groups if d == day and t != original_target]
            if not alt_targets:
                continue

            alt_target = alt_targets[0]
            alt_role = player_roles.get(alt_target, "")
            alt_alignment = player_alignments.get(alt_target, "")

            # Impact: if vote flipped to a wolf target → positive impact
            orig_target_alignment = player_alignments.get(original_target, "")
            impact_value = 0.0
            if alt_alignment == "wolf" and orig_target_alignment == "village":
                impact_value = 0.5  # Good flip
            elif alt_alignment == "village" and orig_target_alignment == "wolf":
                impact_value = -0.5  # Bad flip

            impacts.append({
                "game_id": game_id,
                "type": "vote_flip",
                "player_id": voter_id,
                "role": voter_role,
                "day": day,
                "original_target": original_target,
                "alternative_target": alt_target,
                "original_alignment": orig_target_alignment,
                "alternative_alignment": alt_alignment,
                "impact_value": impact_value,
                "confidence": 0.6,
            })

        # ---- Skill swap counterfactuals ----
        # Witch poison: what if they poisoned a different target?
        for dec in decisions:
            role = dec.get("role", "")
            phase = dec.get("phase", "")
            if not (role == "Witch" and "WITCH" in phase):
                continue

            sa = parse_field(dec.get("selected_action", "{}"))
            if not isinstance(sa, dict):
                continue
            action_type = str(sa.get("type") or sa.get("action_type") or "")

            if action_type in ("witch_poison", "witch_save"):
                player_id = dec.get("player_id", "")
                day = int(dec.get("day", 0))
                target = sa.get("target") or sa.get("target_id", "")

                # Find alternative target
                alive_others = [p for p in players if p["id"] != target and p.get("alive")]
                if not alive_others:
                    continue
                alt = alive_others[0]
                alt_alignment = alt.get("alignment", "")

                orig_target_alignment = ""
                for p in players:
                    if p["id"] == target:
                        orig_target_alignment = p.get("alignment", "")
                        break

                impact_value = 0.0
                if action_type == "witch_poison":
                    if alt_alignment == "wolf" and orig_target_alignment == "village":
                        impact_value = 0.6  # Should have poisoned wolf instead
                    elif alt_alignment == "village" and orig_target_alignment == "wolf":
                        impact_value = -0.6  # Actually poisoned wolf, good

                impacts.append({
                    "game_id": game_id,
                    "type": "skill_swap",
                    "subtype": f"witch_{action_type}",
                    "player_id": player_id,
                    "role": role,
                    "day": day,
                    "original_target": target,
                    "alternative_target": alt["id"],
                    "original_alignment": orig_target_alignment,
                    "alternative_alignment": alt_alignment,
                    "impact_value": impact_value,
                    "confidence": 0.5,
                })

    return impacts


def main() -> int:
    print("Loading replay bundles...")
    bundles = load_replay_bundles()
    print(f"  {len(bundles)} bundles loaded")

    # SpeechScore
    print("\n=== Computing SpeechScore ===")
    speech_scores = compute_speech_scores(bundles)
    print(f"  {len(speech_scores)} speech acts scored")

    # Per-player speech aggregation
    player_speech: dict[str, list[dict]] = defaultdict(list)
    for ss in speech_scores:
        player_speech[ss["player_id"]].append(ss)

    player_speech_agg = {}
    for pid, scores in player_speech.items():
        role = scores[0]["role"]
        avg_quality = statistics.mean(s["speech_quality"] for s in scores)
        avg_groundedness = statistics.mean(s["groundedness"] for s in scores)
        avg_stance = statistics.mean(s["stance_clarity"] for s in scores)
        avg_consistency = statistics.mean(s["consistency"] for s in scores)
        avg_strategic = statistics.mean(s["strategic_value"] for s in scores)
        avg_safety = statistics.mean(s["information_safety"] for s in scores)
        player_speech_agg[pid] = {
            "player_id": pid, "role": role, "n_speeches": len(scores),
            "avg_speech_quality": round(avg_quality, 1),
            "avg_groundedness": round(avg_groundedness, 1),
            "avg_stance_clarity": round(avg_stance, 1),
            "avg_consistency": round(avg_consistency, 1),
            "avg_strategic_value": round(avg_strategic, 1),
            "avg_information_safety": round(avg_safety, 1),
        }

    # CounterfactualImpact
    print("\n=== Computing CounterfactualImpact ===")
    impacts = compute_counterfactual_impact(bundles)
    print(f"  {len(impacts)} counterfactuals computed")

    # Aggregate
    vote_flip_count = sum(1 for i in impacts if i["type"] == "vote_flip")
    skill_swap_count = sum(1 for i in impacts if i["type"] == "skill_swap")
    avg_impact = statistics.mean(abs(i["impact_value"]) for i in impacts) if impacts else 0

    player_impact: dict[str, float] = defaultdict(float)
    for imp in impacts:
        player_impact[imp["player_id"]] += imp["impact_value"]

    # ---- Generate reports ----

    # SpeechScore report
    lines = [
        "# SpeechScore Report",
        "",
        f"**Total speech acts scored**: {len(speech_scores)}",
        f"**Players with speeches**: {len(player_speech)}",
        "",
        "## Component Averages",
        "| Component | Mean | Description |",
        "|-----------|------|-------------|",
    ]
    for comp, desc in [("avg_groundedness", "Based on real public events"),
                        ("avg_stance_clarity", "Clear accusation/defense/vote guidance"),
                        ("avg_consistency", "Speech matches later vote"),
                        ("avg_strategic_value", "Advances camp objective"),
                        ("avg_information_safety", "No private info leaks")]:
        vals = [p[comp] for p in player_speech_agg.values()]
        lines.append(f"| {desc} | {statistics.mean(vals):.1f} | {comp} |")

    lines += [
        "",
        "## Per-Role Speech Quality",
        "| Role | Players | Avg Quality | Avg Grounded | Avg Stance | Avg Consistency |",
        "|------|---------|-------------|-------------|------------|-----------------|",
    ]
    role_speech = defaultdict(list)
    for ps in player_speech_agg.values():
        role_speech[ps["role"]].append(ps)
    for role in ["Seer", "Witch", "Guard", "Hunter", "Werewolf", "Villager"]:
        items = role_speech.get(role, [])
        if items:
            lines.append(f"| {role} | {len(items)} | "
                        f"{statistics.mean(i['avg_speech_quality'] for i in items):.1f} | "
                        f"{statistics.mean(i['avg_groundedness'] for i in items):.1f} | "
                        f"{statistics.mean(i['avg_stance_clarity'] for i in items):.1f} | "
                        f"{statistics.mean(i['avg_consistency'] for i in items):.1f} |")

    lines += [
        "",
        "## Note",
        "- SpeechScore MVP uses rule-based heuristics, not deep learning",
        "- groundedness/stance/consistency/strategic_value/information_safety each 0-25/20/20/20/15",
        "- Total speech_quality range: 0-100",
    ]
    (ROOT / "data/health/speech_score_report.md").write_text("\n".join(lines))
    print(f"  → speech_score_report.md")

    # CounterfactualImpact report
    lines = [
        "# CounterfactualImpact Report",
        "",
        f"**Total counterfactuals**: {len(impacts)}",
        f"  - Vote flip: {vote_flip_count}",
        f"  - Skill swap: {skill_swap_count}",
        f"**Mean absolute impact**: {avg_impact:.3f}",
        "",
        "## Top Impact Players",
        "| Player ID | Role | Total Impact | N Counterfactuals |",
        "|-----------|------|-------------|-------------------|",
    ]
    sorted_impacts = sorted(player_impact.items(), key=lambda x: abs(x[1]), reverse=True)[:10]
    for pid, total in sorted_impacts:
        n = sum(1 for i in impacts if i["player_id"] == pid)
        role = "?"
        for p in player_speech_agg.values():
            if p["player_id"] == pid:
                role = p["role"]
                break
        lines.append(f"| {pid[:12]} | {role} | {total:+.3f} | {n} |")

    lines += [
        "",
        "## Methodology",
        "- vote_flip: what if one player voted differently? Impact = alignment change value",
        "- skill_swap: what if witch poisoned/saved a different target?",
        "- Impact values in [-1, 1] range, where + = improvement over actual",
        "- Confidence is low (0.5-0.6) for MVP; needs better causal modeling",
    ]
    (ROOT / "data/health/counterfactual_impact_report.md").write_text("\n".join(lines))
    print(f"  → counterfactual_impact_report.md")

    # Save data
    with open(ROOT / "data/health/speech_scores.json", "w", encoding="utf-8") as f:
        json.dump(list(player_speech_agg.values()), f, ensure_ascii=False, indent=2)
    print(f"  → speech_scores.json")

    with open(ROOT / "data/health/counterfactual_impacts.json", "w", encoding="utf-8") as f:
        json.dump(impacts, f, ensure_ascii=False, indent=2)
    print(f"  → counterfactual_impacts.json")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
