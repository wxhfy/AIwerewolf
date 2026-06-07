"""Run auditable 7P multi-tier LLM Werewolf experiments.

Tiers:
  1. baseline     -- no anti-patterns, no Track C
  2. anti_only    -- static anti-patterns only
  3. trackc_only  -- Track C dynamic strategy only
  4. both         -- anti-patterns + Track C

Each tier runs in its own worker process.  Each game inside a worker runs in a
fresh subprocess with a hard timeout, so a hung game cannot poison later seeds.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import warnings
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")

TIERS: dict[str, dict[str, str]] = {
    "baseline": {"COGNITIVE_ENABLE_ANTI_PATTERNS": "0", "COGNITIVE_ENABLE_TRACK_C": "0"},
    "anti_only": {"COGNITIVE_ENABLE_ANTI_PATTERNS": "1", "COGNITIVE_ENABLE_TRACK_C": "0"},
    "trackc_only": {"COGNITIVE_ENABLE_ANTI_PATTERNS": "0", "COGNITIVE_ENABLE_TRACK_C": "1"},
    "both": {"COGNITIVE_ENABLE_ANTI_PATTERNS": "1", "COGNITIVE_ENABLE_TRACK_C": "1"},
}

DEFAULT_GAME_TIMEOUT_SECONDS = int(os.environ.get("EXPERIMENT_GAME_TIMEOUT_SECONDS", "1800") or "1800")


def str_to_bool(value: str) -> bool:
    return str(value).lower() not in {"false", "0", "no", "off"}


def assert_remote_llm_provider(provider: str, model_pool: str) -> None:
    """Refuse local deterministic fake models in experiment runs by default."""
    tokens = {provider.strip().lower()}
    tokens.update(part.split(":", 1)[0].strip().lower() for part in model_pool.split(",") if part.strip())
    if tokens & {"fake", "fake_llm", "offline_llm"} and not str_to_bool(os.environ.get("ALLOW_OFFLINE_FAKE_LLM", "0")):
        raise RuntimeError(
            "Offline fake LLM is not allowed for experiments. Use a real provider such as "
            "LLM_PROVIDER=weapi, or set ALLOW_OFFLINE_FAKE_LLM=1 only for CI/unit smoke."
        )


def configure_experiment_env() -> str:
    """Load .env and pin MODEL_POOL to the selected provider for auditability."""
    from backend.llm.env import load_env_file

    load_env_file()
    if (
        not os.environ.get("LLM_PROVIDER", "").strip()
        and not os.environ.get("EXPERIMENT_MODEL_POOL", "").strip()
        and os.environ.get("WEAPI_API_KEY", "").strip()
    ):
        os.environ["LLM_PROVIDER"] = "weapi"

    explicit_pool = os.environ.get("EXPERIMENT_MODEL_POOL", "").strip()
    if explicit_pool:
        os.environ["MODEL_POOL"] = explicit_pool
        assert_remote_llm_provider(os.environ.get("LLM_PROVIDER", ""), explicit_pool)
        return explicit_pool

    provider = os.environ.get("LLM_PROVIDER", "").strip().lower()
    if provider in {"weapi", "weapi_pw"}:
        model = os.environ.get("WEAPI_MODEL", "gpt-5.5").strip() or "gpt-5.5"
        pool = f"weapi:{model}"
    elif provider in {"fake", "fake_llm", "offline_llm"}:
        model = os.environ.get("FAKE_LLM_MODEL", "fake-llm").strip() or "fake-llm"
        pool = f"fake:{model}"
    else:
        pool = os.environ.get("MODEL_POOL", "").strip() or os.environ.get("DOUBAO_MODEL_POOL", "").strip()
        assert_remote_llm_provider(provider, pool)
        return pool

    os.environ["MODEL_POOL"] = pool
    assert_remote_llm_provider(provider, pool)
    return pool


def current_model_name() -> str:
    provider = os.environ.get("LLM_PROVIDER", "")
    provider_candidates = {
        "doubao": ["MODEL_POOL", "DOUBAO_MODEL_POOL", "DOUBAO_ENDPOINT", "DOUBAO_MODEL"],
        "deepseek": ["DEEPSEEK_MODEL"],
        "dsv4flash": ["DSV4FLASH_MODEL"],
        "ark": ["MODEL_POOL", "DOUBAO_MODEL_POOL", "ANTHROPIC_MODEL", "DSV4FLASH_MODEL"],
        "weapi": ["MODEL_POOL", "WEAPI_MODEL"],
        "fake": ["MODEL_POOL", "FAKE_LLM_MODEL"],
    }
    candidates = provider_candidates.get(provider, []) + [
        "MODEL_POOL",
        "DOUBAO_MODEL_POOL",
        "DEEPSEEK_MODEL",
        "DSV4FLASH_MODEL",
        "DOUBAO_ENDPOINT",
        "DOUBAO_MODEL",
        "WEAPI_MODEL",
        "FAKE_LLM_MODEL",
    ]
    seen: set[str] = set()
    for key in candidates:
        if key in seen:
            continue
        seen.add(key)
        value = os.environ.get(key, "").strip()
        if value:
            if provider and not value.lower().startswith(f"{provider}:"):
                return f"{provider}:{value}"
            return value
    return provider or "unknown"


def llm_runtime_config() -> dict[str, str]:
    return {
        "llm_timeout_seconds": os.environ.get("LLM_TIMEOUT_SECONDS", ""),
        "llm_max_retries": os.environ.get("LLM_MAX_RETRIES", ""),
    }


def record_is_fallback(record: Any) -> bool:
    parsed = record.parsed_action if isinstance(record.parsed_action, dict) else {}
    metadata = parsed.get("metadata") if isinstance(parsed.get("metadata"), dict) else {}
    return (
        bool(metadata.get("fallback"))
        or bool(metadata.get("fallback_used"))
        or bool(parsed.get("agent_fallback"))
        or str(metadata.get("source", "")).lower() == "fallback"
    )


def record_is_llm(record: Any) -> bool:
    parsed = record.parsed_action if isinstance(record.parsed_action, dict) else {}
    metadata = parsed.get("metadata") if isinstance(parsed.get("metadata"), dict) else {}
    return str(metadata.get("source", "")).lower() == "llm" and not record_is_fallback(record)


def init_strategy_snapshot(require_db: bool) -> dict[str, Any] | None:
    if not require_db:
        return None
    try:
        from backend.db.database import SessionLocal
        from backend.db.database import init_db

        init_db()
        db = SessionLocal()
        try:
            from sqlalchemy import func

            from backend.db.models import StrategyKnowledgeDoc

            q = db.query(func.count(StrategyKnowledgeDoc.id)).filter(StrategyKnowledgeDoc.status == "active")
            active_count = q.scalar()
            return {"active_count": active_count or 0, "timestamp": time.time()}
        finally:
            db.close()
    except Exception as exc:
        print(f"[worker] DB init failed (non-fatal): {exc}", flush=True)
        return {"active_count": -1, "timestamp": time.time(), "error": type(exc).__name__}


def play_game_payload(
    *,
    seed: int,
    tier: str,
    player_count: int,
    strict_no_fallback: bool,
) -> dict[str, Any]:
    """Run one game in the current process and return JSON-serializable metrics."""
    from backend.agents.llm_agent import LLMAgent
    from backend.engine.game import WerewolfGame

    for key, val in TIERS[tier].items():
        os.environ[key] = val
    LLMAgent.STRICT_NO_FALLBACK = strict_no_fallback
    configure_experiment_env()
    started = time.perf_counter()
    game = WerewolfGame(seed=seed, player_count=player_count)
    try:
        state = game.play()
    except Exception as exc:
        state = game.state
        payload = build_game_metrics_payload(state, started)
        payload["error"] = str(exc)
        payload["error_type"] = type(exc).__name__
        payload["traceback"] = traceback_tail()
        return payload
    return build_game_metrics_payload(state, started)


def build_game_metrics_payload(state: Any, started: float) -> dict[str, Any]:
    """Build serializable game metrics from completed or failed game state."""
    winner = state.winner.value if hasattr(state.winner, "value") else str(state.winner)
    decisions = list(getattr(state, "decision_records", []) or [])
    fallback_decisions = sum(1 for record in decisions if record_is_fallback(record))
    invalid_decisions = sum(1 for record in decisions if not getattr(record, "is_valid", True))
    player_fallback_count = sum(getattr(player, "fallback_count", 0) or 0 for player in state.players)
    players = []
    for player in state.players:
        role = player.role.value
        team = "wolf" if role in {"Werewolf", "WhiteWolfKing"} else "village"
        mbti = (player.persona or {}).get("mbti", "UNKNOWN") if hasattr(player, "persona") else "UNKNOWN"
        players.append(
            {
                "name": player.name,
                "seat": player.seat,
                "role": role,
                "team": team,
                "mbti": mbti,
                "alive": player.alive,
                "won": team == winner,
            }
        )
    return {
        "winner": winner,
        "days": state.day,
        "duration_s": round(time.perf_counter() - started, 1),
        "game_id": getattr(state, "id", "") or "",
        "decisions": len(decisions),
        "llm_decisions": sum(1 for record in decisions if record_is_llm(record)),
        "fallback_decisions": fallback_decisions,
        "invalid_decisions": invalid_decisions,
        "player_fallback_count": player_fallback_count,
        "fallback_count": fallback_decisions + player_fallback_count,
        "players": players,
    }


def run_game_isolated(
    *,
    seed: int,
    tier: str,
    player_count: int,
    strict_no_fallback: bool,
    game_timeout_s: int,
) -> dict[str, Any]:
    """Run one game in a fresh subprocess with a hard timeout."""
    if game_timeout_s <= 0:
        return play_game_payload(
            seed=seed,
            tier=tier,
            player_count=player_count,
            strict_no_fallback=strict_no_fallback,
        )

    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--single-game",
        "--tier",
        tier,
        "--single-seed",
        str(seed),
        "--player-count",
        str(player_count),
        "--strict-fallback",
        "true" if strict_no_fallback else "false",
    ]
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            timeout=game_timeout_s,
        )
    except subprocess.TimeoutExpired:
        return empty_error_result("TimeoutError", f"timeout after {game_timeout_s}s", started)

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout)[-1000:]
        return empty_error_result(
            "ChildProcessError", f"game child exited with code {proc.returncode}: {detail}", started
        )
    try:
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        return json.loads(lines[-1])
    except Exception:
        return empty_error_result(
            "JSONDecodeError", f"single-game subprocess produced invalid JSON: {proc.stdout[-1000:]}", started
        )


def empty_error_result(error_type: str, message: str, started: float) -> dict[str, Any]:
    return {
        "error": message,
        "error_type": error_type,
        "duration_s": round(time.perf_counter() - started, 1),
        "decisions": 0,
        "llm_decisions": 0,
        "fallback_decisions": 0,
        "invalid_decisions": 0,
        "player_fallback_count": 0,
        "fallback_count": 0,
        "players": [],
    }


def traceback_tail() -> str:
    import traceback

    return traceback.format_exc()[-1200:]


def run_worker(
    *,
    tier: str,
    seeds: list[int],
    output_file: Path,
    experiment_id: str,
    require_db: bool,
    strict_no_fallback: bool,
    player_count: int,
    game_timeout_s: int,
) -> int:
    from backend.agents.llm_agent import LLMAgent

    for key, val in TIERS[tier].items():
        os.environ[key] = val
    os.environ["EXPERIMENT_ID"] = experiment_id
    os.environ["TIER_EXPERIMENT_ID"] = f"{experiment_id}_{tier}"
    os.environ["DB_POOL_SIZE"] = "1"
    os.environ["DB_MAX_OVERFLOW"] = "0"
    LLMAgent.STRICT_NO_FALLBACK = strict_no_fallback
    model_pool = configure_experiment_env()
    strategy_snapshot = init_strategy_snapshot(require_db)
    if strategy_snapshot:
        print(f"[{tier}] strategy_snapshot={strategy_snapshot}", flush=True)

    output_file.parent.mkdir(parents=True, exist_ok=True)
    for index, seed in enumerate(seeds, start=1):
        started = time.perf_counter()
        result: dict[str, Any] = {
            "seed": seed,
            "tier": tier,
            "index": index,
            "total": len(seeds),
            "experiment_id": experiment_id,
            "player_count": player_count,
            "provider": os.environ.get("LLM_PROVIDER", ""),
            "model": current_model_name(),
            "model_pool": model_pool,
            "strict_no_fallback": strict_no_fallback,
            "game_timeout_s": game_timeout_s,
            **llm_runtime_config(),
        }
        if strategy_snapshot:
            result["strategy_snapshot"] = strategy_snapshot
        try:
            result.update(
                run_game_isolated(
                    seed=seed,
                    tier=tier,
                    player_count=player_count,
                    strict_no_fallback=strict_no_fallback,
                    game_timeout_s=game_timeout_s,
                )
            )
            if "error" in result:
                raise RuntimeError(str(result["error"]))
            invalid_decisions = int(result.get("invalid_decisions", 0) or 0)
            if strict_no_fallback and (result["fallback_count"] or invalid_decisions):
                raise RuntimeError(
                    f"strict_no_fallback violation: fallback={result['fallback_count']} invalid={invalid_decisions}"
                )
            print(
                f"[{tier}] {index}/{len(seeds)} seed={seed} winner={result.get('winner')} "
                f"days={result.get('days')} time={result['duration_s']:.0f}s "
                f"decisions={result.get('decisions', 0)} "
                f"llm={result['llm_decisions']} fb={result['fallback_count']} invalid={invalid_decisions}",
                flush=True,
            )
        except Exception as exc:
            result["error"] = str(exc)
            result["traceback"] = traceback_tail()
            result["duration_s"] = round(time.perf_counter() - started, 1)
            print(f"[{tier}] {index}/{len(seeds)} seed={seed} FAILED: {type(exc).__name__}: {exc}", flush=True)

        with output_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(result, ensure_ascii=False) + "\n")
    print(f"DONE_{tier}", flush=True)
    return 0


def launch_worker(
    *,
    tier: str,
    seeds: list[int],
    output_file: Path,
    experiment_id: str,
    require_db: bool,
    strict_no_fallback: bool,
    player_count: int,
    game_timeout_s: int,
) -> subprocess.Popen:
    child_env = os.environ.copy()
    return subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--worker",
            "--tier",
            tier,
            "--seeds-json",
            json.dumps(seeds),
            "--output-file",
            str(output_file),
            "--experiment-id",
            experiment_id,
            "--require-db",
            "true" if require_db else "false",
            "--strict-fallback",
            "true" if strict_no_fallback else "false",
            "--player-count",
            str(player_count),
            "--game-timeout",
            str(game_timeout_s),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=child_env,
        cwd=str(ROOT),
    )


def format_stats(raw: dict[str, dict[str, int]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for key, item in sorted(raw.items()):
        games = item["games"]
        wins = item["wins"]
        out[key] = {"games": games, "wins": wins, "win_rate": round(wins / games, 4) if games else None}
    return out


def compile_stats(results: list[dict[str, Any]]) -> dict[str, Any]:
    role_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"wins": 0, "games": 0})
    mbti_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"wins": 0, "games": 0})
    team_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"wins": 0, "games": 0})
    mbti_role_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"wins": 0, "games": 0})
    mbti_team_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"wins": 0, "games": 0})

    for row in results:
        if "error" in row:
            continue
        for player in row.get("players", []):
            role = player.get("role", "UNKNOWN")
            team = player.get("team") or ("wolf" if role in {"Werewolf", "WhiteWolfKing"} else "village")
            mbti = player.get("mbti", "UNKNOWN")
            won = bool(player.get("won"))
            for bucket, key in (
                (role_stats, role),
                (mbti_stats, mbti),
                (team_stats, team),
                (mbti_role_stats, f"{mbti}+{role}"),
                (mbti_team_stats, f"{mbti}+{team}"),
            ):
                bucket[key]["wins"] += 1 if won else 0
                bucket[key]["games"] += 1

    return {
        "role_stats": format_stats(role_stats),
        "mbti_stats": format_stats(mbti_stats),
        "team_stats": format_stats(team_stats),
        "mbti_role_stats": format_stats(mbti_role_stats),
        "mbti_team_stats": format_stats(mbti_team_stats),
    }


def format_pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.1%}"


def print_comparison(tier_summaries: dict[str, Any]) -> None:
    tiers = list(tier_summaries.keys())
    print(f"\n{'=' * 110}")
    print("MULTI-TIER WIN RATE COMPARISON")
    print(f"{'=' * 110}")
    print("\n--- Team-Level Win Rates ---")
    print(f"{'Team':<12s}" + "".join(f" {tier:>18s}" for tier in tiers))
    print("-" * 90)
    for team in ("village", "wolf"):
        row = f"{team:<12s}"
        for tier in tiers:
            stats = tier_summaries[tier].get("team_stats", {}).get(team, {})
            row += f" {format_pct(stats.get('win_rate')):>8s} ({stats.get('games', 0):>3d}p)"
        print(row)
    print("\n--- Meta ---")
    for metric in ("game_count", "error_count", "avg_duration_s", "total_llm_decisions", "total_fallbacks"):
        row = f"{metric:<20s}"
        for tier in tiers:
            row += f" {str(tier_summaries[tier].get(metric, '-')):>18s}"
        print(row)
    print(f"{'=' * 110}")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def selected_tiers(raw: str) -> list[str]:
    if not raw.strip() or raw.strip().lower() == "all":
        return list(TIERS)
    tiers = [item.strip() for item in raw.split(",") if item.strip()]
    unknown = [tier for tier in tiers if tier not in TIERS]
    if unknown:
        raise ValueError(f"Unknown tier(s): {', '.join(unknown)}")
    return tiers


def run_experiment(
    *,
    n_games: int,
    seed_start: int,
    tiers_to_run: list[str],
    require_db: bool,
    strict_no_fallback: bool,
    player_count: int,
    game_timeout_s: int,
    label: str,
    output_dir: Path | None,
    append: bool,
) -> Path:
    configure_experiment_env()
    experiment_id = f"exp-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    if output_dir is None:
        base_dir = ROOT / "data" / "experiment" / "multi_tier"
        output_dir = base_dir / label if label else base_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_file = output_dir / "summary.json"

    print(f"{'=' * 70}")
    print(f"Multi-Tier Experiment: {n_games} games x {len(tiers_to_run)} tiers = {n_games * len(tiers_to_run)} total")
    print(f"Experiment ID: {experiment_id}")
    print(f"Label: {label or '(default)'}")
    print(f"Started: {datetime.now()}")
    print("Mode: tier subprocesses; each game isolated in a subprocess")
    print(f"Tiers: {tiers_to_run}")
    print(f"Player count: {player_count}P")
    print(f"Require DB: {require_db}")
    print(f"Strict no fallback: {strict_no_fallback}")
    print(f"Per-game timeout: {game_timeout_s}s")
    print(f"Provider: {os.environ.get('LLM_PROVIDER', '') or '(default)'}")
    print(f"Model: {current_model_name()}")
    print(f"{'=' * 70}")

    processes: dict[str, subprocess.Popen] = {}
    seeds = [seed_start + i for i in range(n_games)]
    for tier in tiers_to_run:
        out_file = output_dir / f"{tier}.jsonl"
        if not append:
            out_file.write_text("", encoding="utf-8")
        else:
            out_file.touch(exist_ok=True)
        processes[tier] = launch_worker(
            tier=tier,
            seeds=seeds,
            output_file=out_file,
            experiment_id=experiment_id,
            require_db=require_db,
            strict_no_fallback=strict_no_fallback,
            player_count=player_count,
            game_timeout_s=game_timeout_s,
        )
        print(f"  Started [{tier}] PID={processes[tier].pid} ({n_games} games, seeds {seeds[0]}-{seeds[-1]})")

    exit_codes = monitor_processes(processes)

    tier_summaries: dict[str, Any] = {}
    all_results: dict[str, list[dict[str, Any]]] = {}
    for tier in TIERS:
        results = read_jsonl(output_dir / f"{tier}.jsonl")
        all_results[tier] = results
        summary = compile_stats(results)
        completed = [row for row in results if "error" not in row]
        failed = [row for row in results if "error" in row]
        durations = [float(row.get("duration_s", 0) or 0) for row in completed]
        summary.update(
            {
                "game_count": len(completed),
                "error_count": len(failed),
                "avg_duration_s": round(sum(durations) / max(len(durations), 1), 1),
                "total_fallbacks": sum(int(row.get("fallback_count", 0) or 0) for row in completed),
                "total_llm_decisions": sum(int(row.get("llm_decisions", 0) or 0) for row in completed),
                "total_invalid_decisions": sum(int(row.get("invalid_decisions", 0) or 0) for row in completed),
            }
        )
        tier_summaries[tier] = summary

    combined_file = output_dir / "results.jsonl"
    with combined_file.open("w", encoding="utf-8") as handle:
        for tier in TIERS:
            for row in all_results[tier]:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    summary_payload = {
        "experiment_id": experiment_id,
        "label": label,
        "completed_at": datetime.now().isoformat(),
        "games_per_tier_requested_this_run": n_games,
        "total_games_requested_this_run": n_games * len(tiers_to_run),
        "seed_start": seed_start,
        "seeds": seeds,
        "tiers_run_this_invocation": tiers_to_run,
        "mode": "tier subprocesses; each game isolated in a subprocess",
        "require_db": require_db,
        "strict_no_fallback": strict_no_fallback,
        "player_count": player_count,
        "game_timeout_s": game_timeout_s,
        "provider": os.environ.get("LLM_PROVIDER", ""),
        "model": current_model_name(),
        "model_pool": os.environ.get("MODEL_POOL", ""),
        **llm_runtime_config(),
        "worker_exit_codes": exit_codes,
        "tiers": tier_summaries,
    }
    summary_file.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print_comparison(tier_summaries)
    print(f"\nSummary: {summary_file}")
    nonzero = {tier: code for tier, code in exit_codes.items() if code not in (0, None)}
    if nonzero:
        raise RuntimeError(f"tier workers failed: {nonzero}")
    return summary_file


def monitor_processes(processes: dict[str, subprocess.Popen]) -> dict[str, int | None]:
    import queue
    import threading

    output_queue: queue.Queue[tuple[str, str]] = queue.Queue()

    def reader(proc: subprocess.Popen, tier_name: str) -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            output_queue.put((tier_name, line.rstrip()))

    threads = [threading.Thread(target=reader, args=(proc, tier), daemon=True) for tier, proc in processes.items()]
    for thread in threads:
        thread.start()

    started = time.perf_counter()
    while any(proc.poll() is None for proc in processes.values()):
        try:
            _tier, line = output_queue.get(timeout=5)
            print(f"  {line}", flush=True)
        except queue.Empty:
            running = [tier for tier, proc in processes.items() if proc.poll() is None]
            if running:
                print(f"  [heartbeat] {time.perf_counter() - started:.0f}s running: {running}", flush=True)

    for thread in threads:
        thread.join(timeout=2)
    while not output_queue.empty():
        _tier, line = output_queue.get_nowait()
        print(f"  {line}", flush=True)
    return {tier: proc.returncode for tier, proc in processes.items()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--games", type=int, default=12)
    parser.add_argument("--seed-start", type=int, default=1000)
    parser.add_argument("--tiers", default="all")
    parser.add_argument("--label", default="")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--append", action="store_true")
    parser.add_argument("--player-count", type=int, default=7)
    parser.add_argument("--game-timeout", type=int, default=DEFAULT_GAME_TIMEOUT_SECONDS)
    parser.add_argument("--strict-fallback", default="true")
    parser.add_argument("--no-db", action="store_true")
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--single-game", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--single-seed", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--tier", choices=tuple(TIERS))
    parser.add_argument("--seeds-json", default="[]")
    parser.add_argument("--output-file", type=Path)
    parser.add_argument("--experiment-id", default="")
    parser.add_argument("--require-db", default="true")
    args = parser.parse_args()

    if args.single_game:
        if not args.tier:
            raise SystemExit("--single-game requires --tier")
        payload = play_game_payload(
            seed=args.single_seed,
            tier=args.tier,
            player_count=args.player_count,
            strict_no_fallback=str_to_bool(args.strict_fallback),
        )
        print(json.dumps(payload, ensure_ascii=False), flush=True)
        return 0

    if args.worker:
        if not args.tier or not args.output_file or not args.experiment_id:
            raise SystemExit("--worker requires --tier, --output-file, and --experiment-id")
        return run_worker(
            tier=args.tier,
            seeds=[int(seed) for seed in json.loads(args.seeds_json)],
            output_file=args.output_file,
            experiment_id=args.experiment_id,
            require_db=str_to_bool(args.require_db),
            strict_no_fallback=str_to_bool(args.strict_fallback),
            player_count=args.player_count,
            game_timeout_s=args.game_timeout,
        )

    run_experiment(
        n_games=args.games,
        seed_start=args.seed_start,
        tiers_to_run=selected_tiers(args.tiers),
        require_db=not args.no_db,
        strict_no_fallback=str_to_bool(args.strict_fallback),
        player_count=args.player_count,
        game_timeout_s=args.game_timeout,
        label=args.label,
        output_dir=args.output_dir,
        append=args.append,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
