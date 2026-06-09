"""Phase H — Real-LLM A/B Validation of Track C Evolution.

Given a target role and the *good* strategy_bias from
``configs/discrimination_strategies.yaml``, run a real-LLM 20-seed A/B
tournament where:

  * baseline = no strategy bias (default agent prompts)
  * candidate = LLMAgents for the target role receive the *good* bias

This bypasses TournamentRunner's heuristic ``_patch_perturbation`` stub by
injecting a custom ``game_runner`` so the only thing that can move scores
is the LLM actually playing differently with the new policy.

AcceptancePolicy then decides PROMOTE / ROLLBACK using the same hard
conditions as Phase F: candidate_fallback_count = 0, info_leak = 0,
invalid_action_rate = 0 + at least one improvement condition ≥ +3%.

Usage:
    python scripts/c_real_llm_ab_validation.py --role Seer --seeds 1 2 3 4 5
    python scripts/c_real_llm_ab_validation.py --role Seer  # default 20 seeds
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.agents.factory import create_agents
from backend.agents.llm_agent import LLMAgent
from backend.engine.game import WerewolfGame
from backend.engine.rules import build_players
from backend.eval.evolution import AcceptancePolicy
from backend.eval.evolution import TournamentRunner
from backend.eval.review import MetricsCalculator

STRATEGY_FILE = ROOT / "configs" / "discrimination_strategies.yaml"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "experiment"


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_good_bias(role: str) -> dict[str, list[str]]:
    with open(STRATEGY_FILE, encoding="utf-8") as f:
        catalog = yaml.safe_load(f)
    role_catalog = catalog.get(role) or {}
    bias = role_catalog.get("good")
    if not bias:
        raise SystemExit(f"No good strategy for role={role!r}")
    return bias


def make_llm_game_runner(role: str, bias: dict[str, list[str]], strict: bool):
    """Returns a ``game_runner(seed, strategy_version, target_role) -> GameMetrics``
    that plays a real LLM game. Candidate strategy_version means inject bias;
    baseline strategy_version means run with no bias."""

    def runner(seed: int, strategy_version: str, target_role: str | None):
        LLMAgent.STRICT_NO_FALLBACK = strict
        is_candidate = "candidate" in strategy_version.lower() or "v2" in strategy_version.lower()
        per_role_bias = {role: bias} if is_candidate else {}
        agent_config: dict[str, Any] = {"type": "llm", "seed": seed}
        model_pool = (
            os.getenv("EXPERIMENT_MODEL_POOL", "").strip()
            or os.getenv("MODEL_POOL", "").strip()
            or os.getenv("DOUBAO_MODEL_POOL", "").strip()
        )
        if model_pool:
            agent_config["model_pool"] = model_pool
        if per_role_bias:
            agent_config["role_models"] = {role: {"strategy_bias": bias}}
        players = build_players(seed=seed)
        agents = create_agents(players, agent_config)
        game = WerewolfGame(
            players=players,
            agents=agents,
            seed=seed,
            strategy_version=strategy_version,
            strategy_bias_by_role=per_role_bias,
        )
        game.play()
        metric = MetricsCalculator().compute(game.state)
        # Bookkeeping needed by TournamentRunner.compare_metrics()
        fallback_count = sum(
            1
            for rec in game.state.decision_records
            if bool((rec.parsed_action or {}).get("metadata", {}).get("fallback"))
            or bool((rec.parsed_action or {}).get("agent_fallback"))
        )
        invalid_count = sum(1 for rec in game.state.decision_records if not rec.is_valid)
        decision_count = max(len(game.state.decision_records), 1)
        retrieved_count = sum(
            1 for rec in game.state.decision_records if bool((rec.parsed_action or {}).get("retrieval_used"))
        )
        metric.metadata.update(
            {
                "strategy_version": strategy_version,
                "tournament_seed": seed,
                "target_role": target_role,
                "runner_mode": "llm_engine_no_perturbation",
                "fallback_count": fallback_count,
                "invalid_count": invalid_count,
                "decision_count": decision_count,
                "fallback_rate": fallback_count / decision_count,
                "invalid_action_rate": invalid_count / decision_count,
                "retrieved_count": retrieved_count,
                "knowledge_hit_rate": retrieved_count / decision_count,
                "info_leak_count": int(metric.metadata.get("info_leak_count", 0) or 0),
            }
        )
        return metric

    return runner


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--role", required=True, help="Target role (Seer/Witch/Hunter/Guard/Werewolf)")
    ap.add_argument("--seeds", nargs="+", type=int, default=list(range(101, 121)), help="20 seeds by default")
    ap.add_argument("--strict-fallback", default="true")
    ap.add_argument("--baseline-version", default=None)
    ap.add_argument("--candidate-version", default=None)
    ap.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    ap.add_argument("--incremental", default="true")
    args = ap.parse_args()

    role = args.role
    bias = load_good_bias(role)
    strict = args.strict_fallback.lower() not in {"false", "0", "no", "off"}
    baseline_version = args.baseline_version or f"{role.lower()}_v1_baseline"
    candidate_version = args.candidate_version or f"{role.lower()}_v2_candidate"

    print(f"[{utc_iso()}] Phase H — real LLM A/B for role={role}")
    print(f"  baseline_version={baseline_version!r}  candidate_version={candidate_version!r}")
    print(f"  seeds={args.seeds!r}  strict_no_fallback={strict}")
    print(f"  good_strategy_bias keys = {list(bias.keys())}")
    model_pool = (
        os.getenv("EXPERIMENT_MODEL_POOL", "").strip()
        or os.getenv("MODEL_POOL", "").strip()
        or os.getenv("DOUBAO_MODEL_POOL", "").strip()
    )
    print(f"  model_pool={model_pool or '(default provider env)'}")

    game_runner = make_llm_game_runner(role, bias, strict)
    runner = TournamentRunner(acceptance_policy=AcceptancePolicy(), game_runner=game_runner)

    started = time.time()
    incremental = args.incremental.lower() not in {"false", "0", "no", "off"}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    label = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    games_jsonl = args.output_dir / f"c_validation_{role}_{label}.games.jsonl"
    partial_path = args.output_dir / f"c_validation_{role}_{label}.partial_summary.json"
    baseline_metrics = []
    candidate_metrics = []
    if incremental:
        for side, version, bucket in (
            ("baseline", baseline_version, baseline_metrics),
            ("candidate", candidate_version, candidate_metrics),
        ):
            for seed in list(args.seeds):
                print(f"  running {side} seed={seed} version={version}")
                metric = game_runner(seed, version, role)
                bucket.append(metric)
                append_jsonl(
                    games_jsonl,
                    {
                        "side": side,
                        "seed": seed,
                        "strategy_version": version,
                        "metric": runner._metric_summary(metric),
                        "completed_at": utc_iso(),
                    },
                )
                write_json(
                    partial_path,
                    {
                        "updated_at": utc_iso(),
                        "role": role,
                        "strict_no_fallback": strict,
                        "model_pool": model_pool,
                        "baseline_games_completed": len(baseline_metrics),
                        "candidate_games_completed": len(candidate_metrics),
                        "games_jsonl": str(games_jsonl),
                    },
                )
        comparison = runner.compare_metrics(baseline_version, candidate_version, baseline_metrics, candidate_metrics)
        decision = runner.acceptance_policy.decide(comparison)
        cmp = comparison.to_dict()
        tournament_status = "promoted" if decision.accepted else "rolled_back"
        baseline_results = [runner._metric_summary(item) for item in baseline_metrics]
        candidate_results = [runner._metric_summary(item) for item in candidate_metrics]
    else:
        tournament = runner.run_ab_tournament(
            baseline_version=baseline_version,
            candidate_version=candidate_version,
            target_role=role,
            seeds=list(args.seeds),
        )
        cmp = tournament.comparison
        tournament_status = tournament.status
        baseline_results = tournament.baseline_results
        candidate_results = tournament.candidate_results
    elapsed = round(time.time() - started, 2)

    output = {
        "started_at": utc_iso(),
        "elapsed_s": elapsed,
        "role": role,
        "baseline_version": baseline_version,
        "candidate_version": candidate_version,
        "seeds": list(args.seeds),
        "model_pool": model_pool,
        "strict_no_fallback": strict,
        "incremental": incremental,
        "games_jsonl": str(games_jsonl) if incremental else "",
        "baseline_games_completed": len(baseline_results),
        "candidate_games_completed": len(candidate_results),
        "baseline_results": baseline_results,
        "candidate_results": candidate_results,
        "comparison": cmp,
        "status": tournament_status,
    }

    out_path = args.output_dir / f"c_validation_{role}_{label}.json"
    write_json(out_path, output)
    print(f"\nWrote {out_path}")
    print("Comparison:")
    print(f"  baseline_avg_score = {cmp.get('baseline_avg_score')}")
    print(f"  candidate_avg_score = {cmp.get('candidate_avg_score')}")
    print(f"  target_role_avg_score_delta_pct = {cmp.get('target_role_avg_score_delta')}")
    print(f"  role_task_score_delta_pct = {cmp.get('role_task_score_delta')}")
    print(f"  candidate_fallback_count = {cmp.get('candidate_fallback_count')}")
    print(f"  info_leak_count = {cmp.get('info_leak_count')}")
    print(f"  invalid_action_rate = {cmp.get('invalid_action_rate')}")
    print(f"  status = {tournament_status}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
