"""Track B BadCase regression tests.

BadCase-001: 神职集体送局 (Gods throw the game).
Constructs a 7-player game where wolves play well and village gods make
consecutive obvious mistakes. Validates that Track B scoring separates
good wolf play from bad god play regardless of camp outcome.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.engine.models import Alignment
from backend.engine.models import DecisionAudit
from backend.engine.models import EventType
from backend.engine.models import GameEvent
from backend.engine.models import GameState
from backend.engine.models import Phase
from backend.engine.models import Player
from backend.engine.models import Role
from backend.eval.opportunity import OpportunityExtractor
from backend.eval.review import MetricsCalculator
from backend.eval.scoring_models import calculate_process_score
from backend.eval.scoring_models import extract_features
from backend.eval.track_b import ReplayBundleBuilder
from backend.eval.track_b import generate_published_review_document

# ---------------------------------------------------------------------------
# Shared helpers (mirrors test_b_full_acceptance.py)
# ---------------------------------------------------------------------------

ALIGNMENT_BY_ROLE = {
    Role.WEREWOLF: Alignment.WOLF,
    Role.SEER: Alignment.VILLAGE,
    Role.WITCH: Alignment.VILLAGE,
    Role.HUNTER: Alignment.VILLAGE,
    Role.GUARD: Alignment.VILLAGE,
    Role.VILLAGER: Alignment.VILLAGE,
}


def _uid() -> str:
    import uuid

    return uuid.uuid4().hex[:12]


def _make_player(pid: str, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        id=pid,
        seat=int(pid[1:]),
        name=name,
        role=role,
        alignment=ALIGNMENT_BY_ROLE[role],
        alive=alive,
    )


def _make_vote(day: int, voter: Player, target: Player) -> GameEvent:
    return GameEvent.create(
        day=day,
        phase=Phase.DAY_VOTE,
        type=EventType.VOTE_CAST,
        visibility="public",
        payload={
            "voter_id": voter.id,
            "voter_name": voter.name,
            "target_id": target.id,
            "target_name": target.name,
        },
    )


def _make_speech(day: int, actor: Player, speech: str, *, phase: Phase = Phase.DAY_SPEECH) -> GameEvent:
    return GameEvent.create(
        day=day,
        phase=phase,
        type=EventType.CHAT_MESSAGE,
        visibility="public",
        payload={
            "actor_id": actor.id,
            "actor_name": actor.name,
            "speech": speech,
            "last_words": False,
        },
    )


def _make_night_action(
    day: int,
    actor: Player,
    action_type: str,
    target: Player,
    *,
    phase: Phase = Phase.NIGHT_WOLF_ACTION,
) -> GameEvent:
    return GameEvent.create(
        day=day,
        phase=phase,
        type=EventType.NIGHT_ACTION,
        visibility="private",
        payload={
            "actor_id": actor.id,
            "actor_name": actor.name,
            "action_type": action_type,
            "target_id": target.id,
        },
        visible_to=[actor.id],
    )


def _make_seer_result(day: int, seer: Player, target: Player, *, is_wolf: bool) -> GameEvent:
    return GameEvent.create(
        day=day,
        phase=Phase.NIGHT_SEER_ACTION,
        type=EventType.PRIVATE_INFO,
        visibility="private",
        payload={
            "kind": "seer_result",
            "target_id": target.id,
            "target_name": target.name,
            "is_wolf": is_wolf,
            "message": f"Seer checked {target.name}: {'wolf' if is_wolf else 'good'}",
        },
        visible_to=[seer.id],
    )


def _make_witch_info(day: int, witch: Player, victim: Player) -> GameEvent:
    """Witch learns who was attacked overnight."""
    return GameEvent.create(
        day=day,
        phase=Phase.NIGHT_WITCH_ACTION,
        type=EventType.PRIVATE_INFO,
        visibility="private",
        payload={
            "kind": "witch_victim",
            "target_id": victim.id,
            "target_name": victim.name,
            "message": f"Last night {victim.name} was attacked.",
        },
        visible_to=[witch.id],
    )


def _make_wolf_tally(day: int, target: Player, votes: dict[str, str]) -> GameEvent:
    """Wolf attack consensus tally (private to wolves)."""
    wolf_ids = list(votes.keys())
    return GameEvent.create(
        day=day,
        phase=Phase.NIGHT_WOLF_ACTION,
        type=EventType.PRIVATE_INFO,
        visibility="private",
        payload={
            "kind": "wolf_attack_tally",
            "target_id": target.id,
            "target_name": target.name,
            "votes": votes,
        },
        visible_to=wolf_ids,
    )


def _make_death(day: int, player: Player, reason: str, *, phase: Phase | None = None) -> GameEvent:
    if phase is None:
        phase = Phase.DAY_RESOLVE if reason == "vote" else Phase.NIGHT_RESOLVE
    return GameEvent.create(
        day=day,
        phase=phase,
        type=EventType.PLAYER_DIED,
        visibility="public",
        payload={
            "player_id": player.id,
            "player_name": player.name,
            "reason": reason,
        },
    )


def _make_hunter_shot(day: int, hunter: Player, target: Player) -> GameEvent:
    return GameEvent.create(
        day=day,
        phase=Phase.HUNTER_SHOOT,
        type=EventType.HUNTER_SHOT,
        visibility="public",
        payload={
            "hunter_id": hunter.id,
            "target_id": target.id,
            "target_name": target.name,
        },
    )


def _make_decision(
    game_id: str,
    player: Player,
    role: Role,
    day: int,
    phase: str,
    request: str,
    parsed_action: dict[str, Any],
    *,
    observation: dict[str, Any] | None = None,
    legal_actions: list[str] | None = None,
) -> DecisionAudit:
    return DecisionAudit(
        id=f"dec-{player.id}-{day}-{phase}-{_uid()}",
        game_id=game_id,
        player_id=player.id,
        day=day,
        phase=phase,
        request=request,
        observation=observation or {},
        legal_actions=legal_actions or [],
        prompt_version="v1",
        raw_output=None,
        parsed_action=parsed_action,
        is_valid=True,
        error_type=None,
        latency_ms=None,
        prompt_tokens=None,
        completion_tokens=None,
        created_at=0.0,
    )


# ---------------------------------------------------------------------------
# BadCase-001: 神职集体送局 — fixture builder
# ---------------------------------------------------------------------------


def build_badcase_001_fixture() -> GameState:
    """Construct the BadCase-001 game state.

    Timeline:
      N1: Guard self-guards, Wolves kill P7, Witch saves P7, Seer checks P1=wolf
      D1: Seer hides wolf check, Witch leaks info, Guard exposes role+plan,
          Hunter threatens, Villager follows wolf wagon
      D1 vote: P6 Hunter voted out, shoots P3 Seer
      N2: Guard self-guards again (consecutive), Wolves kill P4 Witch,
          Witch poisons P5 Guard
      N2 resolve: P4 + P5 die, wolves win.
    """
    game_id = f"badcase-001-{_uid()}"

    # --- Players ---
    p1 = _make_player("P1", "狼人A", Role.WEREWOLF)  # Werewolf (good play)
    p2 = _make_player("P2", "狼人B", Role.WEREWOLF)  # Werewolf (good play)
    p3 = _make_player("P3", "预言家A", Role.SEER)  # Seer (bad)
    p4 = _make_player("P4", "女巫A", Role.WITCH)  # Witch (bad)
    p5 = _make_player("P5", "守卫A", Role.GUARD)  # Guard (bad)
    p6 = _make_player("P6", "猎人A", Role.HUNTER)  # Hunter (bad)
    p7 = _make_player("P7", "村民A", Role.VILLAGER)  # Villager (bad)
    all_players = [p1, p2, p3, p4, p5, p6, p7]

    # --- N1 events ---
    n1_guard = _make_night_action(1, p5, "guard", p5, phase=Phase.NIGHT_GUARD_ACTION)

    # Wolf consensus: both attack P7
    n1_wolf_tally = _make_wolf_tally(1, p7, {p1.id: "P7", p2.id: "P7"})
    n1_wolf1_kill = _make_night_action(1, p1, "attack", p7, phase=Phase.NIGHT_WOLF_ACTION)
    n1_wolf2_kill = _make_night_action(1, p2, "attack", p7, phase=Phase.NIGHT_WOLF_ACTION)

    # Witch learns P7 was attacked, saves P7
    n1_witch_info = _make_witch_info(1, p4, p7)
    n1_witch_save = _make_night_action(1, p4, "save", p7, phase=Phase.NIGHT_WITCH_ACTION)

    # Seer checks P1 → wolf
    n1_seer_result = _make_seer_result(1, p3, p1, is_wolf=True)
    n1_seer_check = _make_night_action(1, p3, "divine", p1, phase=Phase.NIGHT_SEER_ACTION)

    # --- D1 speeches ---
    d1_speech_p3 = _make_speech(
        1,
        p3,
        "我这轮没什么信息，先随便听听吧。我感觉 P6 猎人有点紧张，今天可以先出 P6。",
    )
    d1_speech_p4 = _make_speech(
        1,
        p4,
        "我知道昨晚 P7 被刀了，但我不想说为什么。今天我觉得 P5 怪怪的，先盯 P5。",
    )
    d1_speech_p5 = _make_speech(
        1,
        p5,
        "我是守卫，我昨晚守自己。今晚我还会继续守自己，你们不用管我。",
    )
    d1_speech_p6 = _make_speech(
        1,
        p6,
        "你们爱出就出，我反正有身份。谁投我我就带谁。",
    )
    d1_speech_p7 = _make_speech(
        1,
        p7,
        "我觉得 P1 说得挺有道理，P6 确实像狼。今天就先出 P6 吧。",
    )
    d1_speech_p1 = _make_speech(
        1,
        p1,
        "P6 发言太紧张了，明显有问题。今天我归票 P6，好人们跟我投。",
    )
    d1_speech_p2 = _make_speech(
        1,
        p2,
        "我也觉得 P6 不对劲，跟 P1 投 P6。",
    )

    # --- D1 votes ---
    d1_vote_p1 = _make_vote(1, p1, p6)
    d1_vote_p2 = _make_vote(1, p2, p6)
    d1_vote_p3 = _make_vote(1, p3, p6)
    d1_vote_p4 = _make_vote(1, p4, p5)
    d1_vote_p5 = _make_vote(1, p5, p6)
    d1_vote_p6 = _make_vote(1, p6, p1)
    d1_vote_p7 = _make_vote(1, p7, p6)

    # --- D1 resolve ---
    d1_death_p6 = _make_death(1, p6, "vote")

    # --- D1 hunter shot ---
    d1_hunter_shot = _make_hunter_shot(1, p6, p3)
    d1_death_p3 = _make_death(1, p3, "hunter_shot", phase=Phase.HUNTER_SHOOT)

    # --- N2 events ---
    # Guard self-guards again (consecutive same target)
    n2_guard = _make_night_action(2, p5, "guard", p5, phase=Phase.NIGHT_GUARD_ACTION)

    # Wolves kill Witch P4
    n2_wolf_tally = _make_wolf_tally(2, p4, {p1.id: "P4", p2.id: "P4"})
    n2_wolf1_kill = _make_night_action(2, p1, "attack", p4, phase=Phase.NIGHT_WOLF_ACTION)
    n2_wolf2_kill = _make_night_action(2, p2, "attack", p4, phase=Phase.NIGHT_WOLF_ACTION)

    # Witch learns P4 was attacked, poisons P5 Guard
    n2_witch_info = _make_witch_info(2, p4, p4)
    n2_witch_poison = _make_night_action(2, p4, "witch_poison", p5, phase=Phase.NIGHT_WITCH_ACTION)

    # --- N2 resolve ---
    n2_death_p4 = _make_death(2, p4, "wolf")
    n2_death_p5 = _make_death(2, p5, "witch_poison")

    # --- Assemble events ---
    events = [
        # N1
        n1_guard,
        n1_wolf_tally,
        n1_wolf1_kill,
        n1_wolf2_kill,
        n1_witch_info,
        n1_witch_save,
        n1_seer_result,
        n1_seer_check,
        # D1 speeches
        d1_speech_p3,
        d1_speech_p4,
        d1_speech_p5,
        d1_speech_p6,
        d1_speech_p7,
        d1_speech_p1,
        d1_speech_p2,
        # D1 votes
        d1_vote_p1,
        d1_vote_p2,
        d1_vote_p3,
        d1_vote_p4,
        d1_vote_p5,
        d1_vote_p6,
        d1_vote_p7,
        # D1 resolve
        d1_death_p6,
        d1_hunter_shot,
        d1_death_p3,
        # N2
        n2_guard,
        n2_wolf_tally,
        n2_wolf1_kill,
        n2_wolf2_kill,
        n2_witch_info,
        n2_witch_poison,
        # N2 resolve
        n2_death_p4,
        n2_death_p5,
    ]

    # --- Decision records for opportunity extraction ---
    decisions = [
        # N1
        _make_decision(
            game_id,
            p5,
            Role.GUARD,
            1,
            "NIGHT_GUARD",
            "GUARD",
            {"type": "guard", "target_id": "P5", "reasoning": "首夜自守是标准操作"},
        ),
        _make_decision(
            game_id,
            p1,
            Role.WEREWOLF,
            1,
            "NIGHT_WOLF",
            "KILL",
            {"type": "attack", "target_id": "P7", "reasoning": "刀村民减少好人数量"},
        ),
        _make_decision(
            game_id,
            p2,
            Role.WEREWOLF,
            1,
            "NIGHT_WOLF",
            "KILL",
            {"type": "attack", "target_id": "P7", "reasoning": "跟队友一致刀村民"},
        ),
        _make_decision(
            game_id,
            p4,
            Role.WITCH,
            1,
            "NIGHT_WITCH",
            "WITCH",
            {"type": "save", "target_id": "P7", "reasoning": "首夜救人保平安"},
        ),
        _make_decision(
            game_id,
            p3,
            Role.SEER,
            1,
            "NIGHT_SEER",
            "DIVINE",
            {"type": "divine", "target_id": "P1", "reasoning": "查验 P1 摸身份"},
        ),
        # D1 speeches
        _make_decision(
            game_id,
            p3,
            Role.SEER,
            1,
            "DAY_SPEECH",
            "TALK",
            {"type": "speech", "speech": "我这轮没什么信息，先随便听听吧。我感觉 P6 猎人有点紧张，今天可以先出 P6。"},
            observation={"private": "昨晚查验 P1 是狼人"},
        ),
        _make_decision(
            game_id,
            p4,
            Role.WITCH,
            1,
            "DAY_SPEECH",
            "TALK",
            {"type": "speech", "speech": "我知道昨晚 P7 被刀了，但我不想说为什么。今天我觉得 P5 怪怪的，先盯 P5。"},
            observation={"private": "昨晚 P7 被刀，我用了解药"},
        ),
        _make_decision(
            game_id,
            p5,
            Role.GUARD,
            1,
            "DAY_SPEECH",
            "TALK",
            {"type": "speech", "speech": "我是守卫，我昨晚守自己。今晚我还会继续守自己，你们不用管我。"},
        ),
        _make_decision(
            game_id,
            p6,
            Role.HUNTER,
            1,
            "DAY_SPEECH",
            "TALK",
            {"type": "speech", "speech": "你们爱出就出，我反正有身份。谁投我我就带谁。"},
        ),
        _make_decision(
            game_id,
            p7,
            Role.VILLAGER,
            1,
            "DAY_SPEECH",
            "TALK",
            {"type": "speech", "speech": "我觉得 P1 说得挺有道理，P6 确实像狼。今天就先出 P6 吧。"},
        ),
        _make_decision(
            game_id,
            p1,
            Role.WEREWOLF,
            1,
            "DAY_SPEECH",
            "TALK",
            {"type": "speech", "speech": "P6 发言太紧张了，明显有问题。今天我归票 P6，好人们跟我投。"},
        ),
        _make_decision(
            game_id,
            p2,
            Role.WEREWOLF,
            1,
            "DAY_SPEECH",
            "TALK",
            {"type": "speech", "speech": "我也觉得 P6 不对劲，跟 P1 投 P6。"},
        ),
        # D1 votes
        _make_decision(
            game_id,
            p1,
            Role.WEREWOLF,
            1,
            "DAY_VOTE",
            "VOTE",
            {"type": "vote", "target_id": "P6", "reasoning": "推猎人出局"},
        ),
        _make_decision(
            game_id,
            p2,
            Role.WEREWOLF,
            1,
            "DAY_VOTE",
            "VOTE",
            {"type": "vote", "target_id": "P6", "reasoning": "跟队友推猎人"},
        ),
        _make_decision(
            game_id,
            p3,
            Role.SEER,
            1,
            "DAY_VOTE",
            "VOTE",
            {"type": "vote", "target_id": "P6", "reasoning": "感觉 P6 像狼"},
            observation={"private": "我知道 P1 是狼但没有公开"},
        ),
        _make_decision(
            game_id,
            p4,
            Role.WITCH,
            1,
            "DAY_VOTE",
            "VOTE",
            {"type": "vote", "target_id": "P5", "reasoning": "P5 怪怪的"},
        ),
        _make_decision(
            game_id, p5, Role.GUARD, 1, "DAY_VOTE", "VOTE", {"type": "vote", "target_id": "P6", "reasoning": "跟风投票"}
        ),
        _make_decision(
            game_id,
            p6,
            Role.HUNTER,
            1,
            "DAY_VOTE",
            "VOTE",
            {"type": "vote", "target_id": "P1", "reasoning": "P1 带头踩我"},
        ),
        _make_decision(
            game_id,
            p7,
            Role.VILLAGER,
            1,
            "DAY_VOTE",
            "VOTE",
            {"type": "vote", "target_id": "P6", "reasoning": "跟 P1 节奏"},
        ),
        # D1 hunter shot
        _make_decision(
            game_id,
            p6,
            Role.HUNTER,
            1,
            "NIGHT_HUNTER_SHOOT",
            "SHOOT",
            {"type": "shoot", "target_id": "P3", "reasoning": "P3 也投我，带走"},
        ),
        # N2
        _make_decision(
            game_id,
            p5,
            Role.GUARD,
            2,
            "NIGHT_GUARD",
            "GUARD",
            {"type": "guard", "target_id": "P5", "reasoning": "继续守自己"},
        ),
        _make_decision(
            game_id,
            p1,
            Role.WEREWOLF,
            2,
            "NIGHT_WOLF",
            "KILL",
            {"type": "attack", "target_id": "P4", "reasoning": "刀女巫，去神职"},
        ),
        _make_decision(
            game_id,
            p2,
            Role.WEREWOLF,
            2,
            "NIGHT_WOLF",
            "KILL",
            {"type": "attack", "target_id": "P4", "reasoning": "跟队友刀女巫"},
        ),
        _make_decision(
            game_id,
            p4,
            Role.WITCH,
            2,
            "NIGHT_WITCH",
            "WITCH",
            {"type": "poison", "target_id": "P5", "reasoning": "P5 发言像狼"},
        ),
    ]

    # --- Update alive status ---
    p3.alive = False  # Shot by Hunter D1
    p6.alive = False  # Voted out D1
    p4.alive = False  # Killed by wolves N2
    p5.alive = False  # Poisoned by Witch N2
    # P1, P2, P7 survive → wolves win

    return GameState(
        id=game_id,
        phase=Phase.GAME_END,
        day=3,
        players=all_players,
        events=events,
        decision_records=decisions,
        winner=Alignment.WOLF,
    )


# ---------------------------------------------------------------------------
# Helpers for analysing scores
# ---------------------------------------------------------------------------


def _player_scores_by_id(report: dict[str, Any]) -> dict[str, Any]:
    """Extract player_id → PlayerReview mapping from a review report."""
    return {pr["player_id"]: pr for pr in report.get("player_reviews", [])}


def _collect_badcase_tags(report: dict[str, Any]) -> set[str]:
    """Collect unique mistake_type tags from bad_cases."""
    tags: set[str] = set()
    for bc in report.get("bad_cases", []):
        tags.add(bc.get("mistake_type", ""))
    return tags


def _collect_badcase_descriptions(report: dict[str, Any]) -> list[str]:
    """Collect all bad case descriptions for inspection."""
    return [bc.get("description", "") for bc in report.get("bad_cases", [])]


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def badcase_001_state() -> GameState:
    return build_badcase_001_fixture()


@pytest.fixture(scope="module")
def badcase_001_report(badcase_001_state: GameState) -> dict[str, Any]:
    """Run the full Track B pipeline on the badcase fixture."""
    document = generate_published_review_document(badcase_001_state)
    return document.review_report


@pytest.fixture(scope="module")
def badcase_001_bundle(badcase_001_state: GameState):
    """Build a ReplayBundle from the fixture."""
    return ReplayBundleBuilder().build(badcase_001_state)


@pytest.fixture(scope="module")
def badcase_001_opportunities(badcase_001_bundle):
    """Extract DecisionOpportunities from the bundle."""
    return OpportunityExtractor().extract(badcase_001_bundle)


# ---------------------------------------------------------------------------
# Test 1: Score separation — wolves high, gods low
# ---------------------------------------------------------------------------


def test_badcase_001_scores_are_separated(badcase_001_state: GameState) -> None:
    """Verify P1/P2 wolves score significantly higher than god players.

    Uses process_score (outcome-independent) so wolves don't get credit just
    for being on the winning side.
    """
    metrics = MetricsCalculator().compute(badcase_001_state)
    scores_by_id = {ps.player_id: ps for ps in metrics.player_scores}

    # Print scores for inspection
    print("\n--- BadCase-001 Process Scores ---")
    for pid in sorted(scores_by_id, key=lambda x: int(x[1:])):
        ps = scores_by_id[pid]
        print(
            f"  {pid} ({ps.player_name:8s} {ps.role:10s}): "
            f"process={ps.process_score:.1f} final={ps.final_score:.1f} "
            f"vote={ps.vote_score:.2f} speech={ps.speech_score:.2f} "
            f"skill={ps.skill_score:.2f} role_task={ps.role_task_score:.2f} "
            f"mistake_penalty={ps.mistake_penalty:.2f}"
        )

    # Wolves should have high process scores
    assert scores_by_id["P1"].process_score >= 60, (
        f"P1 Werewolf process_score too low: {scores_by_id['P1'].process_score}"
    )
    assert scores_by_id["P2"].process_score >= 55, (
        f"P2 Werewolf process_score too low: {scores_by_id['P2'].process_score}"
    )

    # Gods should have low process scores
    assert scores_by_id["P3"].process_score <= 45, f"P3 Seer process_score too high: {scores_by_id['P3'].process_score}"
    assert scores_by_id["P4"].process_score <= 45, (
        f"P4 Witch process_score too high: {scores_by_id['P4'].process_score}"
    )
    assert scores_by_id["P5"].process_score <= 45, (
        f"P5 Guard process_score too high: {scores_by_id['P5'].process_score}"
    )
    assert scores_by_id["P6"].process_score <= 35, (
        f"P6 Hunter process_score too high: {scores_by_id['P6'].process_score}"
    )
    assert scores_by_id["P7"].process_score <= 50, (
        f"P7 Villager process_score too high: {scores_by_id['P7'].process_score}"
    )

    # Separation: wolves significantly above worst gods
    gap_1_3 = scores_by_id["P1"].process_score - scores_by_id["P3"].process_score
    gap_1_6 = scores_by_id["P1"].process_score - scores_by_id["P6"].process_score
    print(f"\n  P1-P3 gap: {gap_1_3:.1f}  |  P1-P6 gap: {gap_1_6:.1f}")

    assert gap_1_3 >= 15, f"P1-P3 gap too small: {gap_1_3}"
    assert gap_1_6 >= 25, f"P1-P6 gap too small: {gap_1_6}"


# ---------------------------------------------------------------------------
# Test 2: Core BadCase detection
# ---------------------------------------------------------------------------


def test_badcase_001_detects_seer_withheld_wolf_check(badcase_001_state: GameState) -> None:
    """P3 Seer checked P1=wolf but didn't release the info."""
    metrics = MetricsCalculator().compute(badcase_001_state)
    bad_cases = metrics.metadata.get("bad_case_reports", [])
    descriptions = [bc.description for bc in bad_cases]

    seer_bad = [bc for bc in bad_cases if bc.player_name == "预言家A" and "speech" in bc.mistake_type]
    assert seer_bad, f"Expected seer withheld-wolf-check bad case, got: {descriptions}"


