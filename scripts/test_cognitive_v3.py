"""Test game with Cognitive Agent v3 (StateGraph architecture)."""

import sys, os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.llm.env import load_env_file
load_env_file()

from backend.agents.cognitive.agent_v3 import CognitiveAgentV3
from backend.llm import create_client
from langchain_core.runnables import RunnableLambda

from backend.engine.game import WerewolfGame
from backend.engine.rules import build_players

SEED = 42
players = build_players(seed=SEED)

# Create LLM client
client = create_client()

# Wrap in LangChain Runnable
def llm_invoke(messages):
    class R:
        def __init__(self, c): self.content = c
    lc = [{"role": "user" if m.type == "human" else "system", "content": m.content} for m in messages]
    resp = client.chat_sync(lc, max_tokens=500)
    if isinstance(resp, dict):
        c = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
    else:
        c = str(resp)
    return R(c)

llm = RunnableLambda(llm_invoke)

# Create cognitive agents
agents = {}
for p in players:
    agent = CognitiveAgentV3(
        player_id=p.id,
        role=p.role.value,
        llm=llm,
        player_name=p.name,
        player_seat=p.seat,
    )
    agents[p.id] = agent
    p.is_ai = True
    p.agent_type = "cognitive_v3"

print(f"Players: {len(players)}")
for p in players:
    print(f"  {p.seat}号 {p.name} ({p.role.value}) -> CognitiveAgentV3")

game = WerewolfGame(players=players, agents=agents, seed=SEED)
print("\n=== Starting game (Cognitive Agent v3) ===")
game.play()

print(f"\n=== Results ===")
print(f"Winner: {game.state.winner}")
for p in players:
    a = agents[p.id]
    print(f"  {p.seat}号 {p.name} ({p.role.value}): {len(a.memory.judgments)} judgments, {len(a.memory.actions)} actions")
