"""Generalization variant factory for Track B.

Generates parameterized GameState fixtures with swapped seats, roles,
phrases, kill targets, and vote patterns. Ensures scoring models are
evaluated on generalization, not memorized templates.
"""

from __future__ import annotations

import random
from copy import deepcopy
from typing import Any

from backend.engine.models import (
    Alignment, DecisionAudit, EventType, GameEvent, GameState, Phase, Player, Role,
)

ALIGNMENT_BY_ROLE = {
    Role.WEREWOLF: Alignment.WOLF, Role.SEER: Alignment.VILLAGE,
    Role.WITCH: Alignment.VILLAGE, Role.HUNTER: Alignment.VILLAGE,
    Role.GUARD: Alignment.VILLAGE, Role.VILLAGER: Alignment.VILLAGE,
}

# ===================================================================
# Speech variant templates
# ===================================================================

WOLF_BAD_SPEECHES = {
    "perspective_leak_slip": [
        "我们狼……不是，我是说好人这边不可能这么快被查到。",
        "我们狼……不对我是说村民这边不会这么容易出问题。",
        "说漏嘴了……我们做狼的当然是……不是，我是说如果我是狼。",
        "狼队这边……不是我的意思是好人方。",
    ],
    "night_kill_certainty": [
        "昨晚刀口不是这么回事，你们别乱盘。",
        "昨晚的刀口位置我很清楚，但我不方便多说。",
        "这个刀法显然是盲刀，P3肯定不是狼。",
        "夜里发生的事我比你们清楚，今天别乱踩。",
    ],
    "certainty_about_wolf_action": [
        "狼肯定不会去刀 P3，这个我很确定。",
        "狼队绝对不可能刀那个人，你们想多了。",
        "我现在就能告诉你们狼昨晚干了什么。",
        "夜里行动的判断我比所有人都有数。",
    ],
    "hard_defend_checked_teammate": [
        "PALPHA 一定是好人，谁投 PALPHA 谁就有问题。",
        "我保 PALPHA 了，PALPHA 不可能是狼，你们爱信不信。",
        "PALPHA 肯定干净，查杀 PALPHA 的那个绝对是假的。",
        "我就一句话，PALPHA 铁好人，投 PALPHA 的人明天自己看着办。",
    ],
    "ungrounded_counter_seer": [
        "PBETA 肯定是假预言家，但我现在不想解释太多。",
        "PBETA 的查杀逻辑根本站不住，明眼人都看得出来。",
        "PBETA 跳得这么假还查杀 PALPHA，不是狼是什么？",
        "假预言家 PBETA 的发言漏洞太多了，我懒得一一指出来。",
    ],
    "forced_misdirection": [
        "别看 PALPHA 了，我觉得 PGAMMA 更像狼。",
        "大家别盯着 PALPHA 一个人，看看 PGAMMA 的发言。",
        "PALPHA 的问题先放一边，今天重点关注 PGAMMA。",
        "我不觉得 PALPHA 有问题，反而是 PGAMMA 越看越像狼。",
    ],
    "contradictory_stance": [
        "我不保 PALPHA，但今天谁投 PALPHA 我都觉得有问题。",
        "PALPHA 是不是狼我不确定，但投 PALPHA 的肯定是狼。",
        "我不站 PALPHA 的边，但你们踩 PALPHA 的理由太牵强。",
        "PALPHA 的发言确实不太好，可是也不能因为查杀就直接归票。",
    ],
    "excessive_teammate_binding": [
        "PALPHA 如果是狼那我也认了，但我就是相信他。",
        "如果 PALPHA 是狼，那我也脱不了干系，但我赌他是好人。",
        "我跟 PALPHA 绑定，PALPHA 翻什么牌我都认。",
        "PALPHA 好人我跟到底，PALPHA 是狼我陪你出局。",
    ],
}

