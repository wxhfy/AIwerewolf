"""Track B CleanCase-001: Wolf High-Quality Play regression.

Verifies that good wolf play (light cutting of teammate, no perspective leak,
high-value kills, coordinated votes) is NOT penalized by calibration.
"""

from __future__ import annotations

from pathlib import Path

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


def _mp(pid, name, role, alive=True):
    return Player(id=pid, seat=int(pid[1:]), name=name, role=role, alignment=ALIGNMENT_BY_ROLE[role], alive=alive)


def _mv(day, voter, target):
    return GameEvent.create(
        day=day,
        phase=Phase.DAY_VOTE,
        type=EventType.VOTE_CAST,
        visibility="public",
        payload={"voter_id": voter.id, "voter_name": voter.name, "target_id": target.id, "target_name": target.name},
    )


def _ms(day, actor, speech, phase=Phase.DAY_SPEECH):
    return GameEvent.create(
        day=day,
        phase=phase,
        type=EventType.CHAT_MESSAGE,
        visibility="public",
        payload={"actor_id": actor.id, "actor_name": actor.name, "speech": speech, "last_words": False},
    )


def _mna(day, actor, atype, target, phase=Phase.NIGHT_WOLF_ACTION):
    return GameEvent.create(
        day=day,
        phase=phase,
        type=EventType.NIGHT_ACTION,
        visibility="private",
        payload={"actor_id": actor.id, "actor_name": actor.name, "action_type": atype, "target_id": target.id},
        visible_to=[actor.id],
    )


def _msr(day, seer, target, is_wolf):
    return GameEvent.create(
        day=day,
        phase=Phase.NIGHT_SEER_ACTION,
        type=EventType.PRIVATE_INFO,
        visibility="private",
        payload={"kind": "seer_result", "target_id": target.id, "target_name": target.name, "is_wolf": is_wolf},
        visible_to=[seer.id],
    )


def _mwt(day, target, votes):
    return GameEvent.create(
        day=day,
        phase=Phase.NIGHT_WOLF_ACTION,
        type=EventType.PRIVATE_INFO,
        visibility="private",
        payload={"kind": "wolf_attack_tally", "target_id": target.id, "target_name": target.name, "votes": votes},
        visible_to=list(votes.keys()),
    )


def _md(day, player, reason, phase=None):
    if phase is None:
        phase = Phase.DAY_RESOLVE if reason == "vote" else Phase.NIGHT_RESOLVE
    return GameEvent.create(
        day=day,
        phase=phase,
        type=EventType.PLAYER_DIED,
        visibility="public",
        payload={"player_id": player.id, "player_name": player.name, "reason": reason},
    )


def _mdec(gid, player, role, day, phase, request, pa, obs=None):
    return DecisionAudit(
        id=f"dec-{player.id}-{day}-{phase}-{_uid()}",
        game_id=gid,
        player_id=player.id,
        day=day,
        phase=phase,
        request=request,
        observation=obs or {},
        legal_actions=[],
        prompt_version="v1",
        raw_output=None,
        parsed_action=pa,
        is_valid=True,
        error_type=None,
        latency_ms=None,
        prompt_tokens=None,
        completion_tokens=None,
        created_at=0.0,
    )


