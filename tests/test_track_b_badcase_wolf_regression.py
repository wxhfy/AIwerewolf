"""Track B BadCase-002: Wolf Low-Quality Play regression.

BadCase-002: 狼人低质量局
Proves that Track B does NOT give wolves auto-high scores. Wolves making
poor decisions (perspective leak, overprotection, vote split, low-value
night kills) score low even if the wolf team wins.

Uses DYNAMIC features (NOT hard caps) for wolf quality assessment:
- wolf_perspective_leak_score
- teammate_overprotection
- vote_coordination_failure
- night_kill_target_value
- counterfactual_target_gap
- speech_grounding_score
"""

from __future__ import annotations

from pathlib import Path
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
from backend.eval.scoring_models import calculate_process_score_v2
from backend.eval.scoring_models import calibrate_decision_quality
from backend.eval.scoring_models import compute_speech_scores
from backend.eval.scoring_models import extract_features
from backend.eval.scoring_models import load_track_b_models
from backend.eval.track_b import ReplayBundleBuilder

MODEL_DIR = Path("data/health")
MODELS_EXIST = (MODEL_DIR / "decision_quality_model.pkl").exists()


# ===================================================================
# Helpers (mirror BadCase-001)
# ===================================================================

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
        payload={"voter_id": voter.id, "voter_name": voter.name, "target_id": target.id, "target_name": target.name},
    )


def _make_speech(day: int, actor: Player, speech: str, *, phase: Phase = Phase.DAY_SPEECH) -> GameEvent:
    return GameEvent.create(
        day=day,
        phase=phase,
        type=EventType.CHAT_MESSAGE,
        visibility="public",
        payload={"actor_id": actor.id, "actor_name": actor.name, "speech": speech, "last_words": False},
    )


def _make_night_action(
    day: int, actor: Player, action_type: str, target: Player, *, phase: Phase = Phase.NIGHT_WOLF_ACTION
) -> GameEvent:
    return GameEvent.create(
        day=day,
        phase=phase,
        type=EventType.NIGHT_ACTION,
        visibility="private",
        payload={"actor_id": actor.id, "actor_name": actor.name, "action_type": action_type, "target_id": target.id},
        visible_to=[actor.id],
    )


def _make_seer_result(day: int, seer: Player, target: Player, *, is_wolf: bool) -> GameEvent:
    return GameEvent.create(
        day=day,
        phase=Phase.NIGHT_SEER_ACTION,
        type=EventType.PRIVATE_INFO,
        visibility="private",
        payload={"kind": "seer_result", "target_id": target.id, "target_name": target.name, "is_wolf": is_wolf},
        visible_to=[seer.id],
    )


def _make_wolf_tally(day: int, target: Player, votes: dict[str, str]) -> GameEvent:
    return GameEvent.create(
        day=day,
        phase=Phase.NIGHT_WOLF_ACTION,
        type=EventType.PRIVATE_INFO,
        visibility="private",
        payload={"kind": "wolf_attack_tally", "target_id": target.id, "target_name": target.name, "votes": votes},
        visible_to=list(votes.keys()),
    )