WOLF_GOOD_SPEECHES = {
    "light_cut_teammate": [
        "PALPHA 这轮发言确实有压力，我不强保，先按查杀走。",
        "PALPHA 被查杀后解释不够清楚，我不好硬保，先跟票。",
        "虽然我跟 PALPHA 平时合作多，但这轮他的发言我无法力挺。",
        "PALPHA 的查杀我不确定，但今天的票我先跟好人走。",
    ],
    "reasonable_self_defense": [
        "PBETA 查我可以理解，但我希望大家看我的发言记录和投票，没有硬带节奏。",
        "PBETA 如果真是预言家，我愿意配合查验；但我这两轮的发言所有人都看得到。",
        "我接受查验，但我想请好人看看 PBETA 跳的时机和举证逻辑。",
        "PBETA 说我查杀，但请好人看看我投票和发言的一致性。",
    ],
    "deep_water_low_profile": [
        "我没有强信息，先听神职和票型，今天别乱分票。",
        "这一轮信息还不够，我建议大家听归票，别冲动。",
        "我不想误导大家，今天先跟票，有更多信息再发言。",
        "我这边没有额外信息，按照今天已有的查验走就行。",
    ],
    "wolf_on_wolf_busing": [
        "PALPHA 的发言站不住，我不想因为队友感强行保他。",
        "PALPHA 的逻辑确实有问题，我不能因为他跟我熟就帮他圆。",
        "虽然我想相信 PALPHA，但他的发言确实做低了，我无法跟。",
        "PALPHA 的查杀我没法反驳，今天先出他看牌。",
    ],
    "public_fact_attack_good": [
        "PGAMMA 昨天跟票很晚，今天又突然改口，这个行为值得盘。",
        "大家看 PGAMMA 的投票时间线，昨天最后才投，今天又第一个归票。",
        "PGAMMA 这两天的发言对比，昨天的立场和今天完全不同。",
        "从公开投票看，PGAMMA 的行为模式确实很可疑。",
    ],
    "villager_perspective_fake": [
        "我只能基于公开发言判断，目前 PBETA 的逻辑更完整。",
        "作为村民，我看到的是 PBETA 的查杀比 PALPHA 的防守更有说服力。",
        "我这边信息不多，但从投票和发言来看，PBETA 的站得住脚。",
        "纯看公开发言的话，PBETA 更可信，我今天跟 PBETA 走。",
    ],
    "reasonable_wagon": [
        "今天不要散票，先在 PALPHA 和 PGAMMA 里出，我倾向 PGAMMA。",
        "建议今天归票集中，在 PALPHA 和 PGAMMA 中间选，别分散。",
        "今天两个焦点 PALPHA 和 PGAMMA，我倾向于出 PGAMMA。",
        "归票建议：PALPHA 和 PGAMMA 二选一，别把票撒给其他人。",
    ],
    "reduce_wolf_linkage": [
        "我不想因为一个人的身份把另一批人全绑死，先单点看发言。",
        "PALPHA 的事归 PALPHA，别把我也扯进去，我跟 PALPHA 没有任何绑定。",
        "一个人的身份不能代表全组，单独看每人的发言质量。",
        "PALPHA 是不是狼都不影响我的逻辑，我的发言自己站得住。",
    ],
}

# Kill target value table
KILL_TARGET_VALUES = {
    "Seer": 0.95, "Witch": 0.90, "Guard": 0.80,
    "Hunter": 0.70, "Villager": 0.30,
}

# Seat configuration templates
SEAT_CONFIGS = [
    {"W1": "P1", "W2": "P2", "Se": "P3", "Wi": "P4", "Gu": "P5", "Hu": "P6", "Vi": "P7"},
    {"W1": "P4", "W2": "P6", "Se": "P1", "Wi": "P2", "Gu": "P3", "Hu": "P5", "Vi": "P7"},
    {"W1": "P2", "W2": "P7", "Se": "P5", "Wi": "P1", "Gu": "P3", "Hu": "P4", "Vi": "P6"},
    {"W1": "P3", "W2": "P5", "Se": "P6", "Wi": "P1", "Gu": "P2", "Hu": "P4", "Vi": "P7"},
    {"W1": "P1", "W2": "P5", "Se": "P7", "Wi": "P3", "Gu": "P2", "Hu": "P4", "Vi": "P6"},
    {"W1": "P6", "W2": "P7", "Se": "P2", "Wi": "P4", "Gu": "P1", "Hu": "P3", "Vi": "P5"},
]


