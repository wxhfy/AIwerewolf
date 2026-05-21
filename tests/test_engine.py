from backend.engine.game import WerewolfGame
from backend.engine.models import Role
from backend.engine.visibility import Visibility


def test_game_plays_to_winner() -> None:
    game = WerewolfGame(seed=7)
    state = game.play()

    assert state.winner is not None
    assert state.phase.value == "GAME_END"
    assert any(event.type.value == "CHAT_MESSAGE" for event in state.events)
    assert any(event.type.value == "VOTE_CAST" for event in state.events)
    assert any(event.type.value == "GAME_END" for event in state.events)


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
