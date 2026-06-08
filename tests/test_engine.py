import pytest

from backend.engine.game import WerewolfGame
from backend.engine.models import ActionType
from backend.engine.models import Alignment
from backend.engine.models import Decision
from backend.engine.models import EventType
from backend.engine.models import PendingInput
from backend.engine.models import Phase
from backend.engine.models import Player
from backend.engine.models import Role
from backend.engine.visibility import Visibility


def test_game_plays_to_winner() -> None:
    game = WerewolfGame(seed=7)
    state = game.play()

    assert state.winner is not None
    assert state.phase.value == "GAME_END"
    assert len(state.players) == 10
    assert len([player for player in state.players if player.role in (Role.WEREWOLF, Role.WHITE_WOLF_KING)]) == 3
    assert any(event.type.value == "CHAT_MESSAGE" for event in state.events)
    assert any(event.type.value == "VOTE_CAST" for event in state.events)
    assert any(event.type.value == "GAME_END" for event in state.events)
    assert state.daily_summaries
    assert state.daily_summary_facts
    assert any(item for item in state.daily_summaries.values())


def test_multiple_seeds_finish_without_crashing() -> None:
    for seed in range(1, 8):
        state = WerewolfGame(seed=seed).play()
        assert state.winner is not None
        assert state.phase.value == "GAME_END"


def test_badge_and_last_words_phases_are_exercised() -> None:
    state = WerewolfGame(seed=3, player_count=7).play()
    phases = {event.phase for event in state.events}

    assert Phase.DAY_BADGE_SIGNUP in phases
    assert Phase.DAY_BADGE_SPEECH in phases
    assert Phase.DAY_BADGE_ELECTION in phases
    assert Phase.DAY_LAST_WORDS in phases
    assert state.badge.holder_id is not None
    assert state.badge.history
    assert any(event.payload.get("badge_campaign") for event in state.events if event.type.value == "CHAT_MESSAGE")
    assert any(event.payload.get("last_words") for event in state.events if event.type.value == "CHAT_MESSAGE")


def test_visibility_hides_roles_from_villager() -> None:
    game = WerewolfGame(seed=3)
    state = game.state
    game.initialize()
    villager = next(player for player in state.players if player.role == Role.VILLAGER)
    view = Visibility().for_player(state, villager.id)

    for player in view.players:
        if player["id"] == villager.id:
            assert player["role"] == Role.VILLAGER.value
        else:
            assert "role" not in player
            assert "alignment" not in player


def test_werewolf_knows_only_wolves() -> None:
    game = WerewolfGame(seed=5)
    state = game.state
    game.initialize()
    wolf = next(player for player in state.players if player.role == Role.WEREWOLF)
    view = Visibility().for_player(state, wolf.id)

    assert view.known_wolves
    wolf_family = {Role.WEREWOLF.value, Role.WHITE_WOLF_KING.value}
    for player in view.players:
        if player["id"] == wolf.id or player["id"] in {known["id"] for known in view.known_wolves}:
            assert player["role"] in wolf_family
        else:
            assert "role" not in player


def test_werewolf_night_legal_targets_exclude_wolves() -> None:
    players = [
        Player(id="P1", seat=1, name="WolfA", role=Role.WEREWOLF, alignment=Alignment.WOLF),
        Player(id="P2", seat=2, name="WolfB", role=Role.WEREWOLF, alignment=Alignment.WOLF),
        Player(id="P3", seat=3, name="Seer", role=Role.SEER, alignment=Alignment.VILLAGE),
        Player(id="P4", seat=4, name="Villager", role=Role.VILLAGER, alignment=Alignment.VILLAGE),
    ]
    game = WerewolfGame(players=players, agents={p.id: object() for p in players}, seed=13)
    game.state.phase = Phase.NIGHT_WOLF_ACTION

    view = Visibility().for_player(game.state, "P1")

    assert {target["id"] for target in view.legal_targets} == {"P3", "P4"}
    assert all(target["id"] not in {"P1", "P2"} for target in view.legal_targets)


