"""Phase H Smoke Test — Single-role real-LLM A/B with small seed count.

Runs baseline (no bias) and candidate (good bias) games for one role
using 5 seeds each, then compares avg adjusted_final_score. Bypasses
TournamentRunner's 20-seed minimum for a quick sanity check before
the full 40-game Phase H A/B.

Usage:
    python scripts/phase_h_smoke.py --role Seer --seeds 1 2 3 4 5
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml

from backend.agents.factory import create_agents
from backend.agents.llm_agent import LLMAgent
from backend.engine.game import WerewolfGame
from backend.engine.rules import build_players
from backend.eval.review import MetricsCalculator

STRATEGY_FILE = ROOT / "configs" / "discrimination_strategies.yaml"
OUTPUT_DIR = ROOT / "data" / "experiment"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_good_bias(role: str) -> dict[str, list[str]]:
    catalog = yaml.safe_load(STRATEGY_FILE.read_text(encoding="utf-8"))
    return (catalog.get(role) or {}).get("good") or {}


def run_one_llm_game(role: str, bias: dict | None, seed: int, strict: bool) -> dict[str, Any]:
    """Play one real LLM game. bias=None = baseline (no strategy injection)."""
    LLMAgent.STRICT_NO_FALLBACK = strict
    per_role_bias = {role: bias} if bias else {}
    agent_config: dict[str, Any] = {"type": "llm", "seed": seed}
    if per_role_bias:
        agent_config["role_models"] = {role: {"strategy_bias": bias}}
    players = build_players(seed=seed)
    agents = create_agents(players, agent_config)
    game = WerewolfGame(
        players=players,
        agents=agents,
        seed=seed,
        strategy_bias_by_role=per_role_bias,
    )
    game.play()
    metric = MetricsCalculator().compute(game.state)
    # Extract target role player scores
    role_scores = []
    for score in metric.player_scores:
        if score.role == role:
            role_scores.append(
                {
                    "final": score.adjusted_final_score
                    if score.adjusted_final_score is not None
                    else score.final_score,
                    "role_task": score.role_task_score,
                    "vote": score.vote_score,
                    "skill": score.skill_score,
                    "mistake": score.mistake_penalty,
                    "process": score.process_score,
                }
            )
    avg_final = sum(s["final"] for s in role_scores) / max(len(role_scores), 1)
    avg_rt = sum(s["role_task"] for s in role_scores) / max(len(role_scores), 1)

    fallback_count = sum(
        1
        for rec in game.state.decision_records
        if bool((rec.parsed_action or {}).get("metadata", {}).get("fallback"))
        or bool((rec.parsed_action or {}).get("agent_fallback"))
    )
    return {
        "seed": seed,
        "winner": game.state.winner.value if game.state.winner else None,
        "avg_final": round(avg_final, 2),
        "avg_role_task": round(avg_rt, 3),
        "fallback": fallback_count,
        "decisions": len(game.state.decision_records),
        "role_scores": role_scores,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--role", required=True)
    ap.add_argument("--seeds", nargs="+", type=int, default=[1, 2, 3, 4, 5])
    ap.add_argument("--strict-fallback", default="true")
    args = ap.parse_args()

    role = args.role
    bias = load_good_bias(role)
    strict = args.strict_fallback.lower() not in {"false", "0", "no", "off"}
    if not bias:
        raise SystemExit(f"No good bias for {role}")

    seeds = list(args.seeds)
    print(f"[{utc_iso()}] Phase H smoke: role={role} seeds={seeds} strict={strict}")

    baseline_results = []
    candidate_results = []

    for i, seed in enumerate(seeds):
        tag = f"baseline seed={seed}"
        print(f"  ({i + 1}/{len(seeds)}) {tag} ▶")
        try:
            r = run_one_llm_game(role, None, seed, strict)
            baseline_results.append(r)
            print(f"    ✓ final={r['avg_final']:.1f} rt={r['avg_role_task']:.2f} winner={r['winner']}")
        except Exception as exc:
            print(f"    ✗ {type(exc).__name__}: {exc}")
            baseline_results.append({"seed": seed, "error": str(exc)})

    for i, seed in enumerate(seeds):
        tag = f"candidate seed={seed}"
        print(f"  ({i + 1}/{len(seeds)}) {tag} ▶")
        try:
            r = run_one_llm_game(role, bias, seed, strict)
            candidate_results.append(r)
            print(f"    ✓ final={r['avg_final']:.1f} rt={r['avg_role_task']:.2f} winner={r['winner']}")
        except Exception as exc:
            print(f"    ✗ {type(exc).__name__}: {exc}")
            candidate_results.append({"seed": seed, "error": str(exc)})

    # Summarize
    from statistics import mean

    b_final = [r["avg_final"] for r in baseline_results if "avg_final" in r]
    c_final = [r["avg_final"] for r in candidate_results if "avg_final" in r]
    b_rt = [r["avg_role_task"] for r in baseline_results if "avg_role_task" in r]
    c_rt = [r["avg_role_task"] for r in candidate_results if "avg_role_task" in r]

    print()
    print("=== Phase H Smoke Results ===")
    avg_b = mean(b_final) if b_final else 0
    avg_c = mean(c_final) if c_final else 0
    delta_pct = (avg_c - avg_b) / avg_b * 100 if avg_b else 0
    print(f"  baseline_final_avg  = {avg_b:.2f} (n={len(b_final)})")
    print(f"  candidate_final_avg = {avg_c:.2f} (n={len(c_final)})")
    print(f"  delta               = {delta_pct:+.1f}%")
    print(f"  baseline_role_task  = {mean(b_rt):.3f}" if b_rt else "")
    print(f"  candidate_role_task = {mean(c_rt):.3f}" if c_rt else "")

    b_fallback = sum(r.get("fallback", 0) for r in baseline_results)
    c_fallback = sum(r.get("fallback", 0) for r in candidate_results)
    print(f"  baseline_fallback   = {b_fallback}")
    print(f"  candidate_fallback  = {c_fallback}")

    ok = delta_pct >= 3.0 and c_fallback == 0
    print(f"  verdict             = {'PROMOTE' if ok else 'ROLLBACK/HOLD'}")

    # Write output
    label = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    payload = {
        "role": role,
        "seeds": seeds,
        "baseline_avg_final": avg_b,
        "candidate_avg_final": avg_c,
        "delta_pct": round(delta_pct, 2),
        "baseline_fallback": b_fallback,
        "candidate_fallback": c_fallback,
        "verdict": "PROMOTE" if ok else "ROLLBACK/HOLD",
        "baseline": baseline_results,
        "candidate": candidate_results,
    }
    out_path = OUTPUT_DIR / f"phase_h_smoke_{role}_{label}.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\nWrote {out_path}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