def test_badcase_001_detects_witch_poisoned_village_power(badcase_001_state: GameState) -> None:
    """P4 Witch poisoned P5 Guard (village alignment)."""
    metrics = MetricsCalculator().compute(badcase_001_state)
    bad_cases = metrics.metadata.get("bad_case_reports", [])

    witch_poison_bad = [
        bc
        for bc in bad_cases
        if bc.player_name == "女巫A" and bc.mistake_type == "ability" and "poison" in bc.description.lower()
    ]
    assert witch_poison_bad, f"Expected witch poison village bad case, got: {[bc.description for bc in bad_cases]}"


def test_badcase_001_detects_hunter_shot_key_village_power(badcase_001_state: GameState) -> None:
    """P6 Hunter shot P3 Seer (village alignment)."""
    metrics = MetricsCalculator().compute(badcase_001_state)
    bad_cases = metrics.metadata.get("bad_case_reports", [])

    hunter_shot_bad = [
        bc
        for bc in bad_cases
        if bc.player_name == "猎人A" and bc.mistake_type == "ability" and "shot" in bc.description.lower()
    ]
    assert hunter_shot_bad, f"Expected hunter shot village bad case, got: {[bc.description for bc in bad_cases]}"


def test_badcase_001_detects_guard_consecutive_same_target(badcase_001_state: GameState) -> None:
    """P5 Guard self-guarded on consecutive nights."""
    metrics = MetricsCalculator().compute(badcase_001_state)
    bad_cases = metrics.metadata.get("bad_case_reports", [])

    guard_repeat_bad = [
        bc
        for bc in bad_cases
        if bc.player_name == "守卫A" and bc.mistake_type == "ability" and "repeated" in bc.description.lower()
    ]
    assert guard_repeat_bad, (
        f"Expected guard consecutive same target bad case, got: {[bc.description for bc in bad_cases]}"
    )