def test_llm_invalid_day_vote_raises_instead_of_fallback() -> None:
    players = [
        Player(id="P1", seat=1, name="A", role=Role.VILLAGER, alignment=Alignment.VILLAGE),
        Player(id="P2", seat=2, name="B", role=Role.WEREWOLF, alignment=Alignment.WOLF),
        Player(id="P3", seat=3, name="C", role=Role.SEER, alignment=Alignment.VILLAGE),
    ]
    game = WerewolfGame(players=players, agents={p.id: object() for p in players}, seed=11)
    game.state.day = 1

    def invalid_batch(players, request, call_fn):
        assert request == "VOTE"
        return [
            Decision(player.id, ActionType.VOTE, target_id=player.id, reasoning="self vote", metadata={"source": "llm"})
            for player in players
        ]

    game._batch_ask = invalid_batch  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="Invalid LLM decision in VOTE"):
        game._vote_phase()

    assert not any(event.payload.get("agent_fallback") for event in game.state.events)


def test_llm_invalid_badge_vote_raises_instead_of_fallback() -> None:
    players = [
        Player(id="P1", seat=1, name="A", role=Role.VILLAGER, alignment=Alignment.VILLAGE),
        Player(id="P2", seat=2, name="B", role=Role.WEREWOLF, alignment=Alignment.WOLF),
        Player(id="P3", seat=3, name="C", role=Role.SEER, alignment=Alignment.VILLAGE),
    ]
    game = WerewolfGame(players=players, agents={p.id: object() for p in players}, seed=12)
    game.state.day = 1
    game.state.badge.candidates = ["P1"]

    def invalid_batch(players, request, call_fn):
        assert request == "BADGE_ELECTION"
        decisions = [
            Decision(
                player.id, ActionType.VOTE, target_id="P3", reasoning="not a candidate", metadata={"source": "llm"}
            )
            for player in players
        ]
        for player, decision in zip(players, decisions):
            view = game.visibility.for_player(game.state, player.id)
            game._record_decision(player, request, view.__dict__, decision)
        return decisions

    game._batch_ask = invalid_batch  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="Invalid LLM decision in BADGE_ELECTION"):
        game._badge_election_phase()

    assert not any(event.payload.get("agent_fallback") for event in game.state.events)
    assert game.state.decision_records
    invalid_records = [record for record in game.state.decision_records if not record.is_valid]
    assert len(invalid_records) == 1
    assert invalid_records[0].player_id == "P2"
    assert invalid_records[0].error_type
    assert "badge candidates" in invalid_records[0].error_type


def test_llm_empty_day_speech_raises_instead_of_skipping() -> None:
    players = [
        Player(id="P1", seat=1, name="A", role=Role.VILLAGER, alignment=Alignment.VILLAGE),
        Player(id="P2", seat=2, name="B", role=Role.WEREWOLF, alignment=Alignment.WOLF),
        Player(id="P3", seat=3, name="C", role=Role.SEER, alignment=Alignment.VILLAGE),
    ]
    game = WerewolfGame(players=players, agents={p.id: object() for p in players}, seed=13)
    game.state.day = 1

    def empty_speech_batch(players, request, call_fn):
        assert request == "TALK"
        return [
            Decision(player.id, ActionType.TALK, speech="", reasoning="empty", metadata={"source": "llm"})
            for player in players
        ]

    game._batch_ask = empty_speech_batch  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="Invalid LLM decision in TALK"):
        game._speech_phase()

    assert not any(event.type.value == "CHAT_MESSAGE" for event in game.state.events)


def test_public_snapshot_hides_specific_night_actions() -> None:
    players = [
        Player(id="G1", seat=1, name="Guard", role=Role.GUARD, alignment=Alignment.VILLAGE),
        Player(id="S1", seat=2, name="Seer", role=Role.SEER, alignment=Alignment.VILLAGE),
        Player(id="W1", seat=3, name="Wolf", role=Role.WEREWOLF, alignment=Alignment.WOLF),
        Player(id="V1", seat=4, name="Villager", role=Role.VILLAGER, alignment=Alignment.VILLAGE),
    ]
    game = WerewolfGame(players=players, agents={p.id: object() for p in players}, seed=7)
    game.state.day = 1

    def scripted_ask(player, request, call, many=False):
        if request == "GUARD":
            return Decision(player.id, ActionType.GUARD, target_id="G1", reasoning="guard self")
        if request == "DIVINE":
            return Decision(player.id, ActionType.DIVINE, target_id="W1", reasoning="check wolf")
        raise AssertionError(request)

    game._ask = scripted_ask  # type: ignore[assignment]
    game._guard_phase()
    game._seer_phase()

    public_night_actions = [
        event
        for event in game.state.public_dict()["events"]
        if event["type"] == "NIGHT_ACTION" and str(event["phase"]).startswith("NIGHT_")
    ]
    private_night_actions = [
        event
        for event in game.state.moderator_dict()["events"]
        if event["type"] == "NIGHT_ACTION" and event["visibility"] == "private"
    ]

    assert public_night_actions
    assert {event["payload"].get("action_type") for event in private_night_actions} >= {"guard", "divine"}
    for event in public_night_actions:
        assert event["payload"] == {"message": "行动完毕", "phase": event["phase"]}
        assert "actor_name" not in event["payload"]
        assert "target" not in event["payload"]
        assert "reasoning" not in event["payload"]