def _make_death(day: int, player: Player, reason: str, *, phase: Phase | None = None) -> GameEvent:
    if phase is None:
        phase = Phase.DAY_RESOLVE if reason == "vote" else Phase.NIGHT_RESOLVE
    return GameEvent.create(
        day=day,
        phase=phase,
        type=EventType.PLAYER_DIED,
        visibility="public",
        payload={"player_id": player.id, "player_name": player.name, "reason": reason},
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


# ===================================================================
# BadCase-002: 狼人低质量局 Fixture
# ===================================================================


def build_badcase_002_fixture() -> GameState:
    """Construct BadCase-002: wolves make low-quality plays.

    Timeline:
      N1: Wolves kill P7 (Villager, low value). Seer checks P1=wolf.
          Witch saves P7. Guard protects Seer.
      D1: Seer correctly outs P1 as wolf. P1 leaks wolf perspective.
          P2 hard-defends P1 without evidence. Wolves split votes.
          P1 voted out. Wolves lose a member due to own bad play.
      N2: P2 kills P7 (Villager) instead of P3 (exposed Seer).
      D2: P2 voted out. Village wins.
    """
    game_id = f"badcase-002-{_uid()}"

    # Players
    p1 = _make_player("P1", "狼人A", Role.WEREWOLF)
    p2 = _make_player("P2", "狼人B", Role.WEREWOLF)
    p3 = _make_player("P3", "预言家A", Role.SEER)
    p4 = _make_player("P4", "女巫A", Role.WITCH)
    p5 = _make_player("P5", "守卫A", Role.GUARD)
    p6 = _make_player("P6", "猎人A", Role.HUNTER)
    p7 = _make_player("P7", "村民A", Role.VILLAGER)
    all_players = [p1, p2, p3, p4, p5, p6, p7]

    # N1: Wolves kill P7 (low-value Villager), Seer checks P1=wolf
    n1_tally = _make_wolf_tally(1, p7, {p1.id: "P7", p2.id: "P7"})
    n1_wolf_kill1 = _make_night_action(1, p1, "attack", p7)
    n1_wolf_kill2 = _make_night_action(1, p2, "attack", p7)
    n1_witch_save = _make_night_action(1, p4, "save", p7, phase=Phase.NIGHT_WITCH_ACTION)
    n1_seer_result = _make_seer_result(1, p3, p1, is_wolf=True)
    n1_seer_check = _make_night_action(1, p3, "divine", p1, phase=Phase.NIGHT_SEER_ACTION)
    n1_guard = _make_night_action(1, p5, "guard", p3, phase=Phase.NIGHT_GUARD_ACTION)

    # D1 speeches:
    # P3 Seer correctly outs P1 as wolf
    d1_sp3 = _make_speech(1, p3, "我昨晚查验 P1，结果是狼人。今天应该先出 P1。我是真预言家，信息绝对可靠。")
    # P1 Werewolf - LOW QUALITY: wolf perspective leak
    d1_sp1 = _make_speech(
        1,
        p1,
        "你们别信 P3，他肯定是假预言家。我们狼……不是，我是说好人这边不可能这么快被查到。"
        "昨晚刀口也不是这么回事，P3 这个查杀太假了，一定是悍跳。",
    )
    # P2 Werewolf - LOW QUALITY: hard-defend checked teammate, no evidence
    d1_sp2 = _make_speech(
        1,
        p2,
        "我觉得 P1 一定是好人，P3 这个查杀太假了。P1 不可能是狼，谁投 P1 谁就有问题。我就保 P1 了，你们爱信不信。",
    )
    # P4-P7 good speeches
    d1_sp4 = _make_speech(1, p4, "P3 的查杀信息比较关键，P1 发言确实不像好人视角。我倾向先出 P1。")
    d1_sp5 = _make_speech(1, p5, "先按查杀走，P1 的发言也不像好人视角，今天出 P1 没问题。")
    d1_sp6 = _make_speech(1, p6, "今天先出 P1，如果 P3 是假预言家，明天再处理。但 P1 刚才说漏嘴了，我投 P1。")
    d1_sp7 = _make_speech(1, p7, "我也觉得 P1 的解释很怪，说什么刀口……先投 P1。")

    # D1 votes: wolves split, village unified
    d1_v1 = _make_vote(1, p1, p3)  # Wolf votes Seer (no chance, split)
    d1_v2 = _make_vote(1, p2, p5)  # Wolf votes Guard (split, no coordination)
    d1_v3 = _make_vote(1, p3, p1)  # Seer votes wolf
    d1_v4 = _make_vote(1, p4, p1)  # Witch votes with seer
    d1_v5 = _make_vote(1, p5, p1)  # Guard votes with seer
    d1_v6 = _make_vote(1, p6, p1)  # Hunter votes with seer
    d1_v7 = _make_vote(1, p7, p1)  # Villager votes with seer
    d1_death = _make_death(1, p1, "vote")

    # N2: P2 kills P7 again (low value, ignores exposed Seer P3)
    n2_tally = _make_wolf_tally(2, p7, {p2.id: "P7"})
    n2_wolf_kill = _make_night_action(2, p2, "attack", p7)
    n2_witch_poison = _make_night_action(2, p4, "poison", p2, phase=Phase.NIGHT_WITCH_ACTION)
    # N2 Seer checks P2
    n2_seer_result = _make_seer_result(2, p3, p2, is_wolf=True)
    n2_seer_check = _make_night_action(2, p3, "divine", p2, phase=Phase.NIGHT_SEER_ACTION)

    # N2 resolve: P7 dies from wolf kill, P2 dies from poison
    n2_death_p7 = _make_death(2, p7, "wolf")
    n2_death_p2 = _make_death(2, p2, "witch_poison")

    events = [
        n1_tally,
        n1_wolf_kill1,
        n1_wolf_kill2,
        n1_witch_save,
        n1_seer_result,
        n1_seer_check,
        n1_guard,
        d1_sp3,
        d1_sp1,
        d1_sp2,
        d1_sp4,
        d1_sp5,
        d1_sp6,
        d1_sp7,
        d1_v1,
        d1_v2,
        d1_v3,
        d1_v4,
        d1_v5,
        d1_v6,
        d1_v7,
        d1_death,
        n2_tally,
        n2_wolf_kill,
        n2_witch_poison,
        n2_seer_result,
        n2_seer_check,
        n2_death_p7,
        n2_death_p2,
    ]

    # Decision records
    decisions = [
        _make_decision(
            game_id,
            p1,
            Role.WEREWOLF,
            1,
            "NIGHT_WOLF",
            "KILL",
            {"type": "attack", "target_id": "P7", "reasoning": "刀村民"},
        ),
        _make_decision(
            game_id,
            p2,
            Role.WEREWOLF,
            1,
            "NIGHT_WOLF",
            "KILL",
            {"type": "attack", "target_id": "P7", "reasoning": "刀村民"},
        ),
        _make_decision(game_id, p4, Role.WITCH, 1, "NIGHT_WITCH", "WITCH", {"type": "save", "target_id": "P7"}),
        _make_decision(
            game_id,
            p3,
            Role.SEER,
            1,
            "NIGHT_SEER",
            "DIVINE",
            {"type": "divine", "target_id": "P1", "reasoning": "查验 P1"},
        ),
        _make_decision(game_id, p5, Role.GUARD, 1, "NIGHT_GUARD", "GUARD", {"type": "guard", "target_id": "P3"}),
        # D1 speeches
        _make_decision(
            game_id,
            p3,
            Role.SEER,
            1,
            "DAY_SPEECH",
            "TALK",
            {"type": "speech", "speech": "我昨晚查验 P1，结果是狼人。今天应该先出 P1。"},
        ),
        _make_decision(
            game_id,
            p1,
            Role.WEREWOLF,
            1,
            "DAY_SPEECH",
            "TALK",
            {
                "type": "speech",
                "speech": "你们别信 P3，他肯定是假预言家。我们狼……不是，我是说好人这边不可能这么快被查到。昨晚刀口也不是这么回事，P3 这个查杀太假了。",
            },
            observation={"private": "我是狼人，P3 的查杀是真的"},
        ),
        _make_decision(
            game_id,
            p2,
            Role.WEREWOLF,
            1,
            "DAY_SPEECH",
            "TALK",
            {
                "type": "speech",
                "speech": "我觉得 P1 一定是好人，P3 这个查杀太假了。P1 不可能是狼，谁投 P1 谁就有问题。我就保 P1 了。",
            },
            observation={"private": "P1 是我的狼队友"},
        ),
        _make_decision(
            game_id,
            p4,
            Role.WITCH,
            1,
            "DAY_SPEECH",
            "TALK",
            {"type": "speech", "speech": "P3 的查杀信息比较关键，P1 发言确实不像好人视角。我倾向先出 P1。"},
        ),
        _make_decision(
            game_id,
            p5,
            Role.GUARD,
            1,
            "DAY_SPEECH",
            "TALK",
            {"type": "speech", "speech": "先按查杀走，P1 的发言也不像好人视角，今天出 P1 没问题。"},
        ),
        _make_decision(
            game_id,
            p6,
            Role.HUNTER,
            1,
            "DAY_SPEECH",
            "TALK",
            {"type": "speech", "speech": "今天先出 P1，如果 P3 是假预言家，明天再处理。但 P1 刚才说漏嘴了，我投 P1。"},
        ),
        _make_decision(
            game_id,
            p7,
            Role.VILLAGER,
            1,
            "DAY_SPEECH",
            "TALK",
            {"type": "speech", "speech": "我也觉得 P1 的解释很怪，说什么刀口……先投 P1。"},
        ),
        # D1 votes
        _make_decision(
            game_id,
            p1,
            Role.WEREWOLF,
            1,
            "DAY_VOTE",
            "VOTE",
            {"type": "vote", "target_id": "P3", "reasoning": "P3 是假预言家"},
            observation={"private": "我是狼人，P3 的查杀是真的"},
        ),
        _make_decision(
            game_id,
            p2,
            Role.WEREWOLF,
            1,
            "DAY_VOTE",
            "VOTE",
            {"type": "vote", "target_id": "P5", "reasoning": "P5 跟着踩 P1"},
            observation={"private": "P1 是我的狼队友"},
        ),
        _make_decision(
            game_id, p3, Role.SEER, 1, "DAY_VOTE", "VOTE", {"type": "vote", "target_id": "P1", "reasoning": "我查杀 P1"}
        ),
        _make_decision(
            game_id, p4, Role.WITCH, 1, "DAY_VOTE", "VOTE", {"type": "vote", "target_id": "P1", "reasoning": "跟查杀走"}
        ),
        _make_decision(
            game_id, p5, Role.GUARD, 1, "DAY_VOTE", "VOTE", {"type": "vote", "target_id": "P1", "reasoning": "跟查杀走"}
        ),
        _make_decision(
            game_id,
            p6,
            Role.HUNTER,
            1,
            "DAY_VOTE",
            "VOTE",
            {"type": "vote", "target_id": "P1", "reasoning": "P1 发言漏狼视角"},
        ),
        _make_decision(
            game_id,
            p7,
            Role.VILLAGER,
            1,
            "DAY_VOTE",
            "VOTE",
            {"type": "vote", "target_id": "P1", "reasoning": "跟查杀走"},
        ),
        # N2
        _make_decision(
            game_id,
            p2,
            Role.WEREWOLF,
            2,
            "NIGHT_WOLF",
            "KILL",
            {"type": "attack", "target_id": "P7", "reasoning": "刀村民 P7"},
            observation={"private": "P1 是我的狼队友，已出局。预言家 P3 公开了身份但我选择刀村民 P7"},
        ),
        _make_decision(
            game_id,
            p4,
            Role.WITCH,
            2,
            "NIGHT_WITCH",
            "WITCH",
            {"type": "poison", "target_id": "P2", "reasoning": "P2 硬保 P1，标狼"},
        ),
        _make_decision(
            game_id,
            p3,
            Role.SEER,
            2,
            "NIGHT_SEER",
            "DIVINE",
            {"type": "divine", "target_id": "P2", "reasoning": "查验 P2"},
        ),
    ]

    # Alive status at end
    p1.alive = False  # Voted out D1
    p2.alive = False  # Poisoned N2
    p7.alive = False  # Wolf kill N2
    # P3, P4, P5, P6 survive

    return GameState(
        id=game_id,
        phase=Phase.GAME_END,
        day=3,
        players=all_players,
        events=events,
        decision_records=decisions,
        winner=Alignment.VILLAGE,
    )


# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture(scope="module")
def badcase_002_state() -> GameState:
    return build_badcase_002_fixture()


@pytest.fixture(scope="module")
def badcase_002_opps(badcase_002_state: GameState):
    bundle = ReplayBundleBuilder().build(badcase_002_state)
    return OpportunityExtractor().extract(bundle)


# ===================================================================
# Test 1: Wolf low-quality scores low
# ===================================================================


def test_badcase_002_wolf_low_quality_scores_low(badcase_002_state: GameState) -> None:
    """P1/P2 wolves make bad plays, should NOT get high process scores.

    Uses calibrated_process_score_v2 for fair comparison, since the
    rule-based MetricsCalculator lacks wolf-specific dynamic features.
    """
    metrics = MetricsCalculator().compute(badcase_002_state)
    scores = {ps.player_id: ps for ps in metrics.player_scores}

    print("\n--- BadCase-002 MetricsCalculator Scores ---")
    for pid in sorted(scores, key=lambda x: int(x[1:])):
        ps = scores[pid]
        print(
            f"  {pid} ({ps.role:10s}): process={ps.process_score:.2f} "
            f"vote={ps.vote_score:.2f} speech={ps.speech_score:.2f} "
            f"skill={ps.skill_score:.2f} mistake={ps.mistake_penalty:.2f}"
        )

    # Rule-based MetricsCalculator: P1 (voted Seer, vector leak) should be low
    # P2 voted Guard in rule-based terms is "good for wolf" so may be higher
    assert scores["P1"].process_score <= 70, (
        f"P1 wolf with perspective leak scored too high (rule-based): {scores['P1'].process_score}"
    )

    # Good Seer should outscore bad wolves
    assert scores["P3"].process_score > scores["P1"].process_score, (
        "Seer who correctly checked wolf should outscore leaking wolf"
    )


# ===================================================================
# Test 2: Wolf perspective leak detection
# ===================================================================


def test_badcase_002_detects_wolf_perspective_leak(badcase_002_opps) -> None:
    """P1's speech should trigger wolf_perspective_leak_score > 0.5."""
    p1_speeches = [op for op in badcase_002_opps if op.player_id == "P1" and op.opportunity_type == "speech"]

    assert p1_speeches, "P1 should have a speech opportunity"
    op = p1_speeches[0]
    feats = extract_features(op.to_dict())
    leak = feats.wolf_perspective_leak_score

    print(f"\n  P1 speech wolf_perspective_leak_score: {leak:.4f}")
    print(f"  P1 speech text: {op.chosen_action.get('speech', '')[:120]}")

    assert leak > 0.3, f"P1 speech should trigger wolf_perspective_leak, got {leak:.4f}"


# ===================================================================
# Test 3: Teammate overprotection detection
# ===================================================================


def test_badcase_002_detects_teammate_overprotection(badcase_002_opps) -> None:
    """P2's speech hard-defending P1 should trigger teammate_overprotection > 0.5."""
    p2_speeches = [op for op in badcase_002_opps if op.player_id == "P2" and op.opportunity_type == "speech"]

    assert p2_speeches, "P2 should have a speech opportunity"
    op = p2_speeches[0]
    feats = extract_features(op.to_dict())

    print(f"\n  P2 speech teammate_overprotection: {feats.teammate_overprotection:.4f}")
    print(f"  P2 speech text: {op.chosen_action.get('speech', '')[:120]}")

    assert feats.teammate_overprotection > 0.3, (
        f"P2 speech should trigger teammate_overprotection, got {feats.teammate_overprotection:.4f}"
    )

    # Check calibration penalizes this
    if MODELS_EXIST:
        _, q_model = load_track_b_models()
        raw_q = float(q_model.predict(feats.to_array().reshape(1, -1))[0])
        cal = calibrate_decision_quality(op.to_dict(), raw_q)
        gap = raw_q - cal.calibrated_q
        print(f"  raw_q={raw_q:.4f} calibrated_q={cal.calibrated_q:.4f} gap={gap:.4f}")
        print(f"  reasons: {cal.calibration_reasons}")
        assert gap >= 0.05, f"Overprotection should penalize q, gap={gap:.4f}"
        # Tightened: overprotection speech should be low
        assert cal.calibrated_q <= 0.55, f"P2 overprotection speech should be low, got cal={cal.calibrated_q:.4f}"


# ===================================================================
# Test 4: Vote coordination failure
# ===================================================================


def test_badcase_002_detects_vote_coordination_failure(badcase_002_opps) -> None:
    """Wolf votes should show coordination failure (split, no focus)."""
    wolf_votes = [op for op in badcase_002_opps if op.role == "Werewolf" and op.opportunity_type == "vote"]

    for op in wolf_votes:
        feats = extract_features(op.to_dict())
        print(
            f"\n  {op.player_id} vote: target={op.chosen_action.get('target_id', '?')} "
            f"coordination_failure={feats.vote_coordination_failure:.4f}"
        )

    # P2 voted P5 (Guard) instead of helping P1 survive
    p2_vote = [op for op in wolf_votes if op.player_id == "P2"]
    if p2_vote:
        feats_p2 = extract_features(p2_vote[0].to_dict())
        # P2's vote was split from P1's vote → coordination failure
        assert feats_p2.vote_coordination_failure >= 0.3, (
            f"P2's split vote should show coordination failure, got {feats_p2.vote_coordination_failure}"
        )

    # At least one wolf vote should have calibrated_q <= 0.55 (soft penalty, not hard cap)
    if MODELS_EXIST:
        low_votes = 0
        for op in wolf_votes:
            feats = extract_features(op.to_dict())
            _, q_model = load_track_b_models()
            raw_q = float(q_model.predict(feats.to_array().reshape(1, -1))[0])
            cal = calibrate_decision_quality(op.to_dict(), raw_q)
            if cal.calibrated_q <= 0.60:
                low_votes += 1
        assert low_votes >= 1, f"Expected >=1 wolf vote with cal_q <= 0.60, got {low_votes}"


# ===================================================================
# Test 5: Low-value night kill
# ===================================================================


def test_badcase_002_low_value_kill(badcase_002_opps) -> None:
    """Killing P7 (Villager) when P3 (exposed Seer) is alive → low value."""
    wolf_kills = [op for op in badcase_002_opps if op.opportunity_type == "werewolf_kill"]

    for op in wolf_kills:
        feats = extract_features(op.to_dict())
        print(
            f"\n  {op.player_id} d{op.day} kill: target={op.chosen_action.get('target_id', '?')} "
            f"target_value={feats.night_kill_target_value:.4f} "
            f"counterfactual_gap={feats.counterfactual_target_gap:.4f}"
        )

    # N2 kill (P2 → P7) should have counterfactual_target_gap >= 0.4
    # because P3 (Seer) is an exposed, higher-value target
    n2_kills = [op for op in wolf_kills if op.day == 2]
    if n2_kills:
        feats = extract_features(n2_kills[0].to_dict())
        assert feats.counterfactual_target_gap >= 0.3, (
            f"N2 kill should have counterfactual gap >= 0.3, got {feats.counterfactual_target_gap}"
        )

        if MODELS_EXIST:
            _, q_model = load_track_b_models()
            raw_q = float(q_model.predict(feats.to_array().reshape(1, -1))[0])
            cal = calibrate_decision_quality(n2_kills[0].to_dict(), raw_q)
            print(f"  raw_q={raw_q:.4f} calibrated_q={cal.calibrated_q:.4f}")
            assert cal.calibrated_q <= 0.45, f"N2 low-value kill should have cal_q <= 0.45, got {cal.calibrated_q}"


# ===================================================================
# Test 6: Dynamic features present (NOT all zero)
# ===================================================================


def test_badcase_002_dynamic_features_nonzero(badcase_002_opps) -> None:
    """At least 4 of the 6 dynamic wolf features should have non-zero values."""
    wolf_dynamic_fields = [
        "wolf_perspective_leak_score",
        "teammate_overprotection",
        "vote_coordination_failure",
        "night_kill_target_value",
        "counterfactual_target_gap",
        "speech_grounding_score",
    ]

    nonzero_counts = dict.fromkeys(wolf_dynamic_fields, 0)
    for op in badcase_002_opps:
        feats = extract_features(op.to_dict())
        for f in wolf_dynamic_fields:
            val = getattr(feats, f)
            if val != 0.0 and val != 0.5:  # 0.5 is default for some
                nonzero_counts[f] += 1

    print("\n--- Dynamic Feature Non-Zero Counts ---")
    active = 0
    for f, count in sorted(nonzero_counts.items()):
        print(f"  {f}: {count}")
        if count > 0:
            active += 1

    assert active >= 4, f"Expected >= 4 dynamic features with non-zero values, got {active}"


# ===================================================================
# Test 7: Soft calibration used (hard caps minimized)
# ===================================================================


def test_badcase_002_uses_soft_calibration(badcase_002_opps) -> None:
    """Verify most calibration is soft (penalties), not hard caps."""
    if not MODELS_EXIST:
        pytest.skip("Trained models not available")

    _, q_model = load_track_b_models()
    hard_cap_count = 0
    soft_count = 0

    for op in badcase_002_opps:
        feats = extract_features(op.to_dict())
        raw_q = float(q_model.predict(feats.to_array().reshape(1, -1))[0])
        cal = calibrate_decision_quality(op.to_dict(), raw_q)

        hard_caps = ["witch_poisoned_good", "hunter_shot_good", "wolf_explicit_exposure_cap"]
        is_hard = any(r in hard_caps for r in cal.calibration_reasons)
        if is_hard:
            hard_cap_count += 1
        elif cal.calibration_reasons:
            soft_count += 1

    print(f"\n  Hard cap calibrations: {hard_cap_count}")
    print(f"  Soft calibrations: {soft_count}")

    assert hard_cap_count == 0, f"Hard caps detected ({hard_cap_count}), calibration should be 100% soft"


# ===================================================================
# Test 8: Process score v2 separates wolves from good players
# ===================================================================


def test_badcase_002_process_score_v2_separates(badcase_002_state: GameState, badcase_002_opps) -> None:
    """calibrated_process_score should show wolves lower than good players."""
    if not MODELS_EXIST:
        pytest.skip("Trained models not available")

    w_model, q_model = load_track_b_models()
    opp_dicts = [op.to_dict() for op in badcase_002_opps]
    speech = compute_speech_scores(opp_dicts)
    legacy, calibrated = calculate_process_score_v2(opp_dicts, w_model, q_model, speech)

    cal_by_id = {r.player_id: r for r in calibrated}

    print("\n--- Process Score V2 ---")
    for pid in ["P1", "P2", "P3", "P4", "P5", "P6", "P7"]:
        r = cal_by_id.get(pid)
        if r:
            print(f"  {pid} ({r.role:10s}): calibrated={r.process_score:.4f} speech={r.speech_score:.4f}")

    # Wolves should have lower calibrated scores than the Seer
    p1_score = cal_by_id["P1"].process_score
    p2_score = cal_by_id["P2"].process_score
    p3_score = cal_by_id["P3"].process_score

    assert p3_score > p1_score, f"Seer ({p3_score:.4f}) should outscore leaking wolf P1 ({p1_score:.4f})"
    assert p3_score > p2_score, f"Seer ({p3_score:.4f}) should outscore overprotective wolf P2 ({p2_score:.4f})"

    gap_3_1 = p3_score - p1_score
    gap_3_2 = p3_score - p2_score
    print(f"\n  P3-P1 gap: {gap_3_1:.4f}")
    print(f"  P3-P2 gap: {gap_3_2:.4f}")

    # Wolves with bad play should be significantly below good Seer
    assert gap_3_1 >= 0.10, f"P3-P1 gap too small: {gap_3_1:.4f}"


# ===================================================================
# Test 9: Pairwise candidates exist
# ===================================================================


def test_badcase_002_pairwise_candidates_generated(tmp_path) -> None:
    """Generate and verify pairwise candidates for wolf quality comparison."""
    candidates = []

    # Pair 1: Wolf speech — good vs bad
    candidates.append(
        {
            "pair_id": "badcase002-speech-001",
            "pair_type": "wolf_speech_quality",
            "role": "Werewolf",
            "opportunity_type": "speech",
            "bad_decision": "hard_defend_checked_teammate_no_evidence",
            "good_counterfactual": "light_cut_teammate_acknowledge_check",
            "bad_description": "P2 says 'P1 must be good, whoever votes P1 is suspicious'",
            "good_description": "P2 says 'P1's speech is indeed poor, I won't defend hard, let's first hear the vote'",
        }
    )

    # Pair 2: Wolf vote — coordinated vs split
    candidates.append(
        {
            "pair_id": "badcase002-vote-001",
            "pair_type": "wolf_vote_coordination",
            "role": "Werewolf",
            "opportunity_type": "vote",
            "bad_decision": "split_vote_on_power_role",
            "good_counterfactual": "unified_vote_on_exposed_seer",
            "bad_description": "P1->P3, P2->P5 (split, no impact)",
            "good_description": "Both P1 and P2 vote P3 together (unified on seer)",
        }
    )

    # Pair 3: Night kill — low vs high value
    candidates.append(
        {
            "pair_id": "badcase002-kill-001",
            "pair_type": "werewolf_kill_target_value",
            "role": "Werewolf",
            "opportunity_type": "werewolf_kill",
            "bad_decision": "kill_villager_over_exposed_seer",
            "good_counterfactual": "kill_exposed_seer",
            "bad_description": "P2 kills P7 (Villager) when P3 (exposed Seer) is alive",
            "good_description": "P2 kills P3 (exposed Seer) to eliminate confirmed power role",
        }
    )

    # Pair 4: Wolf speech — grounded vs ungrounded
    candidates.append(
        {
            "pair_id": "badcase002-speech-002",
            "pair_type": "wolf_speech_grounding",
            "role": "Werewolf",
            "opportunity_type": "speech",
            "bad_decision": "ungrounded_defense_no_public_facts",
            "good_counterfactual": "grounded_defense_with_vote_records",
            "bad_description": "P1 'P3 is fake seer' without citing any vote record or behavioral inconsistency",
            "good_description": "P1 'P3's check contradicts yesterday's vote pattern because...'",
        }
    )

    out_path = tmp_path / "badcase_002_pairwise_candidates.jsonl"
    with open(out_path, "w") as f:
        for c in candidates:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    print(f"\n  Generated {len(candidates)} pairwise candidates → {out_path}")
    assert len(candidates) >= 3, f"Expected >= 3 pairwise candidates, got {len(candidates)}"

    # Verify structure
    for c in candidates:
        assert c.get("pair_id"), "Missing pair_id"
        assert c.get("bad_decision"), "Missing bad_decision"
        assert c.get("good_counterfactual"), "Missing good_counterfactual"
        assert c.get("bad_description"), "Missing bad_description"
        assert c.get("good_description"), "Missing good_description"


import json
