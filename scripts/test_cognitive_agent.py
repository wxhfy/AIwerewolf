"""Test game with Cognitive Agent (Observe-Think-Act)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.llm.env import load_env_file

load_env_file()

from backend.agents.cognitive import create_cognitive_agent
from backend.engine.game import WerewolfGame
from backend.engine.rules import build_players

SEED = 42
players = build_players(seed=SEED)

# Create cognitive agents for all players
agents = {}
for p in players:
    agent = create_cognitive_agent(
        player_id=p.id,
        role=p.role.value,
        llm_provider="dsv4flash",
        player_name=p.name,
        player_seat=p.seat,
    )
    agents[p.id] = agent
    p.is_ai = True
    p.agent_type = "cognitive"

print(f"Players: {len(players)}")
for p in players:
    a = agents[p.id]
    print(f"  {p.seat}号 {p.name} ({p.role.value}) -> CognitiveAgent")

game = WerewolfGame(players=players, agents=agents, seed=SEED)
print("\n=== Starting game (Cognitive Agent) ===")
game.play()

print("\n=== Results ===")
print(f"Winner: {game.state.winner}")

# Show agent memory
for p in players:
    a = agents[p.id]
    mem = a.memory
    print(f"\n{p.seat}号 {p.name} ({p.role.value}):")
    print(f"  Judgments: {len(mem.judgments)}")
    print(f"  Actions: {len(mem.actions)}")
    if mem.judgments:
        for j in mem.judgments[-3:]:
            print(f"    {j.target}: {j.judgment} ({j.confidence:.0%}) - {j.reasoning[:50]}")