def test_emit_speech_sanitizes_internal_planning_and_preserves_segments() -> None:
    players = [
        Player(id="P1", seat=1, name="A", role=Role.SEER, alignment=Alignment.VILLAGE),
        Player(id="P2", seat=2, name="B", role=Role.WEREWOLF, alignment=Alignment.WOLF),
        Player(id="P3", seat=3, name="C", role=Role.VILLAGER, alignment=Alignment.VILLAGE),
    ]
    game = WerewolfGame(players=players, agents={p.id: object() for p in players}, seed=17)
    game.state.day = 1
    game.state.phase = Phase.DAY_SPEECH
    decision = Decision(
        "P1",
        ActionType.TALK,
        speech="好的，我分析清楚了局势。现在我是唯一跳预言家的，无人对跳。\n\n让我看看投票的详细信息。\n\n我今天先报查验：2号是查杀。大家投票不要分散。",
        metadata={"source": "llm"},
    )

    game._emit_speech(players[0], decision, {})
    speeches = [event.payload["speech"] for event in game.state.events if event.type == EventType.CHAT_MESSAGE]

    assert speeches == ["我今天先报查验：2号是查杀。大家投票不要分散。"]
    assert "分析清楚" not in "\n".join(speeches)
    assert "让我看看" not in "\n".join(speeches)


def test_human_pending_input_options_match_legal_targets() -> None:
    players = [
        Player(id="W1", seat=1, name="WolfOne", role=Role.WEREWOLF, alignment=Alignment.WOLF),
        Player(id="W2", seat=2, name="WolfTwo", role=Role.WHITE_WOLF_KING, alignment=Alignment.WOLF),
        Player(id="G1", seat=3, name="GuardOne", role=Role.GUARD, alignment=Alignment.VILLAGE),
        Player(id="S1", seat=4, name="SeerOne", role=Role.SEER, alignment=Alignment.VILLAGE),
        Player(id="V1", seat=5, name="VillagerOne", role=Role.VILLAGER, alignment=Alignment.VILLAGE),
    ]
    game = WerewolfGame(players=players, seed=12)
    game.state.day = 1
    game.state.badge.candidates = ["G1", "S1"]
    game.state.night_actions.last_guard_target_id = "S1"
    game.state.night_actions.wolf_target_id = "V1"

    badge_pending = game._build_pending_input(game.state.player("V1"), "BADGE_ELECTION")
    assert {option["id"] for option in badge_pending.options} == {"G1", "S1"}

    wolf_pending = game._build_pending_input(game.state.player("W1"), "ATTACK")
    assert {option["id"] for option in wolf_pending.options} == {"G1", "S1", "V1"}

    wolf_vote_pending = game._build_pending_input(game.state.player("W1"), "WOLF_TEAM_VOTE")
    assert wolf_vote_pending.action_type == "night_action"
    assert {option["id"] for option in wolf_vote_pending.options} == {"G1", "S1", "V1"}

    guard_pending = game._build_pending_input(game.state.player("G1"), "GUARD")
    assert "S1" not in {option["id"] for option in guard_pending.options}

    witch = Player(id="C1", seat=6, name="WitchOne", role=Role.WITCH, alignment=Alignment.VILLAGE)
    game.state.players.append(witch)
    witch_pending = game._build_pending_input(witch, "WITCH")
    assert witch_pending.can_skip is True
    assert "V1" not in {option["id"] for option in witch_pending.options}


