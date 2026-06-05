#!/usr/bin/env python3
"""Run 4-tier experiment sequentially (doubao, 7 players, 1 game each).
Usage: python scripts/run_experiment.py
"""
import os, sys, json, time
sys.path.insert(0, '.')
from backend.llm.env import load_env_file
load_env_file()
from backend.engine.game import WerewolfGame

configs = [
    ("baseline",    {"COGNITIVE_ENABLE_ANTI_PATTERNS": "0", "COGNITIVE_ENABLE_TRACK_C": "0"}),
    ("anti_only",   {"COGNITIVE_ENABLE_ANTI_PATTERNS": "1", "COGNITIVE_ENABLE_TRACK_C": "0"}),
    ("trackc_only", {"COGNITIVE_ENABLE_ANTI_PATTERNS": "0", "COGNITIVE_ENABLE_TRACK_C": "1"}),
    ("both",        {"COGNITIVE_ENABLE_ANTI_PATTERNS": "1", "COGNITIVE_ENABLE_TRACK_C": "1"}),
]

results = []
for tier, env_vars in configs:
    for k, v in env_vars.items():
        os.environ[k] = v
    
    t0 = time.time()
    print(f"\n{'='*50}")
    print(f"[{tier}] Starting (seed=42, 7 players)...")
    print(f"{'='*50}")
    try:
        game = WerewolfGame(seed=42, player_count=7)
        game.initialize()
        game.play()
        dur = int(time.time() - t0)
        r = {"tier": tier, "winner": game.state.winner, "day": game.state.day, "duration_s": dur}
        results.append(r)
        print(f"[{tier}] DONE! Winner={game.state.winner}, Day={game.state.day}, Duration={dur}s")
    except Exception as e:
        dur = int(time.time() - t0)
        results.append({"tier": tier, "error": str(e)[:300], "duration_s": dur})
        print(f"[{tier}] FAILED ({dur}s): {e}")

print(f"\n{'='*50}")
print("RESULTS")
print(f"{'='*50}")
for r in results:
    tier = r["tier"]
    if "error" in r:
        print(f"  {tier}: FAILED - {r['error'][:100]}")
    else:
        print(f"  {tier}: Winner={r['winner']}, Day={r['day']}, Dur={r['duration_s']}s")

os.makedirs("data/experiment", exist_ok=True)
with open("data/experiment/results.json", "w") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print("\nSaved to data/experiment/results.json")
