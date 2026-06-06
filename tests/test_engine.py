import pytest

from backend.engine.game import WerewolfGame
from backend.engine.models import ActionType
from backend.engine.models import Alignment
from backend.engine.models import Decision
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
        return [
            Decision(
                player.id, ActionType.VOTE, target_id="P3", reasoning="not a candidate", metadata={"source": "llm"}
            )
            for player in players
        ]

    game._batch_ask = invalid_batch  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="Invalid LLM decision in BADGE_ELECTION"):
        game._badge_election_phase()

    assert not any(event.payload.get("agent_fallback") for event in game.state.events)


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
