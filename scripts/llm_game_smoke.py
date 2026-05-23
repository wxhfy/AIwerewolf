from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.agents.factory import create_agents
from backend.engine.game import WerewolfGame
from backend.engine.models import EventType
from backend.engine.rules import build_players


def main() -> int:
    seed = 9
    players = build_players(seed=seed)
    agents = create_agents(players, {"type": "llm", "seed": seed})
    game = WerewolfGame(players=players, agents=agents, seed=seed)
    state = game.play()

    talk_events = [event for event in state.events if event.type == EventType.CHAT_MESSAGE]
    vote_events = [event for event in state.events if event.type == EventType.VOTE_CAST]
    llm_talks = [event for event in talk_events if event.payload.get("agent_source") == "llm"]
    llm_votes = [event for event in vote_events if event.payload.get("agent_source") == "llm"]

    print("winner=", state.winner.value if state.winner else None)
    print("day=", state.day)
    print("talk_events=", len(talk_events))
    print("vote_events=", len(vote_events))
    print("llm_talk_events=", len(llm_talks))
    print("llm_vote_events=", len(llm_votes))
    print("fallback_talk_events=", sum(1 for event in talk_events if event.payload.get("agent_fallback")))
    print("fallback_vote_events=", sum(1 for event in vote_events if event.payload.get("agent_fallback")))

    if not talk_events or not vote_events:
        raise RuntimeError("LLM game smoke did not produce talks and votes")
    if not llm_talks:
        raise RuntimeError("No talk events came from llm source")
    if not llm_votes:
        raise RuntimeError("No vote events came from llm source")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