def test_public_snapshot_redacts_night_pending_input_details() -> None:
    game = WerewolfGame(seed=7, player_count=7)
    game.initialize()
    guard = next(player for player in game.state.players if player.role == Role.GUARD)
    game.state.phase = Phase.NIGHT_GUARD_ACTION
    game.state.pending_input = PendingInput(
        player_id=guard.id,
        player_name=guard.name,
        seat=guard.seat,
        request="GUARD",
        phase=Phase.NIGHT_GUARD_ACTION.value,
        action_type="guard",
        prompt="守卫请选择今晚守护目标",
        options=[{"id": "P1", "seat": 1, "name": "Player 1", "alive": True}],
        can_skip=True,
        placeholder="选择守护目标",
    )

    public_snapshot = game.state.snapshot(show_private=False)
    private_snapshot = game.state.snapshot(show_private=True)

    assert public_snapshot["pending_input"] == {
        "player_id": "",
        "player_name": "夜晚行动",
        "seat": 0,
        "request": "NIGHT_ACTION",
        "phase": Phase.NIGHT_START.value,
        "action_type": "night_action",
        "prompt": "行动完毕",
        "options": [],
        "can_skip": False,
        "placeholder": None,
    }
    assert private_snapshot["pending_input"]["request"] == "GUARD"
    assert private_snapshot["pending_input"]["action_type"] == "guard"
    assert private_snapshot["pending_input"]["options"]


def test_public_snapshot_redacts_night_subphase_events() -> None:
    game = WerewolfGame(seed=7, player_count=7)
    game.initialize()
    game.state.phase = Phase.NIGHT_SEER_ACTION
    game._set_phase(Phase.NIGHT_SEER_ACTION)

    public_snapshot = game.state.snapshot(show_private=False)
    private_snapshot = game.state.snapshot(show_private=True)

    assert public_snapshot["phase"] == Phase.NIGHT_START.value
    assert private_snapshot["phase"] == Phase.NIGHT_SEER_ACTION.value
    assert all(
        event["phase"] in {Phase.NIGHT_START.value, Phase.NIGHT_RESOLVE.value}
        or event["type"] == EventType.NIGHT_ACTION.value
        for event in public_snapshot["events"]
        if event["phase"].startswith("NIGHT_")
    )
    assert all(
        event["payload"].get("phase") in {None, Phase.NIGHT_START.value, Phase.NIGHT_RESOLVE.value}
        or event["type"] == EventType.NIGHT_ACTION.value
        for event in public_snapshot["events"]
        if str(event["payload"].get("phase", "")).startswith("NIGHT_")
    )


def test_public_snapshot_redacts_night_action_payload() -> None:
    game = WerewolfGame(seed=7, player_count=7)
    game.initialize()
    guard = next(player for player in game.state.players if player.role == Role.GUARD)
    target = next(player for player in game.state.players if player.id != guard.id)
    game.state.phase = Phase.NIGHT_GUARD_ACTION
    game._log(
        EventType.NIGHT_ACTION,
        "public",
        {
            "actor_id": guard.id,
            "actor_name": guard.name,
            "action_type": "guard",
            "target_id": target.id,
            "target": target.public_dict(),
            "reasoning": "守护关键神职",
        },
    )

    public_event = game.state.snapshot(show_private=False)["events"][-1]
    private_event = game.state.snapshot(show_private=True)["events"][-1]

    assert public_event["phase"] == Phase.NIGHT_GUARD_ACTION.value
    assert public_event["payload"] == {
        "message": "行动完毕",
        "phase": Phase.NIGHT_GUARD_ACTION.value,
    }
    assert private_event["phase"] == Phase.NIGHT_GUARD_ACTION.value
    assert private_event["payload"]["actor_id"] == guard.id
    assert private_event["payload"]["target_id"] == target.id
    assert private_event["payload"]["reasoning"] == "守护关键神职"


def test_public_snapshot_shows_wolf_completion_without_private_process() -> None:
    game = WerewolfGame(seed=7, player_count=7)
    game.initialize()
    wolves = [player for player in game.state.players if player.alignment == Alignment.WOLF]
    target = next(player for player in game.state.players if player.alignment != Alignment.WOLF)

    game._set_phase(Phase.NIGHT_WOLF_ACTION)
    game._log(
        EventType.PRIVATE_INFO,
        "private",
        {
            "kind": "wolf_attack_vote",
            "actor_id": wolves[0].id,
            "actor_name": wolves[0].name,
            "target_id": target.id,
            "target_name": target.name,
            "reasoning": "focus the seer claim",
        },
        visible_to=[wolf.id for wolf in wolves],
    )
    game._log_night_phase_completed(Phase.NIGHT_WOLF_ACTION)

    public_events = game.state.snapshot(show_private=False)["events"]
    private_events = game.state.snapshot(show_private=True)["events"]

    public_wolf_events = [
        event
        for event in public_events
        if event["type"] == EventType.NIGHT_ACTION.value
        and event["payload"].get("phase") == Phase.NIGHT_WOLF_ACTION.value
    ]
    assert public_wolf_events
    assert public_wolf_events[-1]["payload"] == {
        "message": "行动完毕",
        "phase": Phase.NIGHT_WOLF_ACTION.value,
    }
    assert all(event["type"] != EventType.PRIVATE_INFO.value for event in public_events)
    assert any(
        event["type"] == EventType.PRIVATE_INFO.value and event["payload"].get("kind") == "wolf_attack_vote"
        for event in private_events
    )


