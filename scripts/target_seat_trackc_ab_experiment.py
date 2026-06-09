#!/usr/bin/env python3
"""Target-seat Track C causal A/B runner using CognitiveAgent.

This runner is for the remaining causal claim: whether Track C helps the final
agent when only one target seat is upgraded and all other seats stay baseline.
It keeps seed, role assignment, persona sampling, and model pool fixed between
baseline and candidate games.
"""

from __future__ import annotations

import argparse
import atexit
import fcntl
import json
import multiprocessing as mp
import os
import queue
import sys
import time
import traceback
from contextlib import contextmanager
from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path
from random import Random
from typing import Any
from typing import Iterable
from typing import Sequence

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.agents.characters import PERSONA_POOL
from backend.agents.characters import build_character_roster
from backend.agents.cognitive.factory import create_cognitive_agent_with_character
from backend.agents.cognitive.factory import create_llm_from_client
from backend.engine.game import WerewolfGame
from backend.engine.rules import build_players
from backend.engine.rules import get_role_configuration
from backend.eval.review import GameMetrics
from backend.eval.review import MetricsCalculator
from backend.eval.review import PlayerScore
from backend.llm import create_client
from backend.llm.env import load_env_file
from scripts.track_bc_leaderboard_experiment import FRAMEWORKS
from scripts.track_bc_leaderboard_experiment import FrameworkSpec
from scripts.track_bc_leaderboard_experiment import ModelSpec
from scripts.track_bc_leaderboard_experiment import model_for_seat
from scripts.track_bc_leaderboard_experiment import resolve_model_specs
from scripts.track_bc_leaderboard_experiment import summarize_decision_records
from scripts.track_bc_leaderboard_experiment import validate_model_specs

DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "target_seat_trackc_ab"
WOLF_ROLES = {"Werewolf", "WhiteWolfKing"}


@dataclass(frozen=True)
class TargetSeat:
    seed: int
    player_id: str
    seat: int
    role: str
    alignment: str
    name: str


@dataclass
class TargetGameResult:
    side: str
    seed: int
    target: TargetSeat
    game_id: str
    winner: str | None
    target_won: bool
    target_score: dict[str, Any]
    decision_summary: dict[str, Any]
    elapsed_s: float
    framework_assignment: dict[str, str]
    seat_assignments: list[dict[str, Any]]


class TargetGameTimeoutError(TimeoutError):
    """Raised when a target-seat side game exceeds the configured timeout."""