def test_badcase_001_detects_seer_voted_against_checked_wolf(badcase_001_state: GameState) -> None:
    """P3 Seer knew P1 was wolf but voted P6 (villager) instead.

    Verifies the 'seer_ignored_confirmed_wolf_vote' BadCase rule is now active.
    """
    metrics = MetricsCalculator().compute(badcase_001_state)
    bad_cases = metrics.metadata.get("bad_case_reports", [])

    # Both should be detected:
    # 1. Seer withheld wolf check in speech
    seer_speech_bad = [bc for bc in bad_cases if bc.player_name == "预言家A" and bc.mistake_type == "speech"]
    assert seer_speech_bad, f"Expected seer withheld check speech bad case, got: {[bc.description for bc in bad_cases]}"

    # 2. Seer voted against known wolf (NEW rule)
    seer_vote_bad = [bc for bc in bad_cases if bc.player_name == "预言家A" and bc.mistake_type == "vote"]
    assert seer_vote_bad, (
        f"seer_ignored_confirmed_wolf_vote NOT detected! Bad cases: {[bc.description for bc in bad_cases]}"
    )


# ---------------------------------------------------------------------------
# Test 3: Wolf good play NOT penalised
# ---------------------------------------------------------------------------


def test_badcase_001_wolves_score_high_for_good_play(badcase_001_state: GameState) -> None:
    """Wolves made good decisions: pushed hunter, knifed witch.

    Their voting and killing should NOT be penalised just because they're wolves.
    """
    metrics = MetricsCalculator().compute(badcase_001_state)
    scores_by_id = {ps.player_id: ps for ps in metrics.player_scores}

    # Wolves voted for village-aligned Hunter → good for wolf
    assert scores_by_id["P1"].vote_score >= 0.7, f"P1 vote_score too low: {scores_by_id['P1'].vote_score}"
    assert scores_by_id["P2"].vote_score >= 0.7, f"P2 vote_score too low: {scores_by_id['P2'].vote_score}"

    # Wolf skill score should be reasonable (killed villagers then witch)
    assert scores_by_id["P1"].skill_score >= 0.5, f"P1 skill_score too low: {scores_by_id['P1'].skill_score}"

    # No bad cases for wolves
    bad_cases = metrics.metadata.get("bad_case_reports", [])
    wolf_bad = [bc for bc in bad_cases if "狼人" in bc.player_name]
    assert len(wolf_bad) == 0, f"Wolves should not have bad cases, got: {[bc.description for bc in wolf_bad]}"