def test_day_vote_tie_enters_pk_and_resolves() -> None:
    game = WerewolfGame(seed=7, player_count=7)
    game.initialize()
    game.state.day = 1
    game.state.badge.holder_id = None

    first_target = game.state.players[0].id
    second_target = game.state.players[1].id
    third_target = game.state.players[2].id
    first_round = {
        game.state.players[0].id: second_target,
        game.state.players[1].id: first_target,
        game.state.players[2].id: first_target,
        game.state.players[3].id: second_target,
        game.state.players[4].id: first_target,
        game.state.players[5].id: second_target,
        game.state.players[6].id: third_target,
    }
    pk_round = {
        game.state.players[2].id: first_target,
        game.state.players[3].id: first_target,
        game.state.players[4].id: first_target,
        game.state.players[5].id: first_target,
        game.state.players[6].id: first_target,
    }

    def scripted_ask(player, request, call, many=False):
        if request in {"TALK", "LAST_WORDS"}:
            return Decision(player.id, ActionType.TALK, speech=f"{player.name} speaks", reasoning="scripted")
        if request == "VOTE":
            target = pk_round[player.id] if game.state.pk_targets else first_round[player.id]
            return Decision(player.id, ActionType.VOTE, target_id=target, reasoning="scripted")
        if request == "BOOM":
            return Decision(player.id, ActionType.SKIP, reasoning="scripted")
        if request == "SHOOT":
            return Decision(player.id, ActionType.SKIP, reasoning="no target")
        if request == "BADGE_TRANSFER":
            return Decision(
                player.id, ActionType.BADGE_TRANSFER, target_id=game.state.alive_players[-1].id, reasoning="scripted"
            )
        raise AssertionError(request)

    game._ask = scripted_ask  # type: ignore[assignment]
    game._batch_ask = lambda players, request, call_fn: [scripted_ask(p, request, call_fn) for p in players]  # type: ignore[assignment]
    game._speech_phase()
    game._vote_phase()
    game._day_resolve()

    assert game.state.day_history[1]["executed"]["player_id"] == first_target
    assert any(event.phase == Phase.DAY_PK_SPEECH for event in game.state.events)
    assert any(event.payload.get("pk_speech") for event in game.state.events if event.type.value == "CHAT_MESSAGE")
    assert game.state.vote_history[1]


def test_sheriff_vote_has_weight() -> None:
    game = WerewolfGame(seed=7)
    sheriff_id = game.state.players[0].id
    target_a = game.state.players[1].id
    target_b = game.state.players[2].id
    game.state.badge.holder_id = sheriff_id
    votes = {
        sheriff_id: target_a,
        game.state.players[1].id: target_b,
        game.state.players[2].id: target_b,
        game.state.players[3].id: target_a,
    }
    tally = game._weighted_tally(votes)
    assert tally[target_a] == 2.5
    assert tally[target_b] == 2.0


def test_idiot_reveals_and_loses_vote_rights() -> None:
    players = [
        Player(id="A", seat=1, name="A", role=Role.IDIOT, alignment=Alignment.VILLAGE),
        Player(id="B", seat=2, name="B", role=Role.VILLAGER, alignment=Alignment.VILLAGE),
        Player(id="C", seat=3, name="C", role=Role.WEREWOLF, alignment=Alignment.WOLF),
        Player(id="D", seat=4, name="D", role=Role.SEER, alignment=Alignment.VILLAGE),
    ]
    game = WerewolfGame(players=players, seed=1)
    game.initialize()
    game.state.day = 1
    game.state.votes = {"B": "A", "C": "A", "D": "A"}
    game._day_resolve()
    assert game.state.player("A").alive
    assert game.state.abilities.idiot_revealed is True
    assert game.state.day_history[1]["idiotRevealed"]["player_id"] == "A"
    assert all(player.id != "A" for player in game._eligible_day_voters())