def build_cleancase_001_fixture() -> GameState:
    """CleanCase-001: Wolves play well — light cut of checked teammate, no leaks,
    high-value kills, coordinated votes."""
    gid = f"cleancase-001-{_uid()}"
    p1 = _mp("P1", "狼人A", Role.WEREWOLF)
    p2 = _mp("P2", "狼人B", Role.WEREWOLF)
    p3 = _mp("P3", "预言家A", Role.SEER)
    p4 = _mp("P4", "女巫A", Role.WITCH)
    p5 = _mp("P5", "守卫A", Role.GUARD)
    p6 = _mp("P6", "猎人A", Role.HUNTER)
    p7 = _mp("P7", "村民A", Role.VILLAGER)
    ap = [p1, p2, p3, p4, p5, p6, p7]

    # N1: Wolves target Seer (high-value), Seer checks P1=wolf
    ev = [
        _mwt(1, p3, {p1.id: "P3", p2.id: "P3"}),  # Kill Seer — high value
        _mna(1, p1, "attack", p3),
        _mna(1, p2, "attack", p3),
        _mna(1, p4, "save", p3, phase=Phase.NIGHT_WITCH_ACTION),
        _msr(1, p3, p1, is_wolf=True),
        _mna(1, p3, "divine", p1, phase=Phase.NIGHT_SEER_ACTION),
        _mna(1, p5, "guard", p4, phase=Phase.NIGHT_GUARD_ACTION),
    ]

    # D1: P3 outs P1. P2 makes GOOD wolf play — light cut, no overprotection.
    # P1 defends properly — no wolf perspective, uses public evidence.
    ev += [
        _ms(1, p3, "我昨晚查验 P1，结果是狼人。今天应该先出 P1。我是真预言家。"),
        _ms(
            1,
            p1,
            "P3 跳得很急，但他没有解释为什么昨晚查我。大家可以看我昨天发言和投票，我没有帮任何人带节奏。如果P3是预言家，建议他明天再查一轮确认。",
        ),
        _ms(
            1,
            p2,
            "P1这轮发言确实有压力，我不强保。P3如果是预言家，今天可以先按查杀走；但我会看明天刀口和发言再判断。大家先投票，我倾向跟票。",
        ),
        _ms(1, p4, "跟查杀走，先出 P1。"),
        _ms(1, p5, "P3信息可信，先出 P1。"),
        _ms(1, p6, "先出 P1 没问题。"),
        _ms(1, p7, "跟查杀投票。"),
    ]

    # D1 votes: P2 cuts P1 (good wolf play — sacrifice to reduce risk)
    ev += [
        _mv(1, p1, p3),
        _mv(1, p2, p1),  # P2 votes teammate = smart sacrifice
        _mv(1, p3, p1),
        _mv(1, p4, p1),
        _mv(1, p5, p1),
        _mv(1, p6, p1),
        _mv(1, p7, p1),
        _md(1, p1, "vote"),
    ]

    # N2: P2 kills P4 Witch (high-value target)
    ev += [
        _mwt(2, p4, {p2.id: "P4"}),
        _mna(2, p2, "attack", p4),
        _msr(2, p3, p2, is_wolf=True),
        _mna(2, p3, "divine", p2, phase=Phase.NIGHT_SEER_ACTION),
        _md(2, p4, "wolf"),
    ]

    # Decisions
    decs = [
        _mdec(
            gid,
            p1,
            Role.WEREWOLF,
            1,
            "NIGHT_WOLF",
            "KILL",
            {"type": "attack", "target_id": "P3", "reasoning": "刀预言家"},
        ),
        _mdec(
            gid,
            p2,
            Role.WEREWOLF,
            1,
            "NIGHT_WOLF",
            "KILL",
            {"type": "attack", "target_id": "P3", "reasoning": "刀预言家"},
        ),
        _mdec(gid, p4, Role.WITCH, 1, "NIGHT_WITCH", "WITCH", {"type": "save", "target_id": "P3"}),
        _mdec(gid, p3, Role.SEER, 1, "NIGHT_SEER", "DIVINE", {"type": "divine", "target_id": "P1"}),
        _mdec(gid, p5, Role.GUARD, 1, "NIGHT_GUARD", "GUARD", {"type": "guard", "target_id": "P4"}),
        _mdec(
            gid,
            p3,
            Role.SEER,
            1,
            "DAY_SPEECH",
            "TALK",
            {"type": "speech", "speech": "我昨晚查验 P1，结果是狼人。今天应该先出 P1。"},
        ),
        _mdec(
            gid,
            p1,
            Role.WEREWOLF,
            1,
            "DAY_SPEECH",
            "TALK",
            {
                "type": "speech",
                "speech": "P3跳得很急，但没有解释为什么昨晚查我。大家看我昨天发言和投票，我没有帮任何人带节奏。",
            },
            obs={"private": "我是狼人，P3的查杀正确"},
        ),
        _mdec(
            gid,
            p2,
            Role.WEREWOLF,
            1,
            "DAY_SPEECH",
            "TALK",
            {
                "type": "speech",
                "speech": "P1这轮发言确实有压力，我不强保。P3如果是预言家，今天可以先按查杀走；但我会看明天刀口和发言再判断。",
            },
            obs={"private": "P1是我的狼队友，我需要切割降低连坐风险"},
        ),
        _mdec(gid, p4, Role.WITCH, 1, "DAY_SPEECH", "TALK", {"type": "speech", "speech": "跟查杀走，先出 P1。"}),
        _mdec(gid, p5, Role.GUARD, 1, "DAY_SPEECH", "TALK", {"type": "speech", "speech": "P3信息可信，先出 P1。"}),
        _mdec(gid, p6, Role.HUNTER, 1, "DAY_SPEECH", "TALK", {"type": "speech", "speech": "先出 P1 没问题。"}),
        _mdec(gid, p7, Role.VILLAGER, 1, "DAY_SPEECH", "TALK", {"type": "speech", "speech": "跟查杀投票。"}),
        _mdec(gid, p1, Role.WEREWOLF, 1, "DAY_VOTE", "VOTE", {"type": "vote", "target_id": "P3"}),
        _mdec(
            gid,
            p2,
            Role.WEREWOLF,
            1,
            "DAY_VOTE",
            "VOTE",
            {"type": "vote", "target_id": "P1", "reasoning": "切割队友降低连坐"},
            obs={"private": "P1是我的狼队友，牺牲P1保自己"},
        ),
        _mdec(gid, p3, Role.SEER, 1, "DAY_VOTE", "VOTE", {"type": "vote", "target_id": "P1"}),
        _mdec(gid, p4, Role.WITCH, 1, "DAY_VOTE", "VOTE", {"type": "vote", "target_id": "P1"}),
        _mdec(gid, p5, Role.GUARD, 1, "DAY_VOTE", "VOTE", {"type": "vote", "target_id": "P1"}),
        _mdec(gid, p6, Role.HUNTER, 1, "DAY_VOTE", "VOTE", {"type": "vote", "target_id": "P1"}),
        _mdec(gid, p7, Role.VILLAGER, 1, "DAY_VOTE", "VOTE", {"type": "vote", "target_id": "P1"}),
        _mdec(
            gid,
            p2,
            Role.WEREWOLF,
            2,
            "NIGHT_WOLF",
            "KILL",
            {"type": "attack", "target_id": "P4", "reasoning": "刀女巫——高价值神职"},
            obs={"private": "P1已出局，我要刀女巫P4"},
        ),
        _mdec(gid, p3, Role.SEER, 2, "NIGHT_SEER", "DIVINE", {"type": "divine", "target_id": "P2"}),
    ]

    p1.alive = False  # Voted out D1
    p4.alive = False  # Killed N2
    return GameState(
        id=gid, phase=Phase.GAME_END, day=3, players=ap, events=ev, decision_records=decs, winner=Alignment.VILLAGE
    )