# ===================================================================
# Fixture factory
# ===================================================================

def _uid():
    import uuid; return uuid.uuid4().hex[:12]


def _mp(pid, name, role, alive=True):
    return Player(id=pid, seat=int(pid[1:]), name=name, role=role,
                  alignment=ALIGNMENT_BY_ROLE[role], alive=alive)


def _mv(day, voter, target):
    return GameEvent.create(day=day, phase=Phase.DAY_VOTE, type=EventType.VOTE_CAST,
        visibility="public", payload={"voter_id": voter.id, "voter_name": voter.name,
                                       "target_id": target.id, "target_name": target.name})


def _ms(day, actor, speech, phase=Phase.DAY_SPEECH):
    return GameEvent.create(day=day, phase=phase, type=EventType.CHAT_MESSAGE,
        visibility="public", payload={"actor_id": actor.id, "actor_name": actor.name,
                                       "speech": speech, "last_words": False})


def _mna(day, actor, atype, target, phase=Phase.NIGHT_WOLF_ACTION):
    return GameEvent.create(day=day, phase=phase, type=EventType.NIGHT_ACTION,
        visibility="private", payload={"actor_id": actor.id, "actor_name": actor.name,
                                        "action_type": atype, "target_id": target.id},
        visible_to=[actor.id])


def _msr(day, seer, target, is_wolf):
    return GameEvent.create(day=day, phase=Phase.NIGHT_SEER_ACTION, type=EventType.PRIVATE_INFO,
        visibility="private", payload={"kind": "seer_result", "target_id": target.id,
                                        "target_name": target.name, "is_wolf": is_wolf},
        visible_to=[seer.id])


def _mwt(day, target, votes):
    return GameEvent.create(day=day, phase=Phase.NIGHT_WOLF_ACTION, type=EventType.PRIVATE_INFO,
        visibility="private", payload={"kind": "wolf_attack_tally", "target_id": target.id,
                                        "target_name": target.name, "votes": votes},
        visible_to=list(votes.keys()))


def _md(day, player, reason, phase=None):
    if phase is None:
        phase = Phase.DAY_RESOLVE if reason == "vote" else Phase.NIGHT_RESOLVE
    return GameEvent.create(day=day, phase=phase, type=EventType.PLAYER_DIED,
        visibility="public", payload={"player_id": player.id, "player_name": player.name,
                                       "reason": reason})


def _mdec(gid, player, role, day, phase, request, pa, obs=None):
    return DecisionAudit(
        id=f"dec-{player.id}-{day}-{phase}-{_uid()}", game_id=gid,
        player_id=player.id, day=day, phase=phase, request=request,
        observation=obs or {}, legal_actions=[], prompt_version="v1",
        raw_output=None, parsed_action=pa, is_valid=True,
        error_type=None, latency_ms=None, prompt_tokens=None,
        completion_tokens=None, created_at=0.0)


