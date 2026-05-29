"""DecisionOpportunity extraction from game replays.

Phase 1 of Track B reconstruction: extracts per-player, per-decision
"opportunities" from completed game replays. Each opportunity frames a
single decision moment with features, context, and outcomes — enabling
opportunity-level quality modeling instead of whole-game scoring.

Design follows docs/狼人杀 B 方向评分系统重构 Goal 文档.md §2.2.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def _uid() -> str:
    return uuid4().hex[:12]


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class DecisionOpportunity:
    """One evaluable decision moment for one player in one game.

    Corresponds to §2.2: o = (x_o, a_o, A_o, y_o, e_o)
    """

    opportunity_id: str
    game_id: str
    player_id: str
    role: str
    persona_id: str | None
    day: int
    phase: str

    # What kind of decision (seer_check, witch_save, werewolf_kill, ...)
    opportunity_type: str

    # Action space
    legal_actions: list[dict[str, Any]]
    chosen_action: dict[str, Any]

    # Human-readable context windows
    public_context_summary: str
    private_context_summary: str

    # Structured feature blocks (§2.2)
    target_features: dict[str, Any] = field(default_factory=dict)
    game_features: dict[str, Any] = field(default_factory=dict)
    outcome_features: dict[str, Any] = field(default_factory=dict)

    # Evidence trail
    evidence_event_ids: list[str] = field(default_factory=list)

    # V8: Strategy traceability
    strategy_id: str = ""
    strategy_name: str = ""
    strategy_type: str = ""

    # Metadata
    extracted_at: str = field(default_factory=_utcnow_iso)
    source_decision_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Opportunity type constants
# ---------------------------------------------------------------------------

class OpportunityType:
    SEER_CHECK = "seer_check"
    SEER_RELEASE = "seer_release"
    WITCH_SAVE = "witch_save"
    WITCH_POISON = "witch_poison"
    GUARD_PROTECT = "guard_protect"
    HUNTER_SHOT = "hunter_shot"
    HUNTER_RESTRAINT = "hunter_restraint"
    WEREWOLF_KILL = "werewolf_kill"
    VOTE = "vote"
    SPEECH = "speech"


# Map from (role, phase, action_type) → opportunity_type
_ACTION_TO_OPPORTUNITY = {
    ("Seer", "NIGHT", "divine"): OpportunityType.SEER_CHECK,
    ("Seer", "DAY", "speech"): OpportunityType.SEER_RELEASE,
    ("Witch", "NIGHT", "save"): OpportunityType.WITCH_SAVE,
    ("Witch", "NIGHT", "poison"): OpportunityType.WITCH_POISON,
    ("Guard", "NIGHT", "guard"): OpportunityType.GUARD_PROTECT,
    ("Hunter", "NIGHT", "shoot"): OpportunityType.HUNTER_SHOT,
    ("Hunter", "DAY", "abstain_shoot"): OpportunityType.HUNTER_RESTRAINT,
    ("Werewolf", "NIGHT", "kill"): OpportunityType.WEREWOLF_KILL,
    ("Villager", "DAY", "vote"): OpportunityType.VOTE,
}

SPEECH_PHASES = {"BADGE_SPEECH", "DAY_SPEECH", "DAY_LAST_WORDS", "BADGE_SIGNUP"}


# ---------------------------------------------------------------------------
# Feature builders
# ---------------------------------------------------------------------------

class GameFeatureBuilder:
    """Builds game_features and target_features from replay context."""

    @staticmethod
    def build(
        players: list[dict[str, Any]],
        events: list[dict[str, Any]],
        day: int,
        phase: str,
        actor_id: str,
        target_id: str | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        alive_count = sum(1 for p in players if p.get("alive"))
        total_players = len(players)
        camp_balance = GameFeatureBuilder._camp_balance(players)
        exposed_roles = GameFeatureBuilder._exposed_roles(events, day)
        is_endgame = alive_count <= 4

        game_features = {
            "day": day,
            "phase": phase,
            "alive_count": alive_count,
            "total_players": total_players,
            "is_endgame": is_endgame,
            "camp_balance": camp_balance,
            "key_roles_exposed": exposed_roles,
        }

        target_features: dict[str, Any] = {}
        if target_id:
            target = next((p for p in players if p["id"] == target_id), None)
            if target:
                target_features = {
                    "target_role": target.get("role"),
                    "target_alignment": target.get("alignment"),
                    "target_alive": target.get("alive"),
                    "target_is_exposed": target.get("role") in exposed_roles,
                }

        return game_features, target_features

    @staticmethod
    def _camp_balance(players: list[dict[str, Any]]) -> dict[str, int]:
        village = sum(1 for p in players if p.get("alignment") == "village" and p.get("alive"))
        wolf = sum(1 for p in players if p.get("alignment") == "wolf" and p.get("alive"))
        return {"village_alive": village, "wolf_alive": wolf}

    @staticmethod
    def _exposed_roles(events: list[dict[str, Any]], up_to_day: int) -> list[str]:
        exposed: set[str] = set()
        for e in events:
            if e.get("day", 0) > up_to_day:
                break
            content = e.get("content", {})
            text = str(e.get("public_text", "") or "")
            for role_label in ["预言家", "女巫", "守卫", "猎人", "Seer", "Witch", "Guard", "Hunter"]:
                if role_label in text:
                    exposed.add(role_label)
        return sorted(exposed)


class OutcomeFeatureBuilder:
    """Builds outcome_features from post-hoc game events."""

    @staticmethod
    def build(
        events: list[dict[str, Any]],
        deaths: list[dict[str, Any]],
        day: int,
        target_id: str | None,
        actor_id: str,
        final_winner: str | None,
    ) -> dict[str, Any]:
        features: dict[str, Any] = {
            "target_died_same_phase": False,
            "target_died_reason": None,
            "actor_died_same_phase": False,
            "camp_won": None,
        }

        if target_id:
            for death in deaths:
                if death.get("player_id") == target_id and death.get("day") == day:
                    features["target_died_same_phase"] = True
                    features["target_died_reason"] = death.get("reason")
                    break

        for death in deaths:
            if death.get("player_id") == actor_id and death.get("day") == day:
                features["actor_died_same_phase"] = True
                break

        return features


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------

class OpportunityExtractor:
    """Extracts DecisionOpportunity records from a ReplayBundle.

    Usage:
        bundle = ReplayBundleBuilder().build(game_state)
        opportunities = OpportunityExtractor().extract(bundle)
    """

    def extract(self, bundle) -> list[DecisionOpportunity]:
        """Extract all opportunities from a replay bundle.

        Accepts either a ReplayBundle dataclass or a dict with the same shape.
        """
        if isinstance(bundle, dict):
            players = bundle["players"]
            events = bundle["events"]
            decisions = bundle["decisions"]
            deaths = bundle.get("deaths", [])
            game_id = bundle["game_id"]
            winner = bundle.get("winner")
        else:
            players = [asdict(p) if hasattr(p, '__dict__') else p for p in bundle.players]
            events = bundle.events
            decisions = bundle.decisions
            deaths = getattr(bundle, 'deaths', [])
            game_id = bundle.game_id
            winner = getattr(bundle, 'winner', None)

        opportunities: list[DecisionOpportunity] = []

        # V8: build player lookup for strategy fallback
        player_map: dict[str, dict] = {}
        for p in players:
            pid = p.get("id", "") if isinstance(p, dict) else getattr(p, "id", "")
            if pid:
                player_map[pid] = p if isinstance(p, dict) else asdict(p) if hasattr(p, '__dict__') else {}

        for dec in decisions:
            role = dec.get("role", "Unknown")
            phase = dec.get("phase", "")
            day = dec.get("day", 0)
            player_id = dec.get("player_id", "")
            persona_id = dec.get("persona_id")

            # Determine opportunity type
            op_type = self._classify(role, phase, dec)
            if op_type is None:
                continue

            # Build features
            target_id = self._extract_target_id(dec, op_type)
            game_feat, target_feat = GameFeatureBuilder.build(
                players, events, day, phase, player_id, target_id,
            )
            outcome_feat = OutcomeFeatureBuilder.build(
                events, deaths, day, target_id, player_id, winner,
            )

            # Build context summaries
            public_ctx = self._build_public_context(events, day, phase, player_id)
            private_ctx = dec.get("observation_summary", "") or ""

            # Gather evidence events
            evidence_ids = self._gather_evidence(events, day, phase, player_id, target_id)

            opportunities.append(DecisionOpportunity(
                opportunity_id=f"opp-{game_id[:8]}-{player_id}-{day}-{op_type}-{_uid()}",
                game_id=game_id,
                player_id=player_id,
                role=role,
                persona_id=persona_id,
                day=day,
                phase=phase,
                opportunity_type=op_type,
                legal_actions=list(dec.get("legal_actions", [])),
                chosen_action=dict(dec.get("selected_action", {})),
                public_context_summary=public_ctx,
                private_context_summary=private_ctx,
                target_features=target_feat,
                game_features=game_feat,
                outcome_features=outcome_feat,
                evidence_event_ids=evidence_ids,
                source_decision_id=dec.get("decision_id"),
                # V8: strategy traceability — read from parsed_action, fallback to player
                strategy_id=(
                    (dec.get("parsed_action") or {}).get("strategy_id")
                    or player_map.get(player_id, {}).get("strategy_id", "")
                ),
                strategy_name=(
                    (dec.get("parsed_action") or {}).get("strategy_name")
                    or player_map.get(player_id, {}).get("strategy_name", "")
                ),
                strategy_type=(
                    (dec.get("parsed_action") or {}).get("strategy_type")
                    or player_map.get(player_id, {}).get("strategy_type", "")
                ),
            ))

        return opportunities

    # ---- classification ------------------------------------------------

    def _classify(self, role: str, phase: str, dec: dict) -> str | None:
        action = dec.get("selected_action", {})
        action_type = action.get("type") or action.get("action_type") or ""

        # Night actions
        if "NIGHT" in phase.upper() or phase.upper() in {"WOLF", "GUARD", "WITCH", "SEER"}:
            return self._classify_night(role, action_type)

        # Day actions
        if action_type == "vote" or action_type == "VOTE":
            return OpportunityType.VOTE

        if action_type in ("speech", "SPEECH", "chat") or phase in SPEECH_PHASES:
            return self._classify_speech(role, dec)

        # Hunter restraint: Day phase with no shot taken
        if role == "Hunter" and action_type in ("abstain", "pass", "skip", ""):
            return OpportunityType.HUNTER_RESTRAINT

        return None

    def _classify_night(self, role: str, action_type: str) -> str | None:
        mapping = {
            "Seer": {"divine": OpportunityType.SEER_CHECK, "check": OpportunityType.SEER_CHECK},
            "Witch": {"save": OpportunityType.WITCH_SAVE, "poison": OpportunityType.WITCH_POISON,
                       "antidote": OpportunityType.WITCH_SAVE, "use_antidote": OpportunityType.WITCH_SAVE,
                       "use_poison": OpportunityType.WITCH_POISON},
            "Guard": {"guard": OpportunityType.GUARD_PROTECT, "protect": OpportunityType.GUARD_PROTECT},
            "Werewolf": {"kill": OpportunityType.WEREWOLF_KILL, "attack": OpportunityType.WEREWOLF_KILL},
            "Hunter": {"shoot": OpportunityType.HUNTER_SHOT},
        }
        role_map = mapping.get(role, {})
        return role_map.get(action_type)

    def _classify_speech(self, role: str, dec: dict) -> str | None:
        action = dec.get("selected_action", {})
        speech_text = str(action.get("speech") or action.get("text") or "")
        if not speech_text.strip():
            return None
        if role == "Seer":
            # Seer releasing check result in speech is a "seer_release"
            if any(kw in speech_text for kw in ["查验", "查杀", "金水", "验", "divine"]):
                return OpportunityType.SEER_RELEASE
        return OpportunityType.SPEECH

    # ---- helpers -------------------------------------------------------

    @staticmethod
    def _extract_target_id(dec: dict, op_type: str) -> str | None:
        action = dec.get("selected_action", {})
        return (
            action.get("target_id")
            or action.get("target")
            or action.get("player_id")
            or action.get("victim_id")
        )

    @staticmethod
    def _build_public_context(
        events: list[dict], day: int, phase: str, player_id: str,
    ) -> str:
        """Build a short public context summary from recent events."""
        recent = [
            e for e in events
            if e.get("day", 0) == day
            and e.get("event_type") in ("CHAT_MESSAGE", "VOTE_CAST", "PLAYER_DIED")
        ]
        lines = []
        for e in recent[-8:]:
            pt = e.get("public_text", "")
            if pt:
                lines.append(f"[D{e.get('day',0)}|{e.get('phase','')}] {pt[:120]}")
        return "\n".join(lines) if lines else "(no public events)"

    @staticmethod
    def _gather_evidence(
        events: list[dict], day: int, phase: str, player_id: str, target_id: str | None,
    ) -> list[str]:
        """Collect event IDs that serve as evidence for this opportunity."""
        ids: list[str] = []
        for e in events:
            if e.get("day", 0) > day:
                break
            if e.get("day") == day or (e.get("day") == day - 1 and day > 0):
                if e.get("actor_id") in (player_id, target_id) or e.get("target_id") in (player_id, target_id):
                    ids.append(e.get("event_id", ""))
        return [i for i in ids if i]


# ---------------------------------------------------------------------------
# Batch extraction entry point
# ---------------------------------------------------------------------------

def extract_all_opportunities(
    game_ids: list[str],
    *,
    output_path: str | None = None,
) -> list[DecisionOpportunity]:
    """Extract opportunities from all published reviews for given game IDs."""
    import json
    from pathlib import Path

    from backend.db.database import SessionLocal, init_db
    from backend.db.models import PublishedReview
    from backend.eval.track_b import reconstruct_review_report, ReplayBundleBuilder

    init_db()
    db = SessionLocal()
    try:
        from sqlalchemy import text
        gids = tuple(game_ids)
        rows = db.execute(text(
            "SELECT pr.game_id, pr.report_json, g.winner "
            "FROM published_reviews pr JOIN games g ON g.id = pr.game_id "
            "WHERE pr.game_id IN :gids AND pr.publish_allowed = true"
        ), {"gids": gids}).fetchall()

        extractor = OpportunityExtractor()
        all_opps: list[DecisionOpportunity] = []

        for game_id, report_json, winner in rows:
            if not report_json:
                continue
            try:
                report = reconstruct_review_report(report_json)
            except Exception:
                continue

            # Build a minimal replay bundle from the report + decisions
            # Since we don't have the full GameState, we use report_json data
            bundle = _report_to_bundle(game_id, report_json, winner)
            opps = extractor.extract(bundle)
            all_opps.extend(opps)

        if output_path:
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                for opp in all_opps:
                    f.write(json.dumps(opp.to_dict(), ensure_ascii=False) + "\n")

        return all_opps
    finally:
        db.close()


def _report_to_bundle(game_id: str, report_json: dict, winner: str | None) -> dict[str, Any]:
    """Convert a stored report_json into a minimal bundle dict for extraction."""
    events = report_json.get("events", [])
    # If events aren't stored in the report, use empty list (opportunities will
    # have less context but still be extractable from decisions alone)
    return {
        "game_id": game_id,
        "rule_pack": "wolfcha-default",
        "players": _extract_players_from_report(report_json),
        "events": events if isinstance(events, list) else [],
        "decisions": _extract_decisions_from_report(report_json),
        "votes": report_json.get("votes", []),
        "deaths": report_json.get("deaths", []),
        "final_state": report_json.get("final_state", {}),
        "winner": winner,
        "finished_at": report_json.get("generated_at", ""),
    }


def _extract_players_from_report(report: dict) -> list[dict[str, Any]]:
    """Extract player info from a review report's player_reviews."""
    players: list[dict[str, Any]] = []
    for pr in report.get("player_reviews", []):
        players.append({
            "id": pr.get("player_id", ""),
            "name": pr.get("player_name", ""),
            "role": pr.get("role", ""),
            "alignment": pr.get("alignment", "village"),
            "alive": True,
            "persona": {"name": pr.get("player_name", "")},
        })
    return players


