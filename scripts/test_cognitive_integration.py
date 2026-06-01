"""Integration test: CognitiveAgent full game lifecycle.

Verifies:
  1. Agent creation with LLM provider
  2. initialize() / update() / day_start() protocol
  3. All action methods: talk/vote/attack/divine/guard/witch_act/shoot/boom/transfer_badge
  4. finish() triggers reflection (best-effort, logged)
  5. Complete game playable end-to-end

Usage:
  python scripts/test_cognitive_integration.py
"""

import logging
import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

from backend.llm.env import load_env_file
load_env_file()

from backend.agents.cognitive import create_cognitive_agent, CognitiveAgent
from backend.engine.game import WerewolfGame
from backend.engine.rules import build_players, get_role_configuration

SEED = 42
PLAYER_COUNT = 7


def test_agent_creation():
    """Test: can we create a CognitiveAgent with LLM provider?"""
    print("\n=== Test 1: Agent Creation ===")
    try:
        agent = create_cognitive_agent(
            player_id="test-1",
            role="Seer",
            llm_provider="dsv4flash",
            player_name="TestSeer",
            player_seat=1,
        )
        print(f"  OK: agent={agent.player_name} role={agent.role} id={agent.player_id}")
        print(f"  Profile: persona={agent._profile.persona.mbti if agent._profile.persona else '?'}")
        print(f"  Humanization: speech={agent._humanization.speech_min_segments}-{agent._humanization.speech_max_segments}")
        return True
    except Exception as e:
        print(f"  FAIL: {e}")
        import traceback; traceback.print_exc()
        return False


def test_agent_protocol():
    """Test: does CognitiveAgent implement the full Agent Protocol?"""
    print("\n=== Test 2: Agent Protocol Compliance ===")
    from backend.agents.base import Agent

    # CognitiveAgent should be structurally compatible with Agent Protocol
    methods = [
        "initialize", "update", "day_start",
        "talk", "vote", "attack", "divine", "guard",
        "witch_act", "shoot", "boom", "transfer_badge", "finish",
    ]
    agent_methods = set(dir(CognitiveAgent))

    for method in methods:
        if method in agent_methods:
            print(f"  OK: {method}()")
        else:
            print(f"  MISSING: {method}()")
            return False

    # Check required attributes
    try:
        agent = create_cognitive_agent(
            player_id="p1", role="Villager",
            llm_provider="dsv4flash", player_name="Villager1", player_seat=1,
        )
        assert hasattr(agent, "player_id"), "missing player_id"
        assert hasattr(agent, "role"), "missing role"
        assert hasattr(agent, "memory"), "missing memory"
        print("  OK: required attributes present")
    except Exception as e:
        print(f"  FAIL: {e}")
        return False

    return True


def test_full_game():
    """Test: run a complete game with CognitiveAgents."""
    print(f"\n=== Test 3: Full Game ({PLAYER_COUNT} players) ===")

    roles = get_role_configuration(PLAYER_COUNT)
    players = build_players(roles, seed=SEED)

    # Create cognitive agents for all players
    agents = {}
    for p in players:
        try:
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
        except Exception as e:
            print(f"  FAIL creating agent for {p.name}({p.role.value}): {e}")
            return False

    print(f"  Players:")
    for p in players:
        a = agents[p.id]
        mbti = a._profile.persona.mbti if a._profile.persona else "?"
        print(f"    {p.seat}号 {p.name} ({p.role.value}) [{mbti}] → CognitiveAgent")

    # Run game
    try:
        print(f"\n  Starting game...")
        game = WerewolfGame(players=players, agents=agents, seed=SEED)
        game.play()

        print(f"\n  Game finished!")
        print(f"  Winner: {game.state.winner}")
        print(f"  Days: {game.state.day}")

        # Show agent memory
        for p in players:
            a = agents[p.id]
            mem = a.memory
            print(f"\n  {p.seat}号 {p.name} ({p.role.value}):")
            print(f"    Judgments: {len(mem.judgments)}")
            print(f"    Actions: {len(mem.actions)}")
            print(f"    Survived: {p.alive}")

        return True
    except Exception as e:
        print(f"\n  FAIL: {e}")
        import traceback; traceback.print_exc()
        return False