def build_variant_fixture(
    *,
    seats: dict[str, str] | None = None,
    wolf_speech_type: str = "hard_defend_checked_teammate",
    wolf_speech_variant: int = 0,
    wolf2_speech_type: str | None = None,
    wolf2_speech_variant: int = 0,
    kill_target_role: str = "Villager",
    vote_pattern: str = "split",
    seer_checks_wolf: bool = True,
    seed: int = 42,
    winner: Alignment = Alignment.VILLAGE,
) -> GameState:
    """Build a parameterized wolf-operation variant fixture.

    Args:
        seats: role→seat mapping dict. Defaults to config 0.
        wolf_speech_type: key into WOLF_BAD_SPEECHES or WOLF_GOOD_SPEECHES.
        wolf_speech_variant: which variant within the type (0-3).
        wolf2_speech_type: P2's speech type (defaults to same as wolf1).
        kill_target_role: role to kill ("Seer", "Witch", "Villager", etc.).
        vote_pattern: "split" or "unified" or "cut_teammate".
        seer_checks_wolf: if True, Seer checks W1 as wolf.
        seed: random seed for reproducibility.
        winner: game winner alignment.
    """
    random.seed(seed)
    gid = f"variant-{_uid()}"
    cfg = seats or SEAT_CONFIGS[0]

    # Build players
    w1_id = cfg["W1"]; w2_id = cfg["W2"]
    se_id = cfg["Se"]; wi_id = cfg["Wi"]
    gu_id = cfg["Gu"]; hu_id = cfg["Hu"]; vi_id = cfg["Vi"]

    w1 = _mp(w1_id, f"狼人{w1_id}", Role.WEREWOLF)
    w2 = _mp(w2_id, f"狼人{w2_id}", Role.WEREWOLF)
    se = _mp(se_id, f"预言家{se_id}", Role.SEER)
    wi = _mp(wi_id, f"女巫{wi_id}", Role.WITCH)
    gu = _mp(gu_id, f"守卫{gu_id}", Role.GUARD)
    hu = _mp(hu_id, f"猎人{hu_id}", Role.HUNTER)
    vi = _mp(vi_id, f"村民{vi_id}", Role.VILLAGER)
    players = [w1, w2, se, wi, gu, hu, vi]
    player_by_role = {"W1": w1, "W2": w2, "Se": se, "Wi": wi, "Gu": gu, "Hu": hu, "Vi": vi}

    # Resolve kill target
    if kill_target_role == "Seer": kill_target = se
    elif kill_target_role == "Witch": kill_target = wi
    elif kill_target_role == "Guard": kill_target = gu
    elif kill_target_role == "Hunter": kill_target = hu
    else: kill_target = vi

    # Resolve speeches
    is_good = wolf_speech_type in WOLF_GOOD_SPEECHES
    templates = WOLF_GOOD_SPEECHES if is_good else WOLF_BAD_SPEECHES
    w1_template = templates.get(wolf_speech_type, list(templates.values())[0])
    w1_text = w1_template[wolf_speech_variant % len(w1_template)]

    if wolf2_speech_type:
        t2 = (WOLF_GOOD_SPEECHES if wolf2_speech_type in WOLF_GOOD_SPEECHES
              else WOLF_BAD_SPEECHES).get(wolf2_speech_type, list(templates.values())[0])
        w2_text = t2[wolf2_speech_variant % len(t2)]
    else:
        w2_text = w1_text

    # Replace placeholders
    w1_text = w1_text.replace("PALPHA", w1_id).replace("PBETA", se_id).replace("PGAMMA", vi_id)
    w2_text = w2_text.replace("PALPHA", w1_id).replace("PBETA", se_id).replace("PGAMMA", vi_id)

    # Seer speech
    se_check_text = f"我昨晚查验 {w1_id}，结果是狼人。今天先出 {w1_id}。" if seer_checks_wolf else f"我查验 {vi_id}，结果是好人。今天先听发言。"

    # Events
    events = [
        _mwt(1, kill_target, {w1.id: kill_target.id, w2.id: kill_target.id}),
        _mna(1, w1, "attack", kill_target),
        _mna(1, w2, "attack", kill_target),
        _mna(1, wi, "save", kill_target, phase=Phase.NIGHT_WITCH_ACTION),
        _msr(1, se, w1, is_wolf=seer_checks_wolf),
        _mna(1, se, "divine", w1, phase=Phase.NIGHT_SEER_ACTION),
        _mna(1, gu, "guard", se, phase=Phase.NIGHT_GUARD_ACTION),
        _ms(1, se, se_check_text),
        _ms(1, w1, w1_text),
        _ms(1, w2, w2_text),
        _ms(1, wi, "跟查杀走，先出 PALPHA。".replace("PALPHA", w1_id)),
        _ms(1, gu, "查杀信息可信，先出 PALPHA。".replace("PALPHA", w1_id)),
        _ms(1, hu, "同意查杀归票。"),
        _ms(1, vi, "跟查杀投票。"),
    ]

    # Votes
    if vote_pattern == "split":
        events += [_mv(1, w1, se), _mv(1, w2, gu)]
    elif vote_pattern == "cut_teammate":
        events += [_mv(1, w1, se), _mv(1, w2, w1)]
    else:  # unified
        events += [_mv(1, w1, se), _mv(1, w2, se)]

    events += [_mv(1, se, w1), _mv(1, wi, w1), _mv(1, gu, w1), _mv(1, hu, w1), _mv(1, vi, w1)]
    events += [_md(1, w1, "vote")]

    # N2: W2 makes another kill — use same kill quality as N1 for consistency
    n2_target_role = kill_target_role if kill_target_role in ("Seer", "Witch") else "Seer"
    n2_target = player_by_role.get(n2_target_role, se)
    events += [
        _mwt(2, n2_target, {w2.id: n2_target.id}),
        _mna(2, w2, "attack", n2_target),
        _msr(2, se, w2, is_wolf=True),
        _mna(2, se, "divine", w2, phase=Phase.NIGHT_SEER_ACTION),
        _md(2, n2_target, "wolf"),
    ]

    # Decisions
    decisions = [
        _mdec(gid, w1, Role.WEREWOLF, 1, "NIGHT_WOLF", "KILL",
              {"type": "attack", "target_id": kill_target.id}),
        _mdec(gid, w2, Role.WEREWOLF, 1, "NIGHT_WOLF", "KILL",
              {"type": "attack", "target_id": kill_target.id}),
        _mdec(gid, wi, Role.WITCH, 1, "NIGHT_WITCH", "WITCH",
              {"type": "save", "target_id": kill_target.id}),
        _mdec(gid, se, Role.SEER, 1, "NIGHT_SEER", "DIVINE",
              {"type": "divine", "target_id": w1.id}),
        _mdec(gid, gu, Role.GUARD, 1, "NIGHT_GUARD", "GUARD",
              {"type": "guard", "target_id": se.id}),
        _mdec(gid, se, Role.SEER, 1, "DAY_SPEECH", "TALK",
              {"type": "speech", "speech": se_check_text}),
        _mdec(gid, w1, Role.WEREWOLF, 1, "DAY_SPEECH", "TALK",
              {"type": "speech", "speech": w1_text},
              obs={"private": f"我是狼人，{w1_id}是我的ID"}),
        _mdec(gid, w2, Role.WEREWOLF, 1, "DAY_SPEECH", "TALK",
              {"type": "speech", "speech": w2_text},
              obs={"private": f"{w1_id}是我的狼队友"}),
        _mdec(gid, wi, Role.WITCH, 1, "DAY_SPEECH", "TALK",
              {"type": "speech", "speech": f"跟查杀走，先出{w1_id}。"}),
        _mdec(gid, gu, Role.GUARD, 1, "DAY_SPEECH", "TALK",
              {"type": "speech", "speech": "查杀信息可信。"}),
        _mdec(gid, hu, Role.HUNTER, 1, "DAY_SPEECH", "TALK",
              {"type": "speech", "speech": "同意归票。"}),
        _mdec(gid, vi, Role.VILLAGER, 1, "DAY_SPEECH", "TALK",
              {"type": "speech", "speech": "跟查杀投票。"}),
        _mdec(gid, w1, Role.WEREWOLF, 1, "DAY_VOTE", "VOTE",
              {"type": "vote", "target_id": se.id},
              obs={"private": f"我是狼人"}),
        _mdec(gid, w2, Role.WEREWOLF, 1, "DAY_VOTE", "VOTE",
              {"type": "vote", "target_id": gu.id if vote_pattern == "split" else w1.id},
              obs={"private": f"{w1.id}是我的狼队友"}),
        _mdec(gid, se, Role.SEER, 1, "DAY_VOTE", "VOTE",
              {"type": "vote", "target_id": w1.id}),
        _mdec(gid, wi, Role.WITCH, 1, "DAY_VOTE", "VOTE",
              {"type": "vote", "target_id": w1.id}),
        _mdec(gid, gu, Role.GUARD, 1, "DAY_VOTE", "VOTE",
              {"type": "vote", "target_id": w1.id}),
        _mdec(gid, hu, Role.HUNTER, 1, "DAY_VOTE", "VOTE",
              {"type": "vote", "target_id": w1.id}),
        _mdec(gid, vi, Role.VILLAGER, 1, "DAY_VOTE", "VOTE",
              {"type": "vote", "target_id": w1.id}),
        _mdec(gid, w2, Role.WEREWOLF, 2, "NIGHT_WOLF", "KILL",
              {"type": "attack", "target_id": n2_target.id},
              obs={"private": f"{w1_id}已出局"}),
        _mdec(gid, se, Role.SEER, 2, "NIGHT_SEER", "DIVINE",
              {"type": "divine", "target_id": w2.id}),
    ]

    w1.alive = False; n2_target.alive = False
    return GameState(id=gid, phase=Phase.GAME_END, day=3,
                     players=players, events=events,
                     decision_records=decisions, winner=winner)