def _extract_decisions_from_report(report: dict) -> list[dict[str, Any]]:
    """Extract decision-like records from report data.

    Falls back to building synthetic decisions from player_reviews when
    the full decision_records aren't stored in the report JSON.
    """
    decisions = report.get("decisions") or report.get("decision_records") or []
    if decisions:
        return decisions

    # Build synthetic decisions from player_reviews + the review's game_summary
    synthetic: list[dict[str, Any]] = []
    for pr in report.get("player_reviews", []):
        player_id = pr.get("player_id", "")
        role = pr.get("role", "")
        alignment = pr.get("alignment", "village")

        # Vote opportunity
        if pr.get("rule_score_reasons") and any("投票" in str(r) for r in pr.get("rule_score_reasons", [])):
            synthetic.append({
                "decision_id": f"synth-vote-{player_id}",
                "player_id": player_id,
                "role": role,
                "day": 1,
                "phase": "DAY_VOTE",
                "observation_summary": pr.get("overall_summary", ""),
                "legal_actions": [{"type": "vote", "targets": []}],
                "selected_action": {"type": "vote"},
                "parsed_success": True,
                "fallback_used": False,
            })

        # Speech opportunity
        if pr.get("speech_summary"):
            synthetic.append({
                "decision_id": f"synth-speech-{player_id}",
                "player_id": player_id,
                "role": role,
                "day": 1,
                "phase": "DAY_SPEECH",
                "observation_summary": pr.get("speech_summary", ""),
                "legal_actions": [{"type": "speech"}],
                "selected_action": {"type": "speech", "speech": pr.get("speech_summary", "")},
                "parsed_success": True,
                "fallback_used": False,
            })

    return synthetic