class TargetGameSubprocessError(RuntimeError):
    """Error payload propagated from a target-seat side-game subprocess."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        super().__init__(str(payload.get("error") or "target-seat subprocess failed"))

    @property
    def error_type(self) -> str:
        return str(self.payload.get("error_type") or "TargetGameSubprocessError")

    @property
    def child_traceback(self) -> str:
        return str(self.payload.get("traceback") or "")


@dataclass
class OutputFileLock:
    path: Path
    handle: Any | None


class TargetOutputLockError(RuntimeError):
    """Raised when another process is already writing the same experiment output."""


def utc_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"


def acquire_output_file_lock(output_path: Path) -> OutputFileLock:
    """Acquire a non-blocking lock for a target-seat output JSON.

    Long target-seat runs are commonly resumed with ``--append``. A second
    process appending to the same main JSON and sidecar JSONL files can corrupt
    the experiment boundary, so fail fast instead of waiting or interleaving.
    """

    lock_path = output_path.with_suffix(output_path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise TargetOutputLockError(
            f"Output is already locked: {lock_path}. Another target-seat experiment may be "
            f"writing {output_path}. Wait for it to finish or use a different --output-dir."
        ) from exc
    handle.seek(0)
    handle.truncate()
    handle.write(
        json.dumps(
            {
                "pid": os.getpid(),
                "output": str(output_path),
                "locked_at": utc_iso(),
            },
            ensure_ascii=False,
        )
        + "\n"
    )
    handle.flush()
    return OutputFileLock(path=lock_path, handle=handle)


def release_output_file_lock(lock: OutputFileLock | None) -> None:
    if lock is None or lock.handle is None:
        return
    try:
        fcntl.flock(lock.handle.fileno(), fcntl.LOCK_UN)
    finally:
        lock.handle.close()
        lock.handle = None


@contextmanager
def patched_env(updates: dict[str, str]) -> Iterable[None]:
    old_values = {key: os.environ.get(key) for key in updates}
    try:
        for key, value in updates.items():
            os.environ[key] = value
        yield
    finally:
        for key, old_value in old_values.items():
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value


def env_flag(value: str | None, default: bool = True) -> bool:
    raw = str(value or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def framework_feature_flags(framework: FrameworkSpec) -> dict[str, bool]:
    """Freeze framework feature flags on each agent.

    Track C and anti-pattern prompts are evaluated during AgentLoop runtime.
    Using process env alone would make target-seat A/B leak into all seats.
    """
    return {
        "COGNITIVE_ENABLE_TRACK_C": env_flag(framework.env.get("COGNITIVE_ENABLE_TRACK_C"), True),
        "COGNITIVE_ENABLE_ANTI_PATTERNS": env_flag(framework.env.get("COGNITIVE_ENABLE_ANTI_PATTERNS"), True),
        "COGNITIVE_ENABLE_REFLECTION": env_flag(framework.env.get("COGNITIVE_ENABLE_REFLECTION"), True),
    }


def utc_label() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def enum_value(value: Any) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value))


def sample_personas(count: int, seed: int | None) -> list[dict[str, Any]] | None:
    if not PERSONA_POOL:
        return None
    rng = Random(seed)
    pool = list(PERSONA_POOL)
    rng.shuffle(pool)
    if len(pool) >= count:
        return pool[:count]
    return [pool[index % len(pool)] for index in range(count)]


def select_target(players: Sequence[Any], target_role: str, *, occurrence: int = 1) -> TargetSeat:
    matches = [player for player in players if player.role.value == target_role]
    if not matches:
        available = ", ".join(sorted({player.role.value for player in players}))
        raise RuntimeError(f"target role {target_role!r} not present in roster. Available roles: {available}")
    index = max(0, min(occurrence - 1, len(matches) - 1))
    player = matches[index]
    return TargetSeat(
        seed=0,
        player_id=player.id,
        seat=player.seat,
        role=player.role.value,
        alignment=player.alignment.value,
        name=player.name,
    )


def target_won(role: str, winner: str | None) -> bool:
    normalized = str(winner or "").lower()
    if role in WOLF_ROLES:
        return normalized == "wolf"
    return normalized == "village"


def score_to_dict(score: PlayerScore | None) -> dict[str, Any]:
    if score is None:
        return {}
    return {
        "player_id": score.player_id,
        "player_name": score.player_name,
        "role": score.role,
        "alignment": score.alignment,
        "camp_result_score": score.camp_result_score,
        "role_task_score": score.role_task_score,
        "vote_score": score.vote_score,
        "speech_score": score.speech_score,
        "skill_score": score.skill_score,
        "survival_score": score.survival_score,
        "process_score": score.process_score,
        "outcome_bonus": score.outcome_bonus,
        "final_score": score.final_score,
        "adjusted_final_score": score.adjusted_final_score
        if score.adjusted_final_score is not None
        else score.final_score,
        "role_normalized_score": score.role_normalized_score,
        "mistake_penalty": score.mistake_penalty,
    }


def find_target_score(metric: GameMetrics, player_id: str) -> PlayerScore | None:
    for score in metric.player_scores:
        if score.player_id == player_id:
            return score
    return None


def build_roster(seed: int, player_count: int) -> tuple[list[Any], list[dict[str, Any]] | None]:
    roles = get_role_configuration(player_count)
    players = build_players(roles, seed=seed)
    sampled_personas = sample_personas(len(players), seed)
    if sampled_personas:
        for player, persona_data in zip(players, sampled_personas):
            player.name = str(persona_data.get("name") or player.name)
    return players, sampled_personas


def run_target_game(
    *,
    seed: int,
    player_count: int,
    max_days: int,
    model_specs: Sequence[ModelSpec],
    baseline_framework: FrameworkSpec,
    candidate_framework: FrameworkSpec,
    target_role: str,
    target_occurrence: int,
    side: str,
) -> TargetGameResult:
    players, sampled_personas = build_roster(seed, player_count)
    target = select_target(players, target_role, occurrence=target_occurrence)
    target = TargetSeat(
        seed=seed,
        player_id=target.player_id,
        seat=target.seat,
        role=target.role,
        alignment=target.alignment,
        name=target.name,
    )
    characters = build_character_roster(players, seed=seed, sampled_personas=sampled_personas)

    target_framework = candidate_framework if side == "candidate" else baseline_framework
    framework_by_player = {
        player.id: (target_framework if player.id == target.player_id else baseline_framework) for player in players
    }
    framework_assignment = {player.id: framework_by_player[player.id].name for player in players}
    agents: dict[str, Any] = {}
    seat_assignments: list[dict[str, Any]] = []

    for seat_index, player in enumerate(players):
        model_spec = model_for_seat(model_specs, seed, seat_index)
        player.model_name = model_spec.model
        framework = framework_by_player[player.id]
        with patched_env(framework.env):
            client = create_client(provider=model_spec.provider, model=model_spec.model)
            if getattr(client, "available", True) is False:
                raise RuntimeError(f"LLM client unavailable for {model_spec.label}")
            agents[player.id] = create_cognitive_agent_with_character(
                player_id=player.id,
                role=player.role.value,
                llm=create_llm_from_client(client),
                player_name=player.name,
                player_seat=player.seat,
                character=characters[player.id],
                retrieval_policy=framework.retrieval_policy,
                feature_flags=framework_feature_flags(framework),
            )
        seat_assignments.append(
            {
                "seat": player.seat,
                "player_id": player.id,
                "name": player.name,
                "role": player.role.value,
                "alignment": player.alignment.value,
                "framework": framework.name,
                "model": model_spec.label,
                "is_target": player.id == target.player_id,
            }
        )

    strategy_version = f"target-seat-{side}:{target_role}:{target_framework.name}"
    started = time.perf_counter()
    game = WerewolfGame(
        players=players,
        agents=agents,
        seed=seed,
        max_days=max_days,
        player_count=player_count,
        strategy_version=strategy_version,
        sampled_personas=sampled_personas,
    )
    runtime_env = {
        "COGNITIVE_ENABLE_TRACK_C": "0",
        "COGNITIVE_ENABLE_ANTI_PATTERNS": "0",
        "COGNITIVE_ENABLE_REFLECTION": "0",
        "AIWEREWOLF_RETRIEVAL_POLICY": baseline_framework.retrieval_policy,
    }
    with patched_env(runtime_env):
        state = game.play()
    elapsed_s = round(time.perf_counter() - started, 3)
    metric = MetricsCalculator().compute(state)
    decision_summary = summarize_decision_records(state.decision_records)
    target_score = find_target_score(metric, target.player_id)
    winner = enum_value(state.winner)
    return TargetGameResult(
        side=side,
        seed=seed,
        target=target,
        game_id=state.id,
        winner=winner,
        target_won=target_won(target.role, winner),
        target_score=score_to_dict(target_score),
        decision_summary=decision_summary,
        elapsed_s=elapsed_s,
        framework_assignment=framework_assignment,
        seat_assignments=seat_assignments,
    )


def _run_target_game_worker(result_queue: Any, kwargs: dict[str, Any]) -> None:
    try:
        result_queue.put({"ok": True, "result": run_target_game(**kwargs)})
    except Exception as exc:
        result_queue.put(
            {
                "ok": False,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(limit=12),
            }
        )


def run_target_game_with_optional_timeout(*, timeout_s: int = 0, **kwargs: Any) -> TargetGameResult:
    if timeout_s <= 0:
        return run_target_game(**kwargs)

    context_name = "fork" if "fork" in mp.get_all_start_methods() else "spawn"
    ctx = mp.get_context(context_name)
    result_queue = ctx.Queue(maxsize=1)
    proc = ctx.Process(target=_run_target_game_worker, args=(result_queue, dict(kwargs)))
    proc.start()
    proc.join(timeout_s)
    if proc.is_alive():
        proc.terminate()
        proc.join(5)
        if proc.is_alive():
            proc.kill()
            proc.join(5)
        raise TargetGameTimeoutError(
            "target-seat side game timed out after "
            f"{timeout_s}s (side={kwargs.get('side')}, seed={kwargs.get('seed')}, "
            f"target_role={kwargs.get('target_role')}, exitcode={proc.exitcode})"
        )

    try:
        payload = result_queue.get_nowait()
    except queue.Empty as exc:
        raise TargetGameSubprocessError(
            {
                "error_type": "ChildProcessError",
                "error": f"target-seat subprocess exited without result (exitcode={proc.exitcode})",
                "traceback": "",
            }
        ) from exc
    finally:
        result_queue.close()
        result_queue.join_thread()

    if payload.get("ok"):
        result = payload.get("result")
        if isinstance(result, TargetGameResult):
            return result
        raise TargetGameSubprocessError(
            {
                "error_type": "ChildProcessError",
                "error": f"unexpected target-seat payload type: {type(result).__name__}",
                "traceback": "",
            }
        )
    raise TargetGameSubprocessError(payload)


def build_failure_record(
    exc: Exception,
    *,
    seed: int,
    side: str,
    target_role: str,
    elapsed_s: float,
    timeout_s: int,
) -> dict[str, Any]:
    if isinstance(exc, TargetGameSubprocessError):
        error_type = exc.error_type
        error = str(exc)
        tb = exc.child_traceback
    else:
        error_type = type(exc).__name__
        error = str(exc)
        tb = traceback.format_exc(limit=8)
    return {
        "seed": seed,
        "side": side,
        "target_role": target_role,
        "error_type": error_type,
        "error": error,
        "traceback": tb,
        "elapsed_s": elapsed_s,
        "timeout_s": timeout_s,
        "external_failure": True,
        "recorded_at": utc_iso(),
    }


def avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = position - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def bootstrap_mean_ci(values: list[float], *, iterations: int = 1000, seed: int = 0) -> dict[str, Any]:
    if not values:
        return {"samples": 0, "mean": 0.0, "ci95_low": 0.0, "ci95_high": 0.0}
    if len(values) == 1:
        return {
            "samples": 1,
            "mean": round(values[0], 4),
            "ci95_low": round(values[0], 4),
            "ci95_high": round(values[0], 4),
        }
    rng = Random(seed)
    means = []
    for _ in range(iterations):
        sample = [rng.choice(values) for _ in values]
        means.append(avg(sample))
    return {
        "samples": len(values),
        "mean": round(avg(values), 4),
        "ci95_low": round(percentile(means, 0.025), 4),
        "ci95_high": round(percentile(means, 0.975), 4),
    }


def result_metric(result: dict[str, Any], field: str) -> float:
    return float(result.get("target_score", {}).get(field, 0.0) or 0.0)


def acceptance_gates(
    *,
    paired_seed_count: int,
    candidate_fallback: int,
    candidate_invalid: int,
    score_ci: dict[str, Any],
    role_task_ci: dict[str, Any],
    win_ci: dict[str, Any],
    min_paired_seeds: int,
    min_adjusted_score_delta: float,
    min_role_task_delta: float,
    min_win_rate_delta: float,
    require_positive_ci: bool,
) -> dict[str, Any]:
    enough_samples = paired_seed_count >= min_paired_seeds
    strict_health = candidate_fallback == 0 and candidate_invalid == 0
    score_gate = float(score_ci.get("mean", 0.0)) >= min_adjusted_score_delta
    role_task_gate = float(role_task_ci.get("mean", 0.0)) >= min_role_task_delta
    win_gate = float(win_ci.get("mean", 0.0)) >= min_win_rate_delta
    ci_gate = (
        not require_positive_ci
        or float(score_ci.get("ci95_low", 0.0)) > 0
        or float(role_task_ci.get("ci95_low", 0.0)) > 0
        or float(win_ci.get("ci95_low", 0.0)) > 0
    )
    improvement_gate = score_gate or role_task_gate or win_gate
    accepted = enough_samples and strict_health and improvement_gate and ci_gate
    if accepted:
        claim_level = "causal_supported"
    elif not enough_samples:
        claim_level = "insufficient_samples"
    elif not strict_health:
        claim_level = "health_failed"
    elif not improvement_gate:
        claim_level = "no_material_improvement"
    else:
        claim_level = "ci_not_positive"
    return {
        "accepted": accepted,
        "claim_level": claim_level,
        "min_paired_seeds": min_paired_seeds,
        "min_adjusted_score_delta": min_adjusted_score_delta,
        "min_role_task_delta": min_role_task_delta,
        "min_win_rate_delta": min_win_rate_delta,
        "require_positive_ci": require_positive_ci,
        "gates": {
            "enough_samples": enough_samples,
            "strict_health": strict_health,
            "score_gate": score_gate,
            "role_task_gate": role_task_gate,
            "win_gate": win_gate,
            "ci_gate": ci_gate,
            "improvement_gate": improvement_gate,
        },
    }


def compare_results(
    baseline: list[dict[str, Any]],
    candidate: list[dict[str, Any]],
    *,
    bootstrap_iterations: int = 1000,
    min_paired_seeds: int = 20,
    min_adjusted_score_delta: float = 3.0,
    min_role_task_delta: float = 0.03,
    min_win_rate_delta: float = 0.03,
    require_positive_ci: bool = True,
) -> dict[str, Any]:
    by_seed_baseline = {int(item["seed"]): item for item in baseline}
    by_seed_candidate = {int(item["seed"]): item for item in candidate}
    paired_seeds = sorted(set(by_seed_baseline) & set(by_seed_candidate))

    def paired_delta(field: str) -> list[float]:
        return [
            result_metric(by_seed_candidate[seed], field) - result_metric(by_seed_baseline[seed], field)
            for seed in paired_seeds
        ]

    score_deltas = paired_delta("adjusted_final_score")
    role_task_deltas = paired_delta("role_task_score")
    process_deltas = paired_delta("process_score")
    target_win_deltas = [
        float(by_seed_candidate[seed].get("target_won", False)) - float(by_seed_baseline[seed].get("target_won", False))
        for seed in paired_seeds
    ]
    candidate_fallback = sum(int(item.get("decision_summary", {}).get("fallback_count", 0) or 0) for item in candidate)
    candidate_invalid = sum(int(item.get("decision_summary", {}).get("invalid_count", 0) or 0) for item in candidate)
    candidate_decisions = sum(int(item.get("decision_summary", {}).get("decision_count", 0) or 0) for item in candidate)
    score_ci = bootstrap_mean_ci(score_deltas, iterations=bootstrap_iterations, seed=17)
    role_task_ci = bootstrap_mean_ci(role_task_deltas, iterations=bootstrap_iterations, seed=23)
    process_ci = bootstrap_mean_ci(process_deltas, iterations=bootstrap_iterations, seed=29)
    win_ci = bootstrap_mean_ci(target_win_deltas, iterations=bootstrap_iterations, seed=31)
    gates = acceptance_gates(
        paired_seed_count=len(paired_seeds),
        candidate_fallback=candidate_fallback,
        candidate_invalid=candidate_invalid,
        score_ci=score_ci,
        role_task_ci=role_task_ci,
        win_ci=win_ci,
        min_paired_seeds=min_paired_seeds,
        min_adjusted_score_delta=min_adjusted_score_delta,
        min_role_task_delta=min_role_task_delta,
        min_win_rate_delta=min_win_rate_delta,
        require_positive_ci=require_positive_ci,
    )
    return {
        "paired_seed_count": len(paired_seeds),
        "paired_seeds": paired_seeds,
        "baseline_completed": len(baseline),
        "candidate_completed": len(candidate),
        "baseline_target_win_rate": avg([float(item.get("target_won", False)) for item in baseline]),
        "candidate_target_win_rate": avg([float(item.get("target_won", False)) for item in candidate]),
        "target_win_rate_delta": avg(target_win_deltas),
        "baseline_target_adjusted_score": avg([result_metric(item, "adjusted_final_score") for item in baseline]),
        "candidate_target_adjusted_score": avg([result_metric(item, "adjusted_final_score") for item in candidate]),
        "target_adjusted_score_delta": avg(score_deltas),
        "target_role_task_delta": avg(role_task_deltas),
        "target_process_score_delta": avg(process_deltas),
        "paired_deltas": {
            "adjusted_final_score": [round(delta, 4) for delta in score_deltas],
            "role_task_score": [round(delta, 4) for delta in role_task_deltas],
            "process_score": [round(delta, 4) for delta in process_deltas],
            "target_win": [round(delta, 4) for delta in target_win_deltas],
        },
        "bootstrap_ci": {
            "adjusted_final_score_delta": score_ci,
            "role_task_score_delta": role_task_ci,
            "process_score_delta": process_ci,
            "target_win_rate_delta": win_ci,
        },
        "positive_adjusted_score_delta_seeds": sum(1 for delta in score_deltas if delta > 0),
        "positive_role_task_delta_seeds": sum(1 for delta in role_task_deltas if delta > 0),
        "positive_win_delta_seeds": sum(1 for delta in target_win_deltas if delta > 0),
        "candidate_fallback_count": candidate_fallback,
        "candidate_invalid_count": candidate_invalid,
        "candidate_decision_count": candidate_decisions,
        "candidate_invalid_rate": candidate_invalid / max(candidate_decisions, 1),
        "acceptance": gates,
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_previous_results(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    baseline = payload.get("baseline_results", []) if isinstance(payload, dict) else []
    candidate = payload.get("candidate_results", []) if isinstance(payload, dict) else []
    return dedupe_results_by_seed_side(list(baseline or [])), dedupe_results_by_seed_side(list(candidate or []))


def load_previous_failures(payload: dict[str, Any]) -> list[dict[str, Any]]:
    failures = payload.get("failures", []) if isinstance(payload, dict) else []
    return list(failures or []) if isinstance(failures, list) else []


def read_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            raw = line.strip()
            if not raw:
                continue
            rows.append(json.loads(raw))
    return rows


def merge_sidecar_results(
    baseline_results: list[dict[str, Any]],
    candidate_results: list[dict[str, Any]],
    games_jsonl: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    rows = read_jsonl_rows(games_jsonl)
    if not rows:
        return baseline_results, candidate_results, 0
    baseline_rows = [row for row in rows if str(row.get("side") or "") == "baseline"]
    candidate_rows = [row for row in rows if str(row.get("side") or "") == "candidate"]
    merged_baseline = dedupe_results_by_seed_side([*baseline_results, *baseline_rows])
    merged_candidate = dedupe_results_by_seed_side([*candidate_results, *candidate_rows])
    return merged_baseline, merged_candidate, len(rows)


def merge_sidecar_failures(failures: list[dict[str, Any]], failures_jsonl: Path) -> tuple[list[dict[str, Any]], int]:
    rows = read_jsonl_rows(failures_jsonl)
    if not rows:
        return failures, 0
    merged: dict[tuple[Any, str, str], dict[str, Any]] = {}
    for row in [*failures, *rows]:
        key = (row.get("seed"), str(row.get("side") or ""), str(row.get("error_type") or ""))
        merged[key] = row
    return list(merged.values()), len(rows)


def dedupe_results_by_seed_side(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[tuple[int, str], dict[str, Any]] = {}
    for row in rows:
        try:
            seed = int(row.get("seed"))
        except (TypeError, ValueError):
            continue
        side = str(row.get("side") or "").strip()
        if side:
            by_key[(seed, side)] = row
    return list(by_key.values())


def validate_resume_payload(
    payload: dict[str, Any],
    *,
    path: Path,
    target_role: str,
    target_occurrence: int,
    player_count: int,
    max_days: int,
    baseline_framework: str,
    candidate_framework: str,
    model_pool: Sequence[str],
) -> None:
    if not payload:
        raise RuntimeError(f"Resume file is empty or missing: {path}")
    if payload.get("runner") and payload.get("runner") != "target_seat_trackc_ab_experiment.py":
        raise RuntimeError(f"Resume file was not produced by target_seat_trackc_ab_experiment.py: {path}")
    expected = {
        "target_role": target_role,
        "target_occurrence": target_occurrence,
        "player_count": player_count,
        "max_days": max_days,
        "baseline_framework": baseline_framework,
        "candidate_framework": candidate_framework,
    }
    for key, value in expected.items():
        if key in payload and payload.get(key) != value:
            raise RuntimeError(f"Resume metadata mismatch for {key}: expected {value!r}, got {payload.get(key)!r}")
    if "model_pool" in payload and list(payload.get("model_pool") or []) != list(model_pool):
        raise RuntimeError("Resume metadata mismatch for model_pool")
    for key in ("baseline_results", "candidate_results"):
        if key in payload and not isinstance(payload.get(key), list):
            raise RuntimeError(f"Resume field {key} must be a list")


def completed_sides_by_seed(*result_lists: list[dict[str, Any]]) -> dict[tuple[int, str], dict[str, Any]]:
    completed: dict[tuple[int, str], dict[str, Any]] = {}
    for rows in result_lists:
        for row in rows:
            try:
                seed = int(row.get("seed"))
            except (TypeError, ValueError):
                continue
            side = str(row.get("side") or "").strip()
            if side:
                completed[(seed, side)] = row
    return completed


def result_seeds(*result_lists: list[dict[str, Any]]) -> list[int]:
    seeds: set[int] = set()
    for rows in result_lists:
        for row in rows:
            try:
                seeds.add(int(row.get("seed")))
            except (TypeError, ValueError):
                continue
    return sorted(seeds)


def write_jsonl_rows(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def write_partial(
    path: Path,
    *,
    target_role: str,
    baseline_results: list[dict[str, Any]],
    candidate_results: list[dict[str, Any]],
    failures: list[dict[str, Any]],
    games_jsonl: Path,
    failures_jsonl: Path,
    resume_from: Path | None,
    append: bool,
    game_timeout_s: int,
) -> None:
    partial = {
        "updated_at": utc_iso(),
        "target_role": target_role,
        "baseline_completed": len(baseline_results),
        "candidate_completed": len(candidate_results),
        "failure_count": len(failures),
        "games_jsonl": str(games_jsonl),
        "failures_jsonl": str(failures_jsonl),
        "resume_from": str(resume_from) if resume_from else "",
        "append": bool(append),
        "game_timeout_s": game_timeout_s,
    }
    write_json(path, partial)


def dry_run_plan(
    *,
    seeds: Sequence[int],
    player_count: int,
    target_role: str,
    target_occurrence: int,
    baseline_framework: FrameworkSpec,
    candidate_framework: FrameworkSpec,
) -> dict[str, Any]:
    rows = []
    for seed in seeds:
        players, _ = build_roster(seed, player_count)
        target = select_target(players, target_role, occurrence=target_occurrence)
        rows.append(
            {
                "seed": seed,
                "target_seat": target.seat,
                "target_player_id": target.player_id,
                "target_role": target.role,
                "target_alignment": target.alignment,
                "roles": [player.role.value for player in players],
                "baseline_framework": baseline_framework.name,
                "candidate_framework": candidate_framework.name,
            }
        )
    return {"dry_run": True, "rows": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run target-seat Track C A/B with CognitiveAgent")
    parser.add_argument("--target-role", default="Seer")
    parser.add_argument("--target-occurrence", type=int, default=1, help="For duplicate roles, choose nth occurrence.")
    parser.add_argument("--seeds", nargs="+", type=int, default=list(range(9301, 9321)))
    parser.add_argument("--player-count", type=int, default=7)
    parser.add_argument("--max-days", type=int, default=20)
    parser.add_argument("--baseline-framework", default="basic_react")
    parser.add_argument("--candidate-framework", default="rag_react")
    parser.add_argument("--models", default="")
    parser.add_argument("--allow-fake", action="store_true")
    parser.add_argument("--skip-client-check", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--game-timeout-s", type=int, default=0, help="Hard timeout per side game; 0 disables.")
    parser.add_argument(
        "--max-new-games", type=int, default=0, help="Stop after this many newly-run side games; 0 disables."
    )
    parser.add_argument(
        "--only-side",
        choices=["baseline", "candidate"],
        default="",
        help="Run only one side. Useful for retrying missing side games.",
    )
    parser.add_argument("--resume-from", type=Path, default=None, help="Previous target_seat_ab_*.json to resume from.")
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append resumed results into --resume-from instead of writing a new timestamped output.",
    )
    parser.add_argument("--bootstrap-iterations", type=int, default=1000)
    parser.add_argument("--min-paired-seeds", type=int, default=20)
    parser.add_argument("--min-adjusted-score-delta", type=float, default=3.0)
    parser.add_argument("--min-role-task-delta", type=float, default=0.03)
    parser.add_argument("--min-win-rate-delta", type=float, default=0.03)
    parser.add_argument(
        "--allow-ci-cross-zero",
        action="store_true",
        help="Do not require a positive bootstrap CI lower bound for acceptance.",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    load_env_file()
    if args.baseline_framework not in FRAMEWORKS or args.candidate_framework not in FRAMEWORKS:
        raise SystemExit(f"Unknown framework. Choices: {', '.join(sorted(FRAMEWORKS))}")
    baseline_framework = FRAMEWORKS[args.baseline_framework]
    candidate_framework = FRAMEWORKS[args.candidate_framework]
    label = utc_label()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        payload = dry_run_plan(
            seeds=args.seeds,
            player_count=args.player_count,
            target_role=args.target_role,
            target_occurrence=args.target_occurrence,
            baseline_framework=baseline_framework,
            candidate_framework=candidate_framework,
        )
        out = args.output_dir / f"target_seat_ab_dry_run_{args.target_role}_{label}.json"
        write_json(out, payload)
        print(f"Wrote {out}")
        for row in payload["rows"][:10]:
            print(
                f"seed={row['seed']} target={row['target_role']} seat={row['target_seat']} "
                f"{row['baseline_framework']} -> {row['candidate_framework']}"
            )
        return 0

    model_specs = resolve_model_specs(args.models)
    validate_model_specs(model_specs, allow_fake=args.allow_fake, skip_client_check=args.skip_client_check)
    model_pool = [spec.label for spec in model_specs]
    baseline_results: list[dict[str, Any]] = []
    candidate_results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    output_lock: OutputFileLock | None = None
    if args.resume_from:
        resume_payload = read_json(args.resume_from)
        try:
            validate_resume_payload(
                resume_payload,
                path=args.resume_from,
                target_role=args.target_role,
                target_occurrence=args.target_occurrence,
                player_count=args.player_count,
                max_days=args.max_days,
                baseline_framework=baseline_framework.name,
                candidate_framework=candidate_framework.name,
                model_pool=model_pool,
            )
        except RuntimeError as exc:
            raise SystemExit(str(exc)) from exc
        previous_baseline, previous_candidate = load_previous_results(resume_payload)
        previous_failures = load_previous_failures(resume_payload)
        baseline_results.extend(previous_baseline)
        candidate_results.extend(previous_candidate)
        failures.extend(previous_failures)
        if args.append:
            out = args.resume_from.resolve()
            games_jsonl = out.with_suffix(".games.jsonl")
            failures_jsonl = out.with_suffix(".failures.jsonl")
            partial_path = out.with_suffix(".partial.json")
        else:
            out = args.output_dir / f"target_seat_ab_{args.target_role}_{label}.json"
            games_jsonl = args.output_dir / f"target_seat_ab_{args.target_role}_{label}.games.jsonl"
            failures_jsonl = args.output_dir / f"target_seat_ab_{args.target_role}_{label}.failures.jsonl"
            partial_path = args.output_dir / f"target_seat_ab_{args.target_role}_{label}.partial.json"
    else:
        out = args.output_dir / f"target_seat_ab_{args.target_role}_{label}.json"
        games_jsonl = args.output_dir / f"target_seat_ab_{args.target_role}_{label}.games.jsonl"
        failures_jsonl = args.output_dir / f"target_seat_ab_{args.target_role}_{label}.failures.jsonl"
        partial_path = args.output_dir / f"target_seat_ab_{args.target_role}_{label}.partial.json"
    output_lock = acquire_output_file_lock(out)
    atexit.register(release_output_file_lock, output_lock)
    if args.resume_from and args.append:
        baseline_results, candidate_results, sidecar_game_rows = merge_sidecar_results(
            baseline_results,
            candidate_results,
            games_jsonl,
        )
        failures, sidecar_failure_rows = merge_sidecar_failures(failures, failures_jsonl)
        if sidecar_game_rows or sidecar_failure_rows:
            print(
                "merged append sidecars "
                f"games_jsonl_rows={sidecar_game_rows} failures_jsonl_rows={sidecar_failure_rows}"
            )
    already_done = completed_sides_by_seed(baseline_results, candidate_results)
    if args.resume_from and not args.append:
        write_jsonl_rows(games_jsonl, [*baseline_results, *candidate_results])
        write_jsonl_rows(failures_jsonl, failures)

    new_games_attempted = 0
    new_games_completed = 0
    started = time.perf_counter()
    sides = (("baseline", baseline_results), ("candidate", candidate_results))
    if args.only_side:
        sides = tuple((side, bucket) for side, bucket in sides if side == args.only_side)
    for seed in args.seeds:
        for side, bucket in sides:
            if args.max_new_games > 0 and new_games_attempted >= args.max_new_games:
                print(f"reached max_new_games={args.max_new_games}; stopping early")
                break
            if (seed, side) in already_done:
                print(f"skip completed side={side} seed={seed} target_role={args.target_role}")
                continue
            print(f"running side={side} seed={seed} target_role={args.target_role}")
            new_games_attempted += 1
            run_started = time.perf_counter()
            try:
                result = run_target_game_with_optional_timeout(
                    seed=seed,
                    player_count=args.player_count,
                    max_days=args.max_days,
                    model_specs=model_specs,
                    baseline_framework=baseline_framework,
                    candidate_framework=candidate_framework,
                    target_role=args.target_role,
                    target_occurrence=args.target_occurrence,
                    side=side,
                    timeout_s=max(args.game_timeout_s, 0),
                )
            except Exception as exc:
                failure = build_failure_record(
                    exc,
                    seed=seed,
                    side=side,
                    target_role=args.target_role,
                    elapsed_s=round(time.perf_counter() - run_started, 3),
                    timeout_s=max(args.game_timeout_s, 0),
                )
                failures.append(failure)
                append_jsonl(failures_jsonl, failure)
                print(f"failed side={side} seed={seed}: {failure['error_type']} {failure['error']}")
                write_partial(
                    partial_path,
                    target_role=args.target_role,
                    baseline_results=baseline_results,
                    candidate_results=candidate_results,
                    failures=failures,
                    games_jsonl=games_jsonl,
                    failures_jsonl=failures_jsonl,
                    resume_from=args.resume_from,
                    append=bool(args.append),
                    game_timeout_s=max(args.game_timeout_s, 0),
                )
                continue
            row = asdict(result)
            bucket.append(row)
            already_done[(seed, side)] = row
            append_jsonl(games_jsonl, row)
            new_games_completed += 1
            write_partial(
                partial_path,
                target_role=args.target_role,
                baseline_results=baseline_results,
                candidate_results=candidate_results,
                failures=failures,
                games_jsonl=games_jsonl,
                failures_jsonl=failures_jsonl,
                resume_from=args.resume_from,
                append=bool(args.append),
                game_timeout_s=max(args.game_timeout_s, 0),
            )
        if args.max_new_games > 0 and new_games_attempted >= args.max_new_games:
            break

    comparison = compare_results(
        baseline_results,
        candidate_results,
        bootstrap_iterations=args.bootstrap_iterations,
        min_paired_seeds=args.min_paired_seeds,
        min_adjusted_score_delta=args.min_adjusted_score_delta,
        min_role_task_delta=args.min_role_task_delta,
        min_win_rate_delta=args.min_win_rate_delta,
        require_positive_ci=not args.allow_ci_cross_zero,
    )
    output = {
        "generated_at": utc_iso(),
        "elapsed_s": round(time.perf_counter() - started, 3),
        "runner": "target_seat_trackc_ab_experiment.py",
        "target_role": args.target_role,
        "target_occurrence": args.target_occurrence,
        "baseline_framework": baseline_framework.name,
        "candidate_framework": candidate_framework.name,
        "requested_seeds": list(args.seeds),
        "seeds": result_seeds(baseline_results, candidate_results),
        "player_count": args.player_count,
        "max_days": args.max_days,
        "model_pool": model_pool,
        "games_jsonl": str(games_jsonl),
        "failures_jsonl": str(failures_jsonl),
        "resume_from": str(args.resume_from) if args.resume_from else "",
        "append": bool(args.append),
        "game_timeout_s": max(args.game_timeout_s, 0),
        "max_new_games": max(args.max_new_games, 0),
        "only_side": args.only_side,
        "new_games_attempted": new_games_attempted,
        "new_games_completed": new_games_completed,
        "baseline_results": baseline_results,
        "candidate_results": candidate_results,
        "failures": failures,
        "comparison": comparison,
        "claim_boundary": (
            "仅当 comparison.acceptance.accepted=true 时，才能把本输出作为 Track C 单目标席位因果增益证据。"
            "否则只能报告 comparison.acceptance.claim_level，并将其作为阶段性或烟测证据。"
        ),
    }
    write_json(out, output)
    print(f"Wrote {out}")
    print(json.dumps(comparison, ensure_ascii=False, indent=2))
    release_output_file_lock(output_lock)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
