"""Phase 1: Extract DecisionOpportunity from game replay_bundle data.

Run: python scripts/extract_opportunities.py [--limit N] [--output PATH]
"""

from __future__ import annotations

import ast
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.db.database import SessionLocal
from backend.db.database import init_db
from backend.db.models import PublishedReview
from backend.eval.opportunity import DecisionOpportunity
from backend.eval.opportunity import GameFeatureBuilder
from backend.eval.opportunity import OpportunityType
from backend.eval.opportunity import OutcomeFeatureBuilder
from backend.eval.opportunity import _uid


def _parse_field(value: Any) -> Any:
    """Parse stored string representations of Python/JSON objects."""
    if not isinstance(value, str):
        return value
    value = value.strip()
    if not value:
        return {} if "{" in value else []
    # Try JSON first
    try:
        return json.loads(value)
    except (json.JSONDecodeError, ValueError):
        pass
    # Try Python literal
    try:
        return ast.literal_eval(value)
    except (ValueError, SyntaxError):
        pass
    return value


def _extract_target_id(selected_action: dict) -> str | None:
    """Extract target player ID from selected action."""
    return selected_action.get("target_id") or selected_action.get("target") or selected_action.get("player_id")


def _classify_opportunity(role: str, phase: str, action_type: str, selected_action: dict) -> str | None:
    """Map (role, phase, action_type) to opportunity type."""
    at = action_type.lower()

    # Night actions
    if phase == "NIGHT_SEER_ACTION" and at == "divine":
        return OpportunityType.SEER_CHECK
    if phase == "NIGHT_WITCH_ACTION":
        if at == "witch_save":
            return OpportunityType.WITCH_SAVE
        if at == "witch_poison":
            return OpportunityType.WITCH_POISON
        if at == "skip":
            return "witch_skip"  # Choosing not to use poison
    if phase == "NIGHT_GUARD_ACTION" and at == "guard":
        return OpportunityType.GUARD_PROTECT
    if phase == "NIGHT_WOLF_ACTION" and at == "attack":
        return OpportunityType.WEREWOLF_KILL
    if phase == "HUNTER_SHOOT" and at == "shoot":
        return OpportunityType.HUNTER_SHOT

    # Day actions
    if at in ("vote",) and phase in ("DAY_VOTE", "DAY_BADGE_ELECTION", "BADGE_TRANSFER"):
        return OpportunityType.VOTE

    if at in ("talk", "speech", "chat") and phase in (
        "DAY_SPEECH",
        "DAY_BADGE_SPEECH",
        "DAY_LAST_WORDS",
    ):
        speech_text = str(selected_action.get("speech") or selected_action.get("text") or "")
        if role == "Seer" and any(kw in speech_text for kw in ["查验", "查杀", "金水", "divine"]):
            return OpportunityType.SEER_RELEASE
        return OpportunityType.SPEECH

    return None


def _build_public_context(events: list[dict], day: int, phase: str) -> str:
    """Summarize recent public events."""
    recent = [
        e
        for e in events
        if int(e.get("day", 0)) == day
        and e.get("event_type") in ("CHAT_MESSAGE", "VOTE_CAST", "PLAYER_DIED", "BADGE_AWARDED")
    ]
    lines = []
    for e in recent[-6:]:
        pt = e.get("public_text", "")
        if pt:
            lines.append(f"[D{e.get('day', 0)}] {pt[:150]}")
    return "\n".join(lines) if lines else "(no public events this phase)"


def _gather_evidence(events: list[dict], day: int, player_id: str, target_id: str | None) -> list[str]:
    """Collect relevant event IDs as evidence."""
    ids: list[str] = []
    for e in events:
        e_day = int(e.get("day", 0))
        if e_day > day:
            break
        if e_day == day or (e_day == day - 1 and day > 0):
            eid = e.get("event_id", "")
            actor = e.get("actor_id", "")
            target = e.get("target_id", "")
            if actor in (player_id, target_id) or target in (player_id, target_id):
                if eid and eid not in ids:
                    ids.append(eid)
    return ids[:20]