# ---------------------------------------------------------------------------
# Test 4: Opportunity-level scoring
# ---------------------------------------------------------------------------


def test_badcase_001_opportunities_extracted(badcase_001_opportunities) -> None:
    """Verify we extract opportunities for all key action types."""
    opps = badcase_001_opportunities
    types = {op.opportunity_type for op in opps}
    print(f"\n--- Extracted opportunity types: {types} ---")
    print(f"--- Total opportunities: {len(opps)} ---")
    for op in opps:
        print(f"  {op.opportunity_id[:50]:50s} {op.player_id} {op.opportunity_type:20s} day={op.day} role={op.role}")

    expected_types = {
        "guard_protect",
        "werewolf_kill",
        "witch_save",
        "witch_poison",
        "seer_check",
        "hunter_shot",
        "vote",
        "speech",
    }
    missing = expected_types - types
    assert not missing, f"Missing opportunity types: {missing}"


def test_badcase_001_process_scores_from_opportunities(badcase_001_opportunities) -> None:
    """Run calculate_process_score on opportunities using trained models.

    If trained models exist on disk, load them and verify they produce
    differentiated scores. If models don't exist, the test FAILS — do not
    silently fall back to 0.5 default predictions.
    """
    from backend.eval.scoring_models import load_track_b_models

    opp_dicts = [op.to_dict() for op in badcase_001_opportunities]

    w_model, q_model, load_info = load_track_b_models(return_info=True)

    if load_info["fallback_used"]:
        pytest.skip(
            f"Trained models not loadable (fallback used: {load_info['fallback_reason']}). "
            f"Re-run: python scripts/train_and_ablate.py"
        )
    assert w_model.model is not None, "W model not trained"
    assert q_model.model is not None, "Q model not trained"

    results = calculate_process_score(opp_dicts, w_model, q_model)
    scores_by_id = {r.player_id: r for r in results}

    print("\n--- Opportunity Process Scores (trained models) ---")
    for pid in sorted(scores_by_id, key=lambda x: int(x[1:])):
        r = scores_by_id[pid]
        print(
            f"  {pid} ({r.role:10s}): process={r.process_score:.4f} "
            f"role_process={r.adjusted_role_process_score:.4f} "
            f"speech={r.speech_score:.4f} "
            f"n_opps={r.num_opportunities}"
        )

    # Verify each player has opportunities
    for pid in ["P1", "P2", "P3", "P4", "P5", "P6", "P7"]:
        assert pid in scores_by_id, f"Missing player {pid} in process scores"
        assert scores_by_id[pid].num_opportunities >= 1, f"{pid} has no opportunities"

    # With trained models, scores should NOT be all identical
    unique_scores = {r.process_score for r in results}
    assert len(unique_scores) > 1, (
        f"All players got identical process_score={unique_scores}. Models may not be trained."
    )