def test_white_wolf_king_boom_interrupts_day_and_kills_target() -> None:
    players = [
        Player(id="W", seat=1, name="W", role=Role.WHITE_WOLF_KING, alignment=Alignment.WOLF),
        Player(id="V1", seat=2, name="V1", role=Role.VILLAGER, alignment=Alignment.VILLAGE),
        Player(id="V2", seat=3, name="V2", role=Role.SEER, alignment=Alignment.VILLAGE),
        Player(id="G", seat=4, name="G", role=Role.GUARD, alignment=Alignment.VILLAGE),
    ]
    game = WerewolfGame(players=players, seed=2)
    game.initialize()
    game.state.day = 1

    def scripted_ask(player, request, call, many=False):
        if request in {"TALK", "LAST_WORDS"}:
            return Decision(player.id, ActionType.TALK, speech=f"{player.name} talks", reasoning="scripted")
        if request == "BOOM":
            return Decision(player.id, ActionType.BOOM, target_id="V2", reasoning="boom now")
        raise AssertionError(request)

    game._ask = scripted_ask  # type: ignore[assignment]
    game._speech_phase()
    assert game.state.phase == Phase.WHITE_WOLF_KING_BOOM
    assert not game.state.player("W").alive
    assert not game.state.player("V2").alive
    assert game.state.day_history[1]["whiteWolfKingBoom"]["target_player_id"] == "V2"


def test_wolf_phase_has_private_discussion_vote_and_tally() -> None:
    players = [
        Player(id="W1", seat=1, name="WolfOne", role=Role.WEREWOLF, alignment=Alignment.WOLF),
        Player(id="W2", seat=2, name="WolfTwo", role=Role.WEREWOLF, alignment=Alignment.WOLF),
        Player(id="V1", seat=3, name="VillagerOne", role=Role.VILLAGER, alignment=Alignment.VILLAGE),
        Player(id="V2", seat=4, name="VillagerTwo", role=Role.SEER, alignment=Alignment.VILLAGE),
        Player(id="V3", seat=5, name="VillagerThree", role=Role.WITCH, alignment=Alignment.VILLAGE),
    ]
    game = WerewolfGame(players=players, seed=3)
    game.initialize()
    game.state.day = 1

    def scripted_ask(player, request, call, many=False):
        assert request == "WOLF_TEAM_VOTE"
        return Decision(player.id, ActionType.ATTACK, target_id="V2", reasoning=f"{player.name} votes V2")

    game._ask = scripted_ask  # type: ignore[assignment]
    game._wolf_phase()

    assert game.state.night_actions.wolf_votes == {"W1": "V2", "W2": "V2"}
    assert game.state.night_actions.wolf_target_id == "V2"

    wolf_events = [
        event for event in game.state.events if event.visibility == "private" and set(event.visible_to) == {"W1", "W2"}
    ]
    kinds = {event.payload.get("kind") for event in wolf_events}
    assert "wolf_chat_start" in kinds
    assert "wolf_discussion_turn" in kinds
    assert "wolf_attack_vote" in kinds
    assert "wolf_attack_tally" in kinds

    villager_view = Visibility().for_player(game.state, "V1")
    assert all(event["payload"].get("kind") not in kinds for event in villager_view.private_events)
    wolf_view = Visibility().for_player(game.state, "W1")
    wolf_private_kinds = {event["payload"].get("kind") for event in wolf_view.private_events}
    assert "wolf_attack_tally" in wolf_private_kinds


def test_actor_sequence_strict_llm_handler_error_is_not_masked_by_nameerror() -> None:
    players = [
        Player(
            id="W1",
            seat=1,
            name="WolfOne",
            role=Role.WEREWOLF,
            alignment=Alignment.WOLF,
            agent_type="llm",
        ),
        Player(id="V1", seat=2, name="VillagerOne", role=Role.VILLAGER, alignment=Alignment.VILLAGE),
    ]
    game = WerewolfGame(players=players, agents={p.id: object() for p in players}, seed=33)
    game.state.phase = Phase.NIGHT_WOLF_ACTION

    def failing_handler(player: Player) -> None:
        raise RuntimeError("remote read timeout")

    with pytest.raises(RuntimeError, match="remote read timeout"):
        game._run_actor_sequence(Phase.NIGHT_WOLF_ACTION, [players[0]], failing_handler)