def extract_from_bundle(bundle: dict) -> list[DecisionOpportunity]:
    """Extract all DecisionOpportunity records from one replay_bundle."""
    game_id = bundle["game_id"]
    players = bundle.get("players", [])
    events = bundle.get("events", [])
    decisions = bundle.get("decisions", [])
    deaths = bundle.get("deaths", [])
    winner = bundle.get("winner")

    opportunities: list[DecisionOpportunity] = []

    for dec in decisions:
        role = dec.get("role", "Unknown")
        phase = dec.get("phase", "")
        day = int(dec.get("day", 0))
        player_id = dec.get("player_id", "")
        persona_id = dec.get("persona_id")

        # Parse selected_action
        selected_action = _parse_field(dec.get("selected_action", "{}"))
        if not isinstance(selected_action, dict):
            selected_action = {}

        action_type = str(selected_action.get("type") or selected_action.get("action_type") or "")

        # Classify
        op_type = _classify_opportunity(role, phase, action_type, selected_action)
        if op_type is None:
            continue

        # Parse legal_actions
        legal_actions = _parse_field(dec.get("legal_actions", "[]"))
        if not isinstance(legal_actions, list):
            legal_actions = []

        # Parse observation
        obs_raw = _parse_field(dec.get("observation_summary", ""))
        if isinstance(obs_raw, dict):
            private_ctx = json.dumps(obs_raw, ensure_ascii=False)
        else:
            private_ctx = str(obs_raw)

        # Extract target
        target_id = _extract_target_id(selected_action)

        # Build features
        game_feat, target_feat = GameFeatureBuilder.build(
            players,
            events,
            day,
            phase,
            player_id,
            target_id,
        )
        outcome_feat = OutcomeFeatureBuilder.build(
            events,
            deaths,
            day,
            target_id,
            player_id,
            winner,
        )

        # Public context
        public_ctx = _build_public_context(events, day, phase)

        # Evidence
        evidence_ids = _gather_evidence(events, day, player_id, target_id)

        opp = DecisionOpportunity(
            opportunity_id=f"opp-{game_id[:8]}-{player_id}-d{day}-{op_type}-{_uid()}",
            game_id=game_id,
            player_id=player_id,
            role=role,
            persona_id=persona_id,
            day=day,
            phase=phase,
            opportunity_type=op_type,
            legal_actions=legal_actions,
            chosen_action=selected_action,
            public_context_summary=public_ctx,
            private_context_summary=private_ctx[:2000],
            target_features=target_feat,
            game_features=game_feat,
            outcome_features=outcome_feat,
            evidence_event_ids=evidence_ids,
            source_decision_id=dec.get("decision_id"),
        )
        opportunities.append(opp)

    return opportunities


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="Limit games processed")
    ap.add_argument("--output", default="data/health/opportunities.jsonl")
    ap.add_argument("--stats", default="data/health/opportunity_stats.md")
    args = ap.parse_args()

    init_db()
    db = SessionLocal()

    try:
        # Load clean game IDs
        clean_path = Path("/tmp/clean_llm_game_ids.json")
        clean_ids = set(json.loads(clean_path.read_text()))

        reviews = (
            db.query(PublishedReview)
            .filter(
                PublishedReview.game_id.in_(clean_ids),
                PublishedReview.publish_allowed,
                PublishedReview.replay_bundle is not None,
            )
            .all()
        )

        print(f"Found {len(reviews)} reviews with replay_bundle data")

        if args.limit:
            reviews = reviews[: args.limit]

        all_opps: list[DecisionOpportunity] = []
        per_game_counts: dict[str, int] = {}

        for i, review in enumerate(reviews):
            rb = review.replay_bundle
            if not rb:
                continue
            try:
                opps = extract_from_bundle(rb)
                all_opps.extend(opps)
                per_game_counts[review.game_id[:8]] = len(opps)
                if (i + 1) % 10 == 0:
                    print(f"  Processed {i + 1}/{len(reviews)} games, {len(all_opps)} opportunities so far...")
            except Exception as e:
                print(f"  ERROR game {review.game_id[:8]}: {e}")

        # Write JSONL
        output_path = ROOT / args.output
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            for opp in all_opps:
                f.write(json.dumps(opp.to_dict(), ensure_ascii=False) + "\n")
        print(f"\nWrote {len(all_opps)} opportunities to {output_path}")

        # Generate stats
        _generate_stats(all_opps, per_game_counts, ROOT / args.stats)

    finally:
        db.close()

    return 0


def _generate_stats(
    opps: list[DecisionOpportunity],
    per_game: dict[str, int],
    stats_path: Path,
) -> None:
    """Generate opportunity_stats.md."""
    type_counts = Counter(o.opportunity_type for o in opps)
    role_counts = Counter(o.role for o in opps)
    Counter((o.role, o.opportunity_type) for o in opps)
    day_counts = Counter(o.day for o in opps)

    lines = [
        "# DecisionOpportunity Extraction Stats (Phase 1)",
        "",
        f"**Total opportunities**: {len(opps)}",
        f"**Games processed**: {len(per_game)}",
        f"**Avg per game**: {len(opps) / max(len(per_game), 1):.1f}",
        "",
        "## By Opportunity Type",
        "| Type | Count | Pct |",
        "|------|-------|-----|",
    ]
    total = len(opps)
    for op_type, cnt in type_counts.most_common():
        lines.append(f"| {op_type} | {cnt} | {cnt / total * 100:.1f}% |")

    lines += [
        "",
        "## By Role",
        "| Role | Count | Types |",
        "|------|-------|-------|",
    ]
    for role in sorted(role_counts):
        role_types = Counter(o.opportunity_type for o in opps if o.role == role)
        type_str = ", ".join(f"{t}:{c}" for t, c in role_types.most_common(5))
        lines.append(f"| {role} | {role_counts[role]} | {type_str} |")

    lines += [
        "",
        "## By Day",
        "| Day | Count |",
        "|-----|-------|",
    ]
    for day in sorted(day_counts):
        lines.append(f"| {day} | {day_counts[day]} |")

    lines += [
        "",
        "## Evidence Coverage",
        f"| Opportunities with evidence_event_ids | {sum(1 for o in opps if o.evidence_event_ids)} | {sum(1 for o in opps if o.evidence_event_ids) / max(total, 1) * 100:.1f}% |",
        f"| Avg evidence events per opportunity | {sum(len(o.evidence_event_ids) for o in opps) / max(total, 1):.1f} |",
        "",
        "## Target Feature Coverage",
        f"| Opportunities with target_features | {sum(1 for o in opps if o.target_features)} | {sum(1 for o in opps if o.target_features) / max(total, 1) * 100:.1f}% |",
    ]

    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Stats written to {stats_path}")


if __name__ == "__main__":
    raise SystemExit(main())