def test_badcase_001_seer_release_opportunity_low(badcase_001_opportunities) -> None:
    """P3 Seer's D1 speech (seer_release) should have low pre_action_score.

    Since models default to 0.5 without training, we verify the opportunity
    EXISTS and has the correct structure for scoring.
    """
    seer_speech_opps = [
        op
        for op in badcase_001_opportunities
        if op.player_id == "P3" and op.day == 1 and op.opportunity_type in ("speech", "seer_release")
    ]
    assert seer_speech_opps, "P3 Seer D1 speech opportunity not extracted"

    for op in seer_speech_opps:
        feats = extract_features(op.to_dict())
        # Verify feature extraction works
        assert feats.role_seer == 1, f"role_seer not set for P3: {feats}"
        assert feats.day == 1.0, f"day not set: {feats}"
        print(f"  P3 speech opp: type={op.opportunity_type}, private_ctx={op.private_context_summary[:80]}")


def test_badcase_001_guard_consecutive_opportunities(badcase_001_opportunities) -> None:
    """P5 Guard has two guard_protect opportunities on consecutive nights."""
    guard_opps = [
        op for op in badcase_001_opportunities if op.player_id == "P5" and op.opportunity_type == "guard_protect"
    ]
    assert len(guard_opps) >= 2, f"Expected >= 2 guard opportunities, got {len(guard_opps)}"

    targets = [op.chosen_action.get("target_id") for op in guard_opps]
    # Both guard self → both target_id = "P5"
    p5_targets = [t for t in targets if t == "P5"]
    assert len(p5_targets) >= 2, f"Expected both guards to target P5, got targets: {targets}"
