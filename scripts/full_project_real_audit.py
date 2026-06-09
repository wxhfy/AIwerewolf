#!/usr/bin/env python3
"""Run real end-to-end audits for engine, Track B, Track C, and retrieval.

This script intentionally exercises production objects instead of pytest-only
fixtures: WerewolfGame, MetricsCalculator, ReviewReportBuilder,
StrategyKnowledgeDocExtractor, and StrategyKnowledgeStore.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from dataclasses import asdict
from dataclasses import is_dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.agents.heuristic import HeuristicAgent
from backend.engine.actions import ActionValidator
from backend.engine.game import WerewolfGame
from backend.engine.models import ActionType
from backend.engine.models import Alignment
from backend.engine.models import Decision
from backend.engine.models import EventType
from backend.engine.models import GameEvent
from backend.engine.models import GameState
from backend.engine.models import Phase
from backend.engine.models import Player
from backend.engine.models import Role
from backend.engine.rules import ROLE_SPECS
from backend.engine.rules import build_players
from backend.engine.rules import get_role_configuration
from backend.eval.evolution import HashingVectorEmbeddingProvider
from backend.eval.evolution import StrategyKnowledgeDoc
from backend.eval.evolution import StrategyKnowledgeDocExtractor
from backend.eval.evolution import StrategyKnowledgeStore
from backend.eval.evolution import StrategyRetrievalQuery
from backend.eval.review import MarkdownReportRenderer
from backend.eval.review import MetricsCalculator
from backend.eval.review import ReviewReport
from backend.eval.review import ReviewReportBuilder

ISSUE_MAJOR = "major"
ISSUE_CRITICAL = "critical"
CONTROLLED_ROLES = {
    Role.WEREWOLF,
    Role.SEER,
    Role.WITCH,
    Role.HUNTER,
    Role.GUARD,
    Role.IDIOT,
    Role.WHITE_WOLF_KING,
    Role.VILLAGER,
}


def _json_default(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "value"):
        return value.value
    return str(value)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")


def _enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _event_type_counts(states: list[GameState]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for state in states:
        counts.update(_enum_value(event.type) for event in state.events)
    return dict(sorted(counts.items()))


def _phase_counts(states: list[GameState]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for state in states:
        counts.update(_enum_value(event.phase) for event in state.events)
    return dict(sorted(counts.items()))


def _role_counts(states: list[GameState]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for state in states:
        counts.update(player.role.value for player in state.players)
    return dict(sorted(counts.items()))


def _winner_counts(states: list[GameState]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for state in states:
        counts.update([state.winner.value if state.winner else "none"])
    return dict(sorted(counts.items()))


def _issue(issues: list[dict[str, Any]], severity: str, area: str, message: str, evidence: Any = None) -> None:
    issues.append({"severity": severity, "area": area, "message": message, "evidence": evidence})


def make_player(player_id: str, seat: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        id=player_id,
        seat=seat,
        name=name,
        role=role,
        alignment=ROLE_SPECS[role].alignment,
        alive=alive,
    )


def make_control_players() -> dict[Role, Player]:
    return {
        Role.SEER: make_player("P1-seer", 1, "SeerAlpha", Role.SEER),
        Role.WEREWOLF: make_player("P2-wolf", 2, "WolfBravo", Role.WEREWOLF),
        Role.WITCH: make_player("P3-witch", 3, "WitchCharlie", Role.WITCH),
        Role.HUNTER: make_player("P4-hunter", 4, "HunterDelta", Role.HUNTER),
        Role.GUARD: make_player("P5-guard", 5, "GuardEcho", Role.GUARD),
        Role.VILLAGER: make_player("P6-villager", 6, "VillagerFoxtrot", Role.VILLAGER),
        Role.WHITE_WOLF_KING: make_player("P7-wwk", 7, "WhiteWolfGolf", Role.WHITE_WOLF_KING),
        Role.IDIOT: make_player("P8-idiot", 8, "IdiotHotel", Role.IDIOT),
    }


def clone_players(players_by_role: dict[Role, Player]) -> list[Player]:
    return [
        make_player(player.id, player.seat, player.name, player.role, alive=player.alive)
        for player in players_by_role.values()
    ]


def event(
    day: int,
    phase: Phase,
    type_: EventType,
    visibility: str,
    payload: dict[str, Any],
    *,
    visible_to: list[str] | None = None,
) -> GameEvent:
    return GameEvent.create(
        day=day, phase=phase, type=type_, visibility=visibility, payload=payload, visible_to=visible_to
    )


def speech(day: int, actor: Player, text: str, *, phase: Phase = Phase.DAY_SPEECH) -> GameEvent:
    return event(
        day,
        phase,
        EventType.CHAT_MESSAGE,
        "public",
        {"actor_id": actor.id, "actor_name": actor.name, "speech": text, "segment_index": 0, "segment_total": 1},
    )


def vote(day: int, voter: Player, target: Player) -> GameEvent:
    return event(
        day,
        Phase.DAY_VOTE,
        EventType.VOTE_CAST,
        "public",
        {"voter_id": voter.id, "voter_name": voter.name, "target_id": target.id, "target_name": target.name},
    )


def night_action(day: int, actor: Player, action_type: str, target: Player, *, phase: Phase) -> GameEvent:
    return event(
        day,
        phase,
        EventType.NIGHT_ACTION,
        "private",
        {
            "actor_id": actor.id,
            "actor_name": actor.name,
            "action_type": action_type,
            "target_id": target.id,
            "target_name": target.name,
        },
        visible_to=[actor.id],
    )


def seer_result(day: int, seer: Player, target: Player, *, is_wolf: bool) -> GameEvent:
    return event(
        day,
        Phase.NIGHT_SEER_ACTION,
        EventType.PRIVATE_INFO,
        "private",
        {
            "kind": "seer_result",
            "target_id": target.id,
            "target_name": target.name,
            "target_seat": target.seat,
            "is_wolf": is_wolf,
            "message": f"Seer check: seat {target.seat} is {'wolf' if is_wolf else 'not wolf'}.",
        },
        visible_to=[seer.id],
    )


def death(day: int, target: Player, reason: str) -> GameEvent:
    return event(
        day,
        Phase.DAY_RESOLVE if reason == "vote" else Phase.NIGHT_RESOLVE,
        EventType.PLAYER_DIED,
        "public",
        {"player_id": target.id, "player_name": target.name, "reason": reason},
    )


def hunter_shot(day: int, hunter: Player, target: Player) -> GameEvent:
    return event(
        day,
        Phase.HUNTER_SHOOT,
        EventType.HUNTER_SHOT,
        "public",
        {
            "hunter_id": hunter.id,
            "hunter_name": hunter.name,
            "target_id": target.id,
            "target_name": target.name,
        },
    )


def white_wolf_boom(day: int, actor: Player, target: Player) -> GameEvent:
    return event(
        day,
        Phase.WHITE_WOLF_KING_BOOM,
        EventType.WHITE_WOLF_KING_BOOM,
        "public",
        {
            "actor_id": actor.id,
            "actor_name": actor.name,
            "target_id": target.id,
            "target_name": target.name,
        },
    )


def game_state(
    case_id: str, players: list[Player], events: list[GameEvent], *, winner: Alignment, day: int = 2
) -> GameState:
    return GameState(id=case_id, phase=Phase.GAME_END, day=day, players=players, events=events, winner=winner)


def _score_for_role(report: ReviewReport, role: Role) -> dict[str, Any]:
    for entry in report.metadata.get("player_scores", []):
        if entry.get("role") == role.value:
            return entry
    for entry in report.scoreboard:
        if entry.get("role") == role.value:
            return entry
    return {}


def _bad_case_text(report: ReviewReport) -> str:
    chunks: list[str] = []
    for case in report.bad_cases:
        chunks.extend([case.description, case.suggested_fix, case.mistake_type, case.severity])
    for case in report.counterfactuals:
        chunks.extend(
            [case.original_decision, case.alternative_decision, case.expected_effect, case.counterfactual_type]
        )
    return "\n".join(str(item) for item in chunks)


def build_controlled_cases() -> list[tuple[str, GameState, dict[str, Any]]]:
    base = make_control_players()
    cases: list[tuple[str, GameState, dict[str, Any]]] = []

    players = clone_players(base)
    by_role = {player.role: player for player in players}
    cases.append(
        (
            "seer_release_by_seat_number",
            game_state(
                "controlled-seer-release-seat",
                players,
                [
                    seer_result(1, by_role[Role.SEER], by_role[Role.WEREWOLF], is_wolf=True),
                    speech(1, by_role[Role.SEER], "我是预言家，2号是我的查杀，今天归票2号。"),
                    vote(1, by_role[Role.SEER], by_role[Role.WEREWOLF]),
                    vote(1, by_role[Role.VILLAGER], by_role[Role.WEREWOLF]),
                    death(1, by_role[Role.WEREWOLF], "vote"),
                ],
                winner=Alignment.VILLAGE,
            ),
            {
                "expect_no": ["did not release"],
                "expect_score": ("Seer", "role_task_score", ">=", 0.75),
                "expect_text": ["查验结果", "公开"],
            },
        )
    )

    players = clone_players(base)
    by_role = {player.role: player for player in players}
    cases.append(
        (
            "seer_hides_wolf_check",
            game_state(
                "controlled-seer-hide-check",
                players,
                [
                    seer_result(1, by_role[Role.SEER], by_role[Role.WEREWOLF], is_wolf=True),
                    speech(1, by_role[Role.SEER], "今天先听大家发言，我没有特别明确的信息。"),
                    vote(1, by_role[Role.SEER], by_role[Role.VILLAGER]),
                ],
                winner=Alignment.WOLF,
            ),
            {
                "expect_any": ["did not release", "未公开", "查杀命中"],
                "expect_score": ("Seer", "role_task_score", "<", 0.75),
            },
        )
    )

    players = clone_players(base)
    by_role = {player.role: player for player in players}
    cases.append(
        (
            "witch_poison_wolf",
            game_state(
                "controlled-witch-poison-wolf",
                players,
                [
                    night_action(
                        1, by_role[Role.WITCH], "witch_poison", by_role[Role.WEREWOLF], phase=Phase.NIGHT_WITCH_ACTION
                    ),
                    death(1, by_role[Role.WEREWOLF], "poison"),
                ],
                winner=Alignment.VILLAGE,
            ),
            {"expect_no": ["poisoned villager-side"], "expect_score": ("Witch", "skill_score", ">=", 0.65)},
        )
    )

    players = clone_players(base)
    by_role = {player.role: player for player in players}
    cases.append(
        (
            "witch_poison_villager",
            game_state(
                "controlled-witch-poison-villager",
                players,
                [
                    night_action(
                        1, by_role[Role.WITCH], "witch_poison", by_role[Role.VILLAGER], phase=Phase.NIGHT_WITCH_ACTION
                    ),
                    death(1, by_role[Role.VILLAGER], "poison"),
                ],
                winner=Alignment.WOLF,
            ),
            {
                "expect_any": ["poisoned villager-side", "毒杀了好人"],
                "expect_score": ("Witch", "skill_score", "<=", 0.55),
            },
        )
    )

    players = clone_players(base)
    by_role = {player.role: player for player in players}
    cases.append(
        (
            "guard_blocks_key_role_attack",
            game_state(
                "controlled-guard-save-seer",
                players,
                [
                    night_action(
                        1, by_role[Role.WEREWOLF], "attack", by_role[Role.SEER], phase=Phase.NIGHT_WOLF_ACTION
                    ),
                    night_action(1, by_role[Role.GUARD], "guard", by_role[Role.SEER], phase=Phase.NIGHT_GUARD_ACTION),
                    event(
                        1,
                        Phase.NIGHT_RESOLVE,
                        EventType.SYSTEM_MESSAGE,
                        "public",
                        {"message": "No one died last night."},
                    ),
                ],
                winner=Alignment.VILLAGE,
            ),
            {"expect_score": ("Guard", "role_task_score", ">=", 0.75), "expect_text": ["守卫", "高价值"]},
        )
    )

    players = clone_players(base)
    by_role = {player.role: player for player in players}
    cases.append(
        (
            "hunter_shoots_wolf",
            game_state(
                "controlled-hunter-shoot-wolf",
                players,
                [
                    hunter_shot(1, by_role[Role.HUNTER], by_role[Role.WEREWOLF]),
                    death(1, by_role[Role.WEREWOLF], "shoot"),
                ],
                winner=Alignment.VILLAGE,
            ),
            {"expect_no": ["shot villager-side"], "expect_score": ("Hunter", "skill_score", ">=", 0.9)},
        )
    )

    players = clone_players(base)
    by_role = {player.role: player for player in players}
    cases.append(
        (
            "hunter_shoots_villager",
            game_state(
                "controlled-hunter-shoot-villager",
                players,
                [
                    hunter_shot(1, by_role[Role.HUNTER], by_role[Role.VILLAGER]),
                    death(1, by_role[Role.VILLAGER], "shoot"),
                ],
                winner=Alignment.WOLF,
            ),
            {"expect_any": ["shot villager-side", "友方误伤"], "expect_score": ("Hunter", "skill_score", "<=", 0.35)},
        )
    )

    players = clone_players(base)
    by_role = {player.role: player for player in players}
    cases.append(
        (
            "white_wolf_king_boom",
            game_state(
                "controlled-white-wolf-king-boom",
                players,
                [
                    speech(1, by_role[Role.WHITE_WOLF_KING], "我选择白天自爆带走关键好人。", phase=Phase.DAY_SPEECH),
                    white_wolf_boom(1, by_role[Role.WHITE_WOLF_KING], by_role[Role.SEER]),
                    death(1, by_role[Role.SEER], "boom"),
                ],
                winner=Alignment.WOLF,
            ),
            {
                "expect_event": EventType.WHITE_WOLF_KING_BOOM.value,
                "expect_score": ("WhiteWolfKing", "role_task_score", ">=", 0.45),
            },
        )
    )

    players = clone_players(base)
    by_role = {player.role: player for player in players}
    cases.append(
        (
            "idiot_reveal_survives_vote",
            game_state(
                "controlled-idiot-reveal",
                players,
                [
                    vote(1, by_role[Role.WEREWOLF], by_role[Role.IDIOT]),
                    vote(1, by_role[Role.VILLAGER], by_role[Role.IDIOT]),
                    event(
                        1,
                        Phase.DAY_RESOLVE,
                        EventType.SYSTEM_MESSAGE,
                        "public",
                        {
                            "message": f"{by_role[Role.IDIOT].name} revealed as Idiot and survives exile, but loses voting rights."
                        },
                    ),
                ],
                winner=Alignment.VILLAGE,
            ),
            {"expect_text": ["Idiot"], "expect_score": ("Idiot", "role_task_score", ">=", 0.0)},
        )
    )
    return cases


def run_natural_games(
    seeds: list[int], player_counts: list[int], max_days: int, issues: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for seed in seeds:
        for player_count in player_counts:
            roles = get_role_configuration(player_count)
            players = build_players(roles, seed=seed)
            for player in players:
                player.agent_type = "heuristic"
            agents = {player.id: HeuristicAgent(player.id, seed=seed * 1000 + player.seat) for player in players}
            game = WerewolfGame(players=players, agents=agents, seed=seed, max_days=max_days, player_count=player_count)
            state = game.play()
            metrics = MetricsCalculator().compute(state)
            report = ReviewReportBuilder().build(state, metrics)
            report.metadata["quality_passed"] = True
            report.metadata["validation_result"] = {"passed": True, "publish_allowed": True}
            records.append(
                {
                    "kind": "natural_engine_game",
                    "agent_source": "heuristic_agent",
                    "seed": seed,
                    "player_count": player_count,
                    "state": state,
                    "metrics": metrics,
                    "report": report,
                    "markdown": MarkdownReportRenderer().render(report),
                }
            )
            validate_game_state(state, report, issues, label=f"natural seed={seed} players={player_count}")
    return records


def validate_game_state(state: GameState, report: ReviewReport, issues: list[dict[str, Any]], *, label: str) -> None:
    if state.winner is None:
        _issue(issues, ISSUE_CRITICAL, "engine", f"{label}: game ended without winner", {"game_id": state.id})
    if not state.events:
        _issue(issues, ISSUE_CRITICAL, "engine", f"{label}: no events were produced", {"game_id": state.id})
    if not any(event.type == EventType.GAME_END for event in state.events):
        _issue(issues, ISSUE_MAJOR, "engine", f"{label}: missing GAME_END event", {"game_id": state.id})

    public = state.public_dict()
    for player in public.get("players", []):
        leaked = sorted(set(player) & {"role", "alignment"})
        if leaked:
            _issue(issues, ISSUE_CRITICAL, "visibility", f"{label}: public player leaked private fields", leaked)
    for key in ("night_actions", "role_abilities"):
        if key in public:
            _issue(
                issues, ISSUE_CRITICAL, "visibility", f"{label}: public snapshot leaked {key}", {"game_id": state.id}
            )
    for event_payload in public.get("events", []):
        payload = event_payload.get("payload") or {}
        if event_payload.get("type") == EventType.PRIVATE_INFO.value:
            _issue(issues, ISSUE_CRITICAL, "visibility", f"{label}: private info appeared in public events", payload)
        if event_payload.get("type") == EventType.NIGHT_ACTION.value and any(
            field in payload for field in ("actor_id", "target_id", "target_name", "action_type")
        ):
            _issue(issues, ISSUE_CRITICAL, "visibility", f"{label}: public night action leaked details", payload)

    validate_report(report, len(state.players), issues, label=label)
    validate_speech_segments(state, issues, label=label)


def validate_speech_segments(state: GameState, issues: list[dict[str, Any]], *, label: str) -> None:
    chat_events = [event for event in state.events if event.type == EventType.CHAT_MESSAGE]
    grouped: dict[tuple[str, int, str], list[GameEvent]] = {}
    for event_item in chat_events:
        payload = event_item.payload
        idx = payload.get("segment_index")
        total = payload.get("segment_total")
        if idx is None or total is None:
            _issue(
                issues,
                ISSUE_MAJOR,
                "speech_segments",
                f"{label}: chat event missing segment metadata",
                event_item.to_dict(),
            )
            continue
        if not isinstance(idx, int) or not isinstance(total, int) or idx < 0 or total <= 0 or idx >= total:
            _issue(
                issues, ISSUE_MAJOR, "speech_segments", f"{label}: invalid segment index/total", event_item.to_dict()
            )
        if idx > 0 and str(payload.get("reasoning") or "").strip():
            _issue(
                issues,
                ISSUE_MAJOR,
                "speech_segments",
                f"{label}: reasoning leaked into non-first segment",
                event_item.to_dict(),
            )
        grouped.setdefault(
            (str(payload.get("actor_id")), event_item.day, str(payload.get("request") or event_item.phase.value)), []
        ).append(event_item)
    if chat_events and not any((event.payload.get("segment_total") or 0) > 1 for event in chat_events):
        _issue(
            issues,
            ISSUE_MAJOR,
            "speech_segments",
            f"{label}: no multi-segment speech observed",
            {"chat_count": len(chat_events)},
        )


def validate_report(report: ReviewReport, expected_players: int, issues: list[dict[str, Any]], *, label: str) -> None:
    if not report.game_summary or len(report.game_summary.strip()) < 10:
        _issue(issues, ISSUE_MAJOR, "track_b", f"{label}: report summary too short", report.game_summary)
    if len(report.player_reviews) != expected_players:
        _issue(
            issues,
            ISSUE_CRITICAL,
            "track_b",
            f"{label}: player review count mismatch",
            {"expected": expected_players, "actual": len(report.player_reviews)},
        )
    if len(report.scoreboard) != expected_players:
        _issue(
            issues,
            ISSUE_CRITICAL,
            "track_b",
            f"{label}: scoreboard count mismatch",
            {"expected": expected_players, "actual": len(report.scoreboard)},
        )
    scores = [float(item.get("adjusted_final_score", item.get("rule_score", 0))) for item in report.scoreboard]
    if scores != sorted(scores, reverse=True):
        _issue(issues, ISSUE_MAJOR, "track_b", f"{label}: scoreboard is not sorted by adjusted score", scores)
    for entry in report.scoreboard:
        for key in ("rule_score", "adjusted_final_score"):
            value = float(entry.get(key, 0))
            if not 0 <= value <= 100:
                _issue(issues, ISSUE_CRITICAL, "track_b", f"{label}: score out of range", entry)
    for review in report.player_reviews:
        if not review.overall_summary:
            _issue(issues, ISSUE_MAJOR, "track_b", f"{label}: empty player overall summary", asdict(review))
        if not review.score_summary:
            _issue(issues, ISSUE_MAJOR, "track_b", f"{label}: empty player score summary", asdict(review))


def evaluate_controlled_cases(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    outputs: list[dict[str, Any]] = []
    for name, state, expectations in build_controlled_cases():
        metrics = MetricsCalculator().compute(state)
        report = ReviewReportBuilder().build(state, metrics)
        report.metadata["quality_passed"] = True
        report.metadata["validation_result"] = {"passed": True, "publish_allowed": True}
        markdown = MarkdownReportRenderer().render(report)
        text = _bad_case_text(report) + "\n" + markdown
        validate_report(report, len(state.players), issues, label=f"controlled {name}")
        validate_control_expectations(name, state, report, text, expectations, issues)
        outputs.append(
            {
                "kind": "controlled_case",
                "case": name,
                "state": state,
                "metrics": metrics,
                "report": report,
                "markdown": markdown,
                "expectations": expectations,
            }
        )
    return outputs


def _compare(value: float, op: str, threshold: float) -> bool:
    if op == ">=":
        return value >= threshold
    if op == ">":
        return value > threshold
    if op == "<=":
        return value <= threshold
    if op == "<":
        return value < threshold
    if op == "==":
        return value == threshold
    raise ValueError(f"Unsupported comparison: {op}")


def validate_control_expectations(
    name: str,
    state: GameState,
    report: ReviewReport,
    text: str,
    expectations: dict[str, Any],
    issues: list[dict[str, Any]],
) -> None:
    for token in expectations.get("expect_any", []):
        if token in text:
            break
    else:
        if expectations.get("expect_any"):
            _issue(
                issues,
                ISSUE_MAJOR,
                "controlled_case",
                f"{name}: expected one text token missing",
                expectations["expect_any"],
            )

    for token in expectations.get("expect_text", []):
        if token not in text:
            _issue(issues, ISSUE_MAJOR, "controlled_case", f"{name}: expected text token missing", token)

    for token in expectations.get("expect_no", []):
        if token in text:
            _issue(issues, ISSUE_MAJOR, "controlled_case", f"{name}: forbidden text appeared", token)

    if "expect_event" in expectations:
        expected_type = expectations["expect_event"]
        if not any(event.type.value == expected_type for event in state.events):
            _issue(issues, ISSUE_MAJOR, "controlled_case", f"{name}: expected event missing", expected_type)

    if "expect_score" in expectations:
        role_name, field, op, threshold = expectations["expect_score"]
        score = next((item for item in report.metadata.get("player_scores", []) if item.get("role") == role_name), {})
        value = float(score.get(field, -1))
        if not _compare(value, op, float(threshold)):
            _issue(
                issues,
                ISSUE_MAJOR,
                "controlled_case",
                f"{name}: score expectation failed",
                {"role": role_name, "field": field, "actual": value, "op": op, "threshold": threshold},
            )


def validate_core_rules(issues: list[dict[str, Any]]) -> dict[str, Any]:
    players = list(make_control_players().values())
    state = GameState(id="core-rule-check", phase=Phase.NIGHT_START, day=1, players=players)
    by_role = {player.role: player for player in players}
    validator = ActionValidator()
    checks = {
        "wolf_can_attack_villager": validator.validate(
            state, Decision(by_role[Role.WEREWOLF].id, ActionType.ATTACK, target_id=by_role[Role.VILLAGER].id)
        ),
        "wolf_cannot_attack_wolf": validator.validate(
            state, Decision(by_role[Role.WEREWOLF].id, ActionType.ATTACK, target_id=by_role[Role.WHITE_WOLF_KING].id)
        ),
        "seer_cannot_divine_self": validator.validate(
            state, Decision(by_role[Role.SEER].id, ActionType.DIVINE, target_id=by_role[Role.SEER].id)
        ),
        "guard_can_guard_self": validator.validate(
            state, Decision(by_role[Role.GUARD].id, ActionType.GUARD, target_id=by_role[Role.GUARD].id)
        ),
        "villager_cannot_poison": validator.validate(
            state, Decision(by_role[Role.VILLAGER].id, ActionType.WITCH_POISON, target_id=by_role[Role.WEREWOLF].id)
        ),
    }
    expected = {
        "wolf_can_attack_villager": True,
        "wolf_cannot_attack_wolf": False,
        "seer_cannot_divine_self": False,
        "guard_can_guard_self": True,
        "villager_cannot_poison": False,
    }
    for key, expected_value in expected.items():
        if checks.get(key) != expected_value:
            _issue(issues, ISSUE_CRITICAL, "core_rules", f"{key} expected {expected_value}", checks.get(key))

    roles = (Role.WEREWOLF, Role.SEER, Role.WITCH, Role.GUARD, Role.VILLAGER, Role.HUNTER, Role.VILLAGER)
    milk_players = build_players(roles, seed=909)
    milk_agents = {player.id: HeuristicAgent(player.id, seed=9090 + player.seat) for player in milk_players}
    game = WerewolfGame(players=milk_players, agents=milk_agents, seed=909, max_days=2, player_count=7)
    wolf = next(player for player in game.state.players if player.alignment == Alignment.WOLF)
    target = next(
        player for player in game.state.players if player.alignment == Alignment.VILLAGE and player.role != Role.WITCH
    )
    game.state.day = 1
    game.state.night_actions.wolf_target_id = target.id
    game.state.night_actions.guard_target_id = target.id
    game.state.night_actions.witch_save = True
    game.state.night_actions.wolf_votes = {wolf.id: target.id}
    game._night_resolve()
    milk_through_dead = not game.state.player(target.id).alive
    checks["milk_through_dead"] = milk_through_dead
    checks["milk_through_reason"] = game.state.player(target.id).death_reason
    if not milk_through_dead or game.state.player(target.id).death_reason != "milk_through":
        _issue(issues, ISSUE_CRITICAL, "core_rules", "milk-through did not kill guarded+saved wolf target", checks)
    return checks


def doc_text(doc: StrategyKnowledgeDoc) -> str:
    return "\n".join(
        [
            doc.situation_pattern,
            " ".join(doc.trigger_conditions),
            doc.recommended_action,
            doc.avoid_action or "",
            doc.rationale,
            doc.evidence_summary,
        ]
    )


def validate_track_c(reports: list[ReviewReport], issues: list[dict[str, Any]]) -> dict[str, Any]:
    docs = StrategyKnowledgeDocExtractor().extract(reports)
    for doc in docs:
        doc.status = "active" if doc.quality_score >= 0.85 else "candidate"
    store = StrategyKnowledgeStore(
        docs,
        embedding_provider=HashingVectorEmbeddingProvider(dimensions=256),
        rerank_provider=None,
    )
    all_docs = store.all(include_deprecated=True)
    if not all_docs:
        _issue(issues, ISSUE_CRITICAL, "track_c", "no strategy knowledge docs extracted", {})

    known_names = {review.player_name for report in reports for review in report.player_reviews}
    leak_re = re.compile(r"\bP\d+-[A-Za-z0-9]+\b|private_info|role_assignment", re.IGNORECASE)
    invalid_docs: list[dict[str, Any]] = []
    leaked_docs: list[dict[str, Any]] = []
    for doc in all_docs:
        text = doc_text(doc)
        if not doc.situation_pattern.strip() or not doc.recommended_action.strip() or not doc.rationale.strip():
            invalid_docs.append(
                {"doc_id": doc.doc_id, "role": doc.role, "phase": doc.phase, "reason": "empty core fields"}
            )
        if not (0 <= doc.quality_score <= 1) or not (0 <= doc.confidence <= 1):
            invalid_docs.append(
                {
                    "doc_id": doc.doc_id,
                    "role": doc.role,
                    "phase": doc.phase,
                    "reason": "quality/confidence out of range",
                }
            )
        leaked_names = sorted(name for name in known_names if name and name in text)
        if leak_re.search(text) or leaked_names:
            leaked_docs.append(
                {
                    "doc_id": doc.doc_id,
                    "role": doc.role,
                    "phase": doc.phase,
                    "names": leaked_names[:3],
                    "text": text[:400],
                }
            )
    if invalid_docs:
        _issue(issues, ISSUE_MAJOR, "track_c", "invalid knowledge docs found", invalid_docs[:10])
    if leaked_docs:
        _issue(
            issues,
            ISSUE_CRITICAL,
            "track_c",
            "knowledge docs leaked concrete player/private identifiers",
            leaked_docs[:10],
        )

    role_dist = Counter(doc.role for doc in all_docs)
    phase_dist = Counter(doc.phase for doc in all_docs)
    required_roles = {"Seer", "Witch", "Hunter", "Guard", "Werewolf", "Villager"}
    missing_roles = sorted(role for role in required_roles if role_dist.get(role, 0) == 0)
    if missing_roles:
        _issue(issues, ISSUE_MAJOR, "track_c", "missing required role docs", missing_roles)
    source_event_coverage = 0.0 if not all_docs else sum(1 for doc in all_docs if doc.source_event_ids) / len(all_docs)
    if all_docs and source_event_coverage < 0.5:
        _issue(issues, ISSUE_MAJOR, "track_c", "low source event coverage", source_event_coverage)

    queries = [
        StrategyRetrievalQuery(
            role="Seer",
            phase="DAY_SPEECH",
            observation_summary="I checked a wolf result and need to convert it into public pressure without leaking private notes.",
            situation_tags=["seer", "wolf_check", "speech"],
            top_k=3,
            enable_rerank=False,
        ),
        StrategyRetrievalQuery(
            role="Witch",
            phase="NIGHT_ACTION",
            observation_summary="I am considering poison and need to avoid friendly fire.",
            situation_tags=["witch", "poison"],
            top_k=3,
            enable_rerank=False,
        ),
        StrategyRetrievalQuery(
            role="Guard",
            phase="NIGHT_ACTION",
            observation_summary="Wolves may attack a power role and I need a guard target.",
            situation_tags=["guard", "protect"],
            top_k=3,
            enable_rerank=False,
        ),
        StrategyRetrievalQuery(
            role="Werewolf",
            phase="DAY_VOTE",
            observation_summary="Wolf team needs to push votes without exposing teammates.",
            situation_tags=["werewolf", "vote"],
            top_k=3,
            enable_rerank=False,
        ),
        StrategyRetrievalQuery(
            role="Hunter",
            phase="DAY_SPEECH",
            observation_summary="I may die and need a high confidence shot instead of friendly fire.",
            situation_tags=["hunter", "shot"],
            top_k=3,
            enable_rerank=False,
        ),
    ]
    retrieval_samples = []
    for query in queries:
        lessons = store.retrieve(query)
        retrieval_samples.append(
            {
                "query": asdict(query),
                "results": [asdict(lesson) for lesson in lessons],
            }
        )
        if not lessons:
            _issue(
                issues, ISSUE_MAJOR, "retrieval", f"no lessons returned for {query.role}/{query.phase}", asdict(query)
            )
        elif lessons[0].role not in {query.role, "global"}:
            _issue(
                issues,
                ISSUE_MAJOR,
                "retrieval",
                f"top lesson role mismatch for {query.role}/{query.phase}",
                asdict(lessons[0]),
            )

    qualities = [doc.quality_score for doc in all_docs]
    return {
        "docs": all_docs,
        "retrieval_samples": retrieval_samples,
        "summary": {
            "knowledge_doc_count": len(all_docs),
            "role_distribution": dict(sorted(role_dist.items())),
            "phase_distribution": dict(sorted(phase_dist.items())),
            "quality_min": round(min(qualities), 4) if qualities else None,
            "quality_max": round(max(qualities), 4) if qualities else None,
            "quality_avg": round(sum(qualities) / len(qualities), 4) if qualities else None,
            "invalid_doc_count": len(invalid_docs),
            "leak_doc_count": len(leaked_docs),
            "source_event_coverage": round(source_event_coverage, 4),
            "retrieval_query_count": len(queries),
        },
    }


def db_health(issues: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        import psycopg2

        from backend.db.database import DATABASE_URL
        from backend.db.database import DEFAULT_DB_URL

        result = {
            "database_url_present": bool(DATABASE_URL),
            "default_scheme": DEFAULT_DB_URL.split(":", 1)[0] if DEFAULT_DB_URL else "",
            "default_uses_env": bool(
                DATABASE_URL and DEFAULT_DB_URL != "postgresql://werewolf:werewolf_dev_password@127.0.0.1:5433/werewolf"
            ),
            "connect_ok": False,
        }
        try:
            conn = psycopg2.connect(DEFAULT_DB_URL, connect_timeout=5)
            cur = conn.cursor()
            cur.execute("select 1")
            result["connect_ok"] = cur.fetchone()[0] == 1
            cur.close()
            conn.close()
        except Exception as exc:
            result["error_type"] = type(exc).__name__
            result["error_hint"] = _redact_conn_error(exc)
            _issue(issues, ISSUE_MAJOR, "db", "DEFAULT_DB_URL psycopg2 connection failed", result)
        return result
    except Exception as exc:
        result = {"connect_ok": False, "error_type": type(exc).__name__, "error_hint": _redact_conn_error(exc)}
        _issue(issues, ISSUE_MAJOR, "db", "DB health check failed", result)
        return result


def _redact_conn_error(exc: Exception) -> str:
    return re.sub(r"(postgres(?:ql)?(?:\+\w+)?://[^:\s/@]+):([^@\s]+)@", r"\1:***@", str(exc)).splitlines()[0][:240]


def _redact_secret_error(exc: Exception) -> str:
    text = str(exc).splitlines()[0] if str(exc) else repr(exc)
    text = re.sub(r"(api[-_]?key|token|authorization|x-api-key)(['\":=\s]+)[^,\s}]+", r"\1\2***", text, flags=re.I)
    text = re.sub(r"(Bearer\s+)[A-Za-z0-9._\-]+", r"\1***", text)
    return text[:240]


def real_llm_probe(provider: str | None, issues: list[dict[str, Any]]) -> dict[str, Any]:
    start = time.perf_counter()
    try:
        from backend.llm import create_client

        client = create_client(provider=provider, timeout=20, max_retries=0)
        base_url = str(getattr(client, "base_url", "") or "")
        host = urlparse(base_url).netloc or base_url.split("/")[0]
        result = {
            "provider_requested": provider or "env_default",
            "provider": getattr(client, "provider", provider or "unknown"),
            "available": bool(getattr(client, "available", True)),
            "model": getattr(client, "model", ""),
            "base_url_host_hint": host,
            "latency_seconds": None,
            "content_preview": "",
            "ok": False,
        }
        if not result["available"]:
            _issue(issues, ISSUE_MAJOR, "llm", "LLM client unavailable", result)
            return result
        response = client.chat_sync(
            [
                {"role": "system", "content": "Return only the marker requested by the user."},
                {"role": "user", "content": "Reply exactly: AIWEREWOLF_REAL_LLM_OK"},
            ],
            max_tokens=32,
            temperature=0,
            thinking=False,
        )
        result["latency_seconds"] = round(time.perf_counter() - start, 3)
        content = _extract_llm_content(response)
        result["content_preview"] = content[:120]
        result["ok"] = "AIWEREWOLF_REAL_LLM_OK" in content
        if not result["ok"]:
            _issue(issues, ISSUE_MAJOR, "llm", "LLM probe returned unexpected content", result)
        return result
    except Exception as exc:
        result = {
            "provider_requested": provider or "env_default",
            "available": False,
            "ok": False,
            "latency_seconds": round(time.perf_counter() - start, 3),
            "error_type": type(exc).__name__,
            "error_hint": _redact_secret_error(exc),
        }
        _issue(issues, ISSUE_MAJOR, "llm", "real LLM probe failed", result)
        return result


def real_llm_matrix(providers: list[str | None], issues: list[dict[str, Any]]) -> dict[str, Any]:
    """Probe multiple real providers while treating at least one success as pass."""
    local_issues: list[dict[str, Any]] = []
    probes = [real_llm_probe(provider, local_issues) for provider in providers]
    any_ok = any(probe.get("ok") for probe in probes)
    if not any_ok:
        issues.extend(local_issues)
    return {
        "ok": any_ok,
        "providers_requested": [provider or "env_default" for provider in providers],
        "probes": probes,
        "non_blocking_failures": [] if not any_ok else local_issues,
    }


def _extract_llm_content(response: dict[str, Any]) -> str:
    try:
        choices = response.get("choices") or []
        if choices:
            message = choices[0].get("message") or {}
            return str(message.get("content") or "")
    except Exception:
        pass
    return json.dumps(response, ensure_ascii=False)[:1000]


def compact_state(state: GameState) -> dict[str, Any]:
    return {
        "game_id": state.id,
        "winner": state.winner.value if state.winner else None,
        "day": state.day,
        "phase": state.phase.value,
        "players": [
            {
                "id": player.id,
                "seat": player.seat,
                "name": player.name,
                "role": player.role.value,
                "alignment": player.alignment.value,
                "alive": player.alive,
                "death_day": player.death_day,
                "death_reason": player.death_reason,
            }
            for player in state.players
        ],
        "event_count": len(state.events),
        "event_type_counts": dict(Counter(event.type.value for event in state.events)),
        "phase_counts": dict(Counter(event.phase.value for event in state.events)),
        "chat_segment_count": sum(1 for event in state.events if event.type == EventType.CHAT_MESSAGE),
        "multi_segment_chat_count": sum(
            1
            for event in state.events
            if event.type == EventType.CHAT_MESSAGE and int(event.payload.get("segment_total") or 0) > 1
        ),
    }


def compact_report(report: ReviewReport) -> dict[str, Any]:
    return {
        "game_id": report.game_id,
        "winner": report.winner,
        "total_days": report.total_days,
        "total_events": report.total_events,
        "game_summary": report.game_summary,
        "scoreboard": report.scoreboard,
        "mvp_results": [asdict(item) for item in report.mvp_results],
        "bad_cases": [asdict(item) for item in report.bad_cases],
        "counterfactuals": [asdict(item) for item in report.counterfactuals],
        "player_reviews": [asdict(item) for item in report.player_reviews],
    }


def render_audit_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Full Project Real Audit",
        "",
        f"- generated_at: {summary['generated_at']}",
        f"- natural_games: {summary['natural_game_count']}",
        f"- controlled_cases: {summary['controlled_case_count']}",
        f"- issue_count: {len(summary['issues'])}",
        "",
        "## Core Rules",
        "```json",
        json.dumps(summary["core"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Coverage",
        "```json",
        json.dumps(summary["coverage"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Track C",
        "```json",
        json.dumps(summary["track_c"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## DB Health",
        "```json",
        json.dumps(summary["db_health"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Real LLM Probe",
        "```json",
        json.dumps(summary["real_llm"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Issues",
    ]
    if summary["issues"]:
        for item in summary["issues"]:
            lines.append(f"- [{item['severity']}] {item['area']}: {item['message']}")
    else:
        lines.append("- No blocking issues found by this audit.")
    return "\n".join(lines) + "\n"


def parse_csv_ints(value: str) -> list[int]:
    return [int(part.strip()) for part in value.split(",") if part.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", default="1,2,3", help="Comma-separated natural game seeds.")
    parser.add_argument("--player-counts", default="7,10,12", help="Comma-separated player counts.")
    parser.add_argument("--max-days", type=int, default=6)
    parser.add_argument("--output-dir", default=str(ROOT / "docs" / "experiments" / "full_project_real_audit"))
    parser.add_argument("--skip-real-llm", action="store_true")
    parser.add_argument("--real-llm-provider", default=None)
    parser.add_argument(
        "--real-llm-providers", default="", help="Comma-separated provider list; env_default means provider=None."
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    issues: list[dict[str, Any]] = []

    core = validate_core_rules(issues)
    natural_records = run_natural_games(
        parse_csv_ints(args.seeds), parse_csv_ints(args.player_counts), args.max_days, issues
    )
    controlled_records = evaluate_controlled_cases(issues)

    all_records = natural_records + controlled_records
    states = [record["state"] for record in all_records]
    reports = [record["report"] for record in all_records]
    track_c = validate_track_c(reports, issues)
    db = db_health(issues)
    llm = {"skipped": True}
    if not args.skip_real_llm:
        if args.real_llm_providers.strip():
            providers: list[str | None] = []
            for item in args.real_llm_providers.split(","):
                value = item.strip()
                if value:
                    providers.append(None if value == "env_default" else value)
            llm = real_llm_matrix(providers or [args.real_llm_provider], issues)
        else:
            llm = real_llm_probe(args.real_llm_provider, issues)

    coverage = {
        "event_counts": _event_type_counts(states),
        "phase_counts": _phase_counts(states),
        "role_counts": _role_counts(states),
        "winner_counts": _winner_counts(states),
        "controlled_cases": [record["case"] for record in controlled_records],
    }
    summary = {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "natural_game_count": len(natural_records),
        "controlled_case_count": len(controlled_records),
        "core": core,
        "coverage": coverage,
        "track_c": track_c["summary"],
        "db_health": db,
        "real_llm": llm,
        "issues": issues,
    }

    compact_records = [
        {
            "kind": record["kind"],
            "case": record.get("case"),
            "seed": record.get("seed"),
            "player_count": record.get("player_count"),
            "state": compact_state(record["state"]),
            "report": compact_report(record["report"]),
        }
        for record in all_records
    ]
    full_records = [
        {
            "kind": record["kind"],
            "case": record.get("case"),
            "seed": record.get("seed"),
            "player_count": record.get("player_count"),
            "state": record["state"].moderator_dict(),
            "metrics": asdict(record["metrics"]),
            "report": record["report"].to_dict(),
        }
        for record in all_records
    ]
    _write_json(output_dir / "audit_summary.json", summary)
    _write_json(output_dir / "records_compact.json", compact_records)
    _write_json(output_dir / "audit_results.json", full_records)
    _write_json(output_dir / "track_c_docs_sample.json", [doc.to_dict() for doc in track_c["docs"][:40]])
    _write_json(output_dir / "track_c_retrieval_samples.json", track_c["retrieval_samples"])
    sample_markdown = "\n\n---\n\n".join(record["markdown"] for record in all_records[:3])
    (output_dir / "sample_review_report.md").write_text(sample_markdown, encoding="utf-8")
    (output_dir / "audit_report.md").write_text(render_audit_markdown(summary), encoding="utf-8")

    print(
        json.dumps(
            {"output_dir": str(output_dir), "issue_count": len(issues), "summary": summary},
            ensure_ascii=False,
            default=_json_default,
        )
    )
    return 1 if any(issue["severity"] == ISSUE_CRITICAL for issue in issues) else 0


if __name__ == "__main__":
    raise SystemExit(main())