@pytest.fixture(scope="module")
def cleancase_001_state():
    return build_cleancase_001_fixture()


@pytest.fixture(scope="module")
def cleancase_001_opps(cleancase_001_state):
    bundle = ReplayBundleBuilder().build(cleancase_001_state)
    return OpportunityExtractor().extract(bundle)


def test_cleancase_001_good_wolf_speech_not_penalized(cleancase_001_opps) -> None:
    """P2's light-cut speech should NOT trigger overprotection or perspective leak."""
    p2_speeches = [op for op in cleancase_001_opps if op.player_id == "P2" and op.opportunity_type == "speech"]
    assert p2_speeches, "P2 should have a speech"
    op = p2_speeches[0]
    feats = extract_features(op.to_dict())

    print(f"\n  P2 speech leak={feats.wolf_perspective_leak_score:.4f} overprotect={feats.teammate_overprotection:.4f}")

    assert feats.wolf_perspective_leak_score <= 0.2, (
        f"Good wolf speech should have low leak score, got {feats.wolf_perspective_leak_score}"
    )
    assert feats.teammate_overprotection <= 0.2, (
        f"Light cutting should NOT be overprotection, got {feats.teammate_overprotection}"
    )

    if MODELS_EXIST:
        _, q_model = load_track_b_models()
        raw_q = float(q_model.predict(feats.to_array().reshape(1, -1))[0])
        cal = calibrate_decision_quality(op.to_dict(), raw_q)
        print(f"  raw_q={raw_q:.4f} cal={cal.calibrated_q:.4f}")
        assert cal.calibrated_q >= 0.55, f"Good wolf speech should keep high score, got {cal.calibrated_q}"