# ===================================================================
# Batch variant generators
# ===================================================================

def generate_bad_speech_variants(n: int = 20) -> list[tuple[str, GameState]]:
    """Generate N bad-speech variant fixtures across different templates and seats."""
    variants = []
    bad_types = list(WOLF_BAD_SPEECHES.keys())
    for i in range(n):
        stype = bad_types[i % len(bad_types)]
        cfg = SEAT_CONFIGS[i % len(SEAT_CONFIGS)]
        variant_idx = (i // len(bad_types)) % 4
        state = build_variant_fixture(
            seats=cfg, wolf_speech_type=stype,
            wolf_speech_variant=variant_idx,
            kill_target_role="Villager",
            vote_pattern="split" if i % 3 == 0 else "cut_teammate",
            seed=42 + i,
        )
        source = f"bad_speech_{stype}"
        variants.append((source, state))
    return variants


def generate_good_speech_variants(n: int = 20) -> list[tuple[str, GameState]]:
    """Generate N good-speech variant fixtures."""
    variants = []
    good_types = list(WOLF_GOOD_SPEECHES.keys())
    for i in range(n):
        stype = good_types[i % len(good_types)]
        cfg = SEAT_CONFIGS[i % len(SEAT_CONFIGS)]
        variant_idx = (i // len(good_types)) % 4
        state = build_variant_fixture(
            seats=cfg, wolf_speech_type=stype,
            wolf_speech_variant=variant_idx,
            kill_target_role="Seer",
            vote_pattern="unified",
            seed=100 + i,
        )
        source = f"good_speech_{stype}"
        variants.append((source, state))
    return variants


def generate_seat_swap_variants() -> list[tuple[str, GameState]]:
    """Generate one bad + one good variant per seat config."""
    variants = []
    for i, cfg in enumerate(SEAT_CONFIGS):
        bad = build_variant_fixture(
            seats=cfg, wolf_speech_type="perspective_leak_slip",
            wolf_speech_variant=i, kill_target_role="Villager",
            vote_pattern="split", seed=200 + i,
        )
        good = build_variant_fixture(
            seats=cfg, wolf_speech_type="light_cut_teammate",
            wolf_speech_variant=i, kill_target_role="Seer",
            vote_pattern="unified", seed=300 + i,
        )
        variants.append((f"seat_swap_bad_{i}", bad))
        variants.append((f"seat_swap_good_{i}", good))
    return variants


def generate_phrase_swap_variants() -> list[tuple[str, GameState]]:
    """Generate variants using different phrase types, all expressing wolf perspective leak."""
    variants = []
    leak_types = ["perspective_leak_slip", "night_kill_certainty",
                  "certainty_about_wolf_action", "forced_misdirection",
                  "contradictory_stance"]
    for i, stype in enumerate(leak_types):
        for v in range(min(2, len(WOLF_BAD_SPEECHES.get(stype, [""])))):
            state = build_variant_fixture(
                seats=SEAT_CONFIGS[0],
                wolf_speech_type=stype,
                wolf_speech_variant=v,
                kill_target_role="Villager",
                vote_pattern="split",
                seed=400 + i * 10 + v,
            )
            variants.append((f"phrase_swap_{stype}_v{v}", state))
    return variants


def generate_kill_target_variants() -> list[tuple[str, GameState]]:
    """Generate variants with different kill targets."""
    variants = []
    for i, (role, _value) in enumerate(KILL_TARGET_VALUES.items()):
        state = build_variant_fixture(
            seats=SEAT_CONFIGS[i % len(SEAT_CONFIGS)],
            wolf_speech_type="light_cut_teammate",
            kill_target_role=role,
            vote_pattern="unified",
            seed=500 + i,
        )
        variants.append((f"kill_target_{role}", state))
    return variants
