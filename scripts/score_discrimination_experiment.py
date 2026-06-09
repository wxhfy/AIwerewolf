"""Score Discrimination Experiment Harness.

Runs controlled LLM games where the TARGET role gets a "good" or "bad"
``strategy_bias`` injected into ONLY its agent's prompt (via the
``strategy_bias_by_role`` parameter on ``WerewolfGame``). Other seats
receive no strategy bias.

Per-game output is written to ``data/experiment/role_<R>_<V>_seed_<N>.json``
and is *restartable* — if a target file already exists with
``publish_allowed=True`` we skip that combination. Failures are appended to
``data/experiment/errors.jsonl`` so the next run can retry only those.

Strict mode (``--strict-fallback true``) is on by default; any LLM call that
would fall back to heuristic aborts the game (records the failure, moves on).

Usage:
    # Dry-run (Phase D): Seer × good/bad × 5 seeds = 10 games
    python scripts/score_discrimination_experiment.py \
        --roles Seer --variants good bad --seeds 1 2 3 4 5

    # Full sweep (Phase F): 5 roles × good/bad × 10 seeds = 100 games
    python scripts/score_discrimination_experiment.py \
        --roles Seer Witch Hunter Guard Werewolf \
        --variants good bad \
        --seeds 1 2 3 4 5 6 7 8 9 10
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
from backend.agents.llm_agent import LLMFallbackForbidden
from backend.engine.game import WerewolfGame
from backend.engine.rules import build_players
from backend.eval.review import MetricsCalculator
from backend.eval.track_b import generate_published_review_document

STRATEGY_FILE = ROOT / "configs" / "discrimination_strategies.yaml"
OUTPUT_DIR = ROOT / "data" / "experiment"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
ERROR_LOG = OUTPUT_DIR / "errors.jsonl"


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_strategy_catalog(strategy_file: Path | None = None) -> dict[str, dict[str, dict[str, list[str]]]]:
    path = strategy_file or STRATEGY_FILE
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def output_path(role: str, variant: str, seed: int) -> Path:
    return OUTPUT_DIR / f"role_{role}_{variant}_seed_{seed}.json"


def already_done(role: str, variant: str, seed: int) -> bool:
    path = output_path(role, variant, seed)
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return bool(payload.get("publish_allowed"))
    except Exception:
        return False


def run_one_game(role: str, variant: str, seed: int, catalog: dict, strict: bool) -> dict[str, Any]:
    """Play one LLM game with ``strategy_bias`` applied ONLY to ``role`` seats."""
    LLMAgent.STRICT_NO_FALLBACK = strict
    started_at = utc_iso()
    t0 = time.time()

    role_catalog = catalog.get(role) or {}
    bias = role_catalog.get(variant)
    if not bias:
        raise ValueError(f"strategy catalog missing entry for role={role!r} variant={variant!r}")
    strategy_bias_by_role = {role: bias}

    players = build_players(seed=seed)
    target_players = [p for p in players if p.role.value == role]
    if not target_players:
        raise RuntimeError(f"role {role!r} not present in 7-player default setup")

    # Build LLM agents with per-role strategy bias. Factory's role_models
    # path applies strategy_bias only to seats whose role matches.
    agents = create_agents(
        players,
        {
            "type": "llm",
            "seed": seed,
            "role_models": {role: {"strategy_bias": bias}},
        },
    )
    game = WerewolfGame(
        players=players,
        agents=agents,
        seed=seed,
        strategy_bias_by_role=strategy_bias_by_role,
    )
    state = game.play()
    duration_s = round(time.time() - t0, 2)
    finished_at = utc_iso()

    document = generate_published_review_document(state)
    review_report = document.review_report
    validation = document.validation_result

    # Full per-dimension scores come from MetricsCalculator (the published
    # review report flattens these into player_reviews / scoreboard which
    # don't carry role_task / vote / speech sub-scores).
    game_metrics = MetricsCalculator().compute(state)
    role_player_scores: list[dict[str, Any]] = []
    for score in game_metrics.player_scores:
        if score.role != role:
            continue
        role_player_scores.append(
            {
                "player_id": score.player_id,
                "player_name": score.player_name,
                "persona_name": score.persona_name,
                "role": score.role,
                "alignment": score.alignment,
                "camp_result_score": score.camp_result_score,
                "role_task_score": score.role_task_score,
                "vote_score": score.vote_score,
                "speech_score": score.speech_score,
                "skill_score": score.skill_score,
                "survival_score": score.survival_score,
                "mistake_penalty": score.mistake_penalty,
                "final_score": score.final_score,
                "adjusted_final_score": score.adjusted_final_score
                if score.adjusted_final_score is not None
                else score.final_score,
                "impact_bonus": score.impact_bonus,
                "review_penalty": score.review_penalty,
                "mistakes": list(score.mistakes),
                "mistakes_count": len(score.mistakes),
                "highlights": list(score.highlights),
            }
        )

    # Decision audit (count LLM vs fallback)
    decisions = state.decision_records
    fallback_count = sum(
        1
        for rec in decisions
        if bool((rec.parsed_action or {}).get("metadata", {}).get("fallback"))
        or bool((rec.parsed_action or {}).get("agent_fallback"))
        or str((rec.parsed_action or {}).get("metadata", {}).get("source", "")) == "fallback"
    )
    llm_count = sum(
        1 for rec in decisions if str((rec.parsed_action or {}).get("metadata", {}).get("source", "")) == "llm"
    )

    return {
        "experiment_meta": {
            "role": role,
            "variant": variant,
            "seed": seed,
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_s": duration_s,
            "strict_no_fallback": strict,
            "strategy_bias_applied": bias,
        },
        "game_id": state.id,
        "winner": state.winner.value if state.winner else None,
        "days": state.day,
        "total_events": len(state.events),
        "total_decisions": len(decisions),
        "llm_decision_count": llm_count,
        "fallback_decision_count": fallback_count,
        "publish_allowed": bool(validation.get("publish_allowed")),
        "validation_score": validation.get("score"),
        "validation_grade": validation.get("grade"),
        "review_status": document.status,
        "target_role_player_scores": role_player_scores,
        "target_role_avg_adjusted_final_score": (
            sum(p["adjusted_final_score"] for p in role_player_scores if p["adjusted_final_score"] is not None)
            / max(len(role_player_scores), 1)
            if role_player_scores
            else None
        ),
        "target_role_avg_role_task_score": (
            sum(p["role_task_score"] for p in role_player_scores if p["role_task_score"] is not None)
            / max(len(role_player_scores), 1)
            if role_player_scores
            else None
        ),
        "target_role_total_mistakes": sum(p["mistakes_count"] for p in role_player_scores),
        "bad_case_count": len(review_report.get("bad_cases", [])),
        "highlight_count": len(review_report.get("turning_points", [])),
    }


def append_error(role: str, variant: str, seed: int, err: BaseException) -> None:
    payload = {
        "_at": utc_iso(),
        "role": role,
        "variant": variant,
        "seed": seed,
        "error_type": type(err).__name__,
        "error_message": str(err),
    }
    with open(ERROR_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def run_batch(
    roles: list[str], variants: list[str], seeds: list[int], strict: bool, force: bool, catalog_file: Path | None = None
) -> dict[str, Any]:
    catalog = load_strategy_catalog(catalog_file)
    missing = [r for r in roles if r not in catalog]
    if missing:
        raise SystemExit(f"Strategy catalog missing entries for: {missing!r}")

    plan: list[tuple[str, str, int]] = [
        (role, variant, seed) for role in roles for variant in variants for seed in seeds
    ]
    total = len(plan)
    catalog_label = (catalog_file or STRATEGY_FILE).name
    print(
        f"[{utc_iso()}] Experiment plan: {total} games "
        f"({len(roles)} roles × {len(variants)} variants × {len(seeds)} seeds) "
        f"strict_no_fallback={strict} catalog={catalog_label} "
        f"placement={os.getenv('STRATEGY_BIAS_PLACEMENT', 'user')}",
        flush=True,
    )

    completed: list[str] = []
    skipped: list[str] = []
    failed: list[dict[str, Any]] = []

    for idx, (role, variant, seed) in enumerate(plan, 1):
        tag = f"{role}/{variant}/seed{seed}"
        if not force and already_done(role, variant, seed):
            print(f"  ({idx}/{total}) {tag} ✓ skipped (already exists)", flush=True)
            skipped.append(tag)
            continue

        print(f"  ({idx}/{total}) {tag} ▶ starting at {utc_iso()}", flush=True)
        try:
            payload = run_one_game(role, variant, seed, catalog, strict)
            output_path(role, variant, seed).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            avg_score = payload.get("target_role_avg_adjusted_final_score")
            mistakes = payload.get("target_role_total_mistakes", 0)
            fb = payload.get("fallback_decision_count")
            avg_str = f"{avg_score:.2f}" if avg_score is not None else "—"
            print(
                f"    ✓ done in {payload['experiment_meta']['duration_s']}s "
                f"target_avg_score={avg_str} mistakes={mistakes} fallback={fb} "
                f"publish={payload['publish_allowed']}",
                flush=True,
            )
            completed.append(tag)
        except LLMFallbackForbidden as exc:
            print(f"    ✗ ABORT (LLM fallback forbidden): {exc}", flush=True)
            append_error(role, variant, seed, exc)
            failed.append({"tag": tag, "kind": "fallback_aborted", "message": str(exc)})
        except Exception as exc:
            print(f"    ✗ FAILED ({type(exc).__name__}): {exc}", flush=True)
            traceback.print_exc()
            append_error(role, variant, seed, exc)
            failed.append({"tag": tag, "kind": type(exc).__name__, "message": str(exc)})

    summary = {
        "finished_at": utc_iso(),
        "total_planned": total,
        "completed_this_run": len(completed),
        "skipped_already_done": len(skipped),
        "failed_this_run": len(failed),
        "completed_tags": completed,
        "failed_tags": failed,
        "output_dir": str(OUTPUT_DIR),
    }
    label = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    summary_path = OUTPUT_DIR / f"_summary_{label}.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[{utc_iso()}] Batch summary written to {summary_path}", flush=True)
    print(f"  completed={len(completed)}  skipped={len(skipped)}  failed={len(failed)}", flush=True)
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--roles", nargs="+", default=["Seer"], help="Target roles to test (catalog keys)")
    ap.add_argument("--variants", nargs="+", default=["good", "bad"], help="Variants per role")
    ap.add_argument("--seeds", nargs="+", type=int, default=[1, 2, 3, 4, 5], help="Seeds")
    ap.add_argument("--strict-fallback", default="true", help="If true, any LLM fallback aborts the game")
    ap.add_argument("--force", action="store_true", help="Re-run even if output JSON already exists")
    ap.add_argument(
        "--catalog-file",
        default=None,
        help="Path to strategy catalog YAML (default: configs/discrimination_strategies.yaml). "
        "Use configs/discrimination_strategies_iter3.yaml for iter3 example-rich variant.",
    )
    args = ap.parse_args()

    strict = args.strict_fallback.lower() not in {"false", "0", "no", "off"}
    catalog_path = Path(args.catalog_file).resolve() if args.catalog_file else None
    summary = run_batch(
        roles=list(args.roles),
        variants=list(args.variants),
        seeds=list(args.seeds),
        strict=strict,
        force=args.force,
        catalog_file=catalog_path,
    )
    return 0 if summary["failed_this_run"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