def test_cleancase_001_high_value_kill_scores_high(cleancase_001_opps) -> None:
    """High-value kills (Seer, Witch) should score high."""
    wolf_kills = [op for op in cleancase_001_opps if op.opportunity_type == "werewolf_kill"]
    for op in wolf_kills:
        feats = extract_features(op.to_dict())
        target = op.chosen_action.get("target_id", "?")
        print(
            f"\n  {op.player_id} d{op.day} kill target={target} "
            f"target_value={feats.night_kill_target_value:.4f} "
            f"gap={feats.counterfactual_target_gap:.4f}"
        )

        # High-value kills: night_kill_target_value should be high
        assert feats.night_kill_target_value >= 0.5, (
            f"Kill on {target} should have high value, got {feats.night_kill_target_value}"
        )

        if MODELS_EXIST:
            _, q_model = load_track_b_models()
            raw_q = float(q_model.predict(feats.to_array().reshape(1, -1))[0])
            cal = calibrate_decision_quality(op.to_dict(), raw_q)
            print(f"  raw_q={raw_q:.4f} cal={cal.calibrated_q:.4f}")
            assert cal.calibrated_q >= 0.55, f"High-value kill should score well, got {cal.calibrated_q}"


def test_cleancase_001_no_wolf_badcase_false_positive(cleancase_001_state) -> None:
    """Good wolf play should NOT trigger wolf-specific BadCase tags."""
    metrics = MetricsCalculator().compute(cleancase_001_state)
    bad_cases = metrics.metadata.get("bad_case_reports", [])

    wolf_bad = [bc for bc in bad_cases if "狼人" in bc.player_name]
    print(f"\n  Wolf bad cases: {len(wolf_bad)}")
    for bc in wolf_bad:
        print(f"  [{bc.severity}] {bc.description}")

    # Wolves may have generic bad cases (voting for wolf), but NOT wolf-specific ones
    wolf_specific = [
        bc for bc in wolf_bad if any(kw in bc.description for kw in ["perspective", "leak", "overprotect", "硬保"])
    ]
    assert len(wolf_specific) == 0, f"Good wolf play should NOT trigger wolf-specific bad cases: {wolf_specific}"


def test_cleancase_001_process_score_high_for_good_wolf(cleancase_001_state, cleancase_001_opps) -> None:
    """Good wolf should have reasonable process score."""
    if not MODELS_EXIST:
        pytest.skip("Models not available")

    w_model, q_model = load_track_b_models()
    opp_dicts = [op.to_dict() for op in cleancase_001_opps]
    speech = compute_speech_scores(opp_dicts)
    _, calibrated = calculate_process_score_v2(opp_dicts, w_model, q_model, speech)

    cal_by_id = {r.player_id: r for r in calibrated}

    print("\n--- CleanCase-001 Process Scores ---")
    for pid in ["P1", "P2", "P3", "P4", "P5", "P6", "P7"]:
        r = cal_by_id.get(pid)
        if r:
            print(f"  {pid} ({r.role:10s}): calibrated={r.process_score:.4f}")

    # P2 (good wolf) should have decent score
    p2_score = cal_by_id["P2"].process_score
    assert p2_score >= 0.55, f"Good wolf P2 should have decent score, got {p2_score:.4f}"


def test_cleancase_001_dynamic_features_low_risk(cleancase_001_opps) -> None:
    """All wolves in CleanCase should have low-risk dynamic feature values."""
    for op in cleancase_001_opps:
        if op.role != "Werewolf":
            continue
        feats = extract_features(op.to_dict())
        # All risk features should be low
        assert feats.wolf_perspective_leak_score <= 0.3, (
            f"{op.player_id} {op.opportunity_type}: leak too high {feats.wolf_perspective_leak_score}"
        )
        assert feats.teammate_overprotection <= 0.3, (
            f"{op.player_id} {op.opportunity_type}: overprotect too high {feats.teammate_overprotection}"
        )
    print("\n  All wolf dynamic features in safe range ✓")
