from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.agents.llm_agent import LLMAgent
from backend.engine.game import WerewolfGame
from backend.engine.rules import build_players
from backend.engine.visibility import Visibility


def main() -> int:
    players = build_players(seed=7)
    agents = {player.id: LLMAgent(player.id, seed=7 + player.seat, provider="fake") for player in players}
    agent = agents[players[0].id]
    game = WerewolfGame(players=players, agents=agents, seed=7)
    game.initialize()
    view = Visibility().for_player(game.state, players[0].id)
    agent.update(view, "TALK")
    talk = agent.talk()
    print("talk_action=", talk.action_type.value)
    print("talk_has_speech=", bool(talk.speech))
    print("talk_source=", talk.metadata.get("source"))
    print("talk_model=", talk.metadata.get("model"))
    agent.update(view, "VOTE")
    vote = agent.vote()
    print("vote_action=", vote.action_type.value)
    print("vote_has_target=", bool(vote.target_id))
    print("vote_source=", vote.metadata.get("source"))
    print("vote_model=", vote.metadata.get("model"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
