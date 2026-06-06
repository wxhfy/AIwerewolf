"""Debug: run a single game and track fallback stats."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.llm.env import load_env_file

load_env_file()

from backend.agents.factory import create_agents
from backend.engine.game import WerewolfGame
from backend.engine.rules import build_players

SEED = 42
players = build_players(seed=SEED)
agents = create_agents(players, {"type": "llm", "seed": SEED})

print(f"Players: {len(players)}")
for p in players:
    a = agents[p.id]
    print(f"  {p.id} ({p.role.value}) -> {type(a).__name__}")

game = WerewolfGame(players=players, agents=agents, seed=SEED)
print("\n=== Starting game ===")
game.play()

# Count fallbacks
fallback_count = 0
llm_count = 0
for event in game.state.public_events:
    fb = event.get("agent_fallback", False)
    if fb:
        fallback_count += 1
    else:
        llm_count += 1

private_fb = 0
private_llm = 0
for event in game.state.private_events:
    fb = event.get("agent_fallback", False)
    if fb:
        private_fb += 1
    else:
        private_llm += 1

print("\n=== Results ===")
print(f"Public events:  LLM={llm_count}, Fallback={fallback_count}")
print(f"Private events: LLM={private_llm}, Fallback={private_fb}")
print(f"Winner: {game.state.winner}")

# Show agent errors
for p in players:
    a = agents[p.id]
    if hasattr(a, "last_error") and a.last_error:
        print(f"  {p.id} error: {a.last_error}")