def test_agent_lifecycle_isolated():
    """Test: verify each agent lifecycle method works in isolation."""
    print("\n=== Test 4: Isolated Lifecycle Test ===")
    from backend.engine.visibility import PlayerView

    try:
        agent = create_cognitive_agent(
            player_id="lifecycle-test",
            role="Werewolf",
            llm_provider="dsv4flash",
            player_name="WolfTest",
            player_seat=3,
        )

        # Build a minimal mock view
        mock_view = type('obj', (object,), {
            'self_player': {'id': 'lifecycle-test', 'name': 'WolfTest', 'seat': 3, 'role': 'Werewolf'},
            'players': [
                {'id': 'lifecycle-test', 'name': 'WolfTest', 'seat': 3, 'alive': True, 'role': 'Werewolf'},
                {'id': 'p2', 'name': 'Alice', 'seat': 1, 'alive': True, 'role': 'Villager'},
                {'id': 'p3', 'name': 'Bob', 'seat': 2, 'alive': True, 'role': 'Seer'},
            ],
            'day': 1,
            'phase': 'DAY_SPEECH',
            'public_events': [
                {'type': 'CHAT_MESSAGE', 'day': 1, 'actor_id': 'p2', 'phase': 'DAY_SPEECH',
                 'payload': {'speech': '我觉得3号发言有问题'}},
            ],
            'private_events': [],
            'game_id': 'test-game',
        })()

        # initialize
        agent.initialize(mock_view, {})
        print("  OK: initialize()")

        # update
        agent.update(mock_view, "day_start")
        print("  OK: update()")

        # day_start
        agent.day_start()
        print("  OK: day_start()")

        # talk — this will call LLM!
        print("  calling talk()...")
        decision = agent.talk()
        print(f"  OK: talk() → action={decision.action_type}, speech_len={len(decision.speech or '')}")
        if decision.speech:
            print(f"  Speech preview: {decision.speech[:150]}...")

        # vote
        print("  calling vote()...")
        decision = agent.vote()
        print(f"  OK: vote() → target={decision.target_id} reasoning={decision.reasoning[:80]}")

        # night actions (for werewolf)
        mock_view_night = type('obj', (object,), {
            'self_player': {'id': 'lifecycle-test', 'name': 'WolfTest', 'seat': 3, 'role': 'Werewolf', 'wolf_team': []},
            'players': mock_view.players,
            'day': 1, 'phase': 'NIGHT_WOLF_ACTION',
            'public_events': [], 'private_events': [],
            'game_id': 'test-game',
        })()
        agent.update(mock_view_night, "wolf_attack")
        decision = agent.attack()
        print(f"  OK: attack() → target={decision.target_id}")

        # finish
        agent.finish("village")
        print("  OK: finish() — reflection attempted")

        return True
    except Exception as e:
        print(f"  FAIL: {e}")
        import traceback; traceback.print_exc()
        return False


if __name__ == "__main__":
    results = []

    # Test 1: Creation
    results.append(("Agent Creation", test_agent_creation()))

    # Test 2: Protocol
    results.append(("Protocol Compliance", test_agent_protocol()))

    # Test 3: Full Game (skip if no API key configured)
    if os.getenv("DOUBAO_API_KEY"):
        results.append(("Full Game", test_full_game()))
    else:
        print("\n=== Test 3: Full Game — SKIPPED (no DOUBAO_API_KEY) ===")

    # Test 4: Isolated Lifecycle
    if os.getenv("DOUBAO_API_KEY"):
        results.append(("Isolated Lifecycle", test_agent_lifecycle_isolated()))
    else:
        print("\n=== Test 4: Isolated Lifecycle — SKIPPED (no DOUBAO_API_KEY) ===")

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    all_pass = True
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        if not passed:
            all_pass = False
        print(f"  {status}: {name}")
    print(f"\n  Overall: {'ALL PASS' if all_pass else 'SOME FAILED'}")
