from backend.engine.game import WerewolfGame
from backend.engine.models import Phase, Role
from backend.engine.visibility import Visibility


def test_game_plays_to_winner() -> None:
    game = WerewolfGame(seed=7)
    state = game.play()

    assert state.winner is not None
    assert state.phase.value == "GAME_END"
    assert len(state.players) == 7
    assert len([player for player in state.players if player.role == Role.WEREWOLF]) == 2
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
    state = WerewolfGame(seed=7).play()
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
    for player in view.players:
        if player["id"] == wolf.id:
            assert player["role"] == Role.WEREWOLF.value
        elif player["id"] in {known["id"] for known in view.known_wolves}:
            assert player["role"] == Role.WEREWOLF.value
        else:
            assert "role" not in player
