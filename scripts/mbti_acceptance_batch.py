"""Run controlled real-LLM MBTI coverage games.

The harness pins one target persona of each MBTI type into every game and
records target-player win-rate slices by MBTI, role, alignment, and their
cross products. Each game runs in a fresh subprocess with a hard timeout so
one hung remote LLM call cannot poison later seeds.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import traceback
from collections import Counter
from collections import defaultdict
from concurrent.futures import Future
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import as_completed
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HEALTH_DIR = ROOT / "data" / "health"
HEALTH_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_GAME_TIMEOUT_SECONDS = int(os.environ.get("EXPERIMENT_GAME_TIMEOUT_SECONDS", "1800") or "1800")

MBTI_TYPES = (
    "INTJ",
    "INTP",
    "ENTJ",
    "ENTP",
    "INFJ",
    "INFP",
    "ENFJ",
    "ENFP",
    "ISTJ",
    "ISFJ",
    "ESTJ",
    "ESFJ",
    "ISTP",
    "ISFP",
    "ESTP",
    "ESFP",
)


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def str_to_bool(value: str | bool | int) -> bool:
    return str(value).strip().lower() not in {"false", "0", "no", "off", ""}


def assert_remote_llm_provider(provider: str, model_pool: str) -> None:
    tokens = {provider.strip().lower()}
    tokens.update(part.split(":", 1)[0].strip().lower() for part in model_pool.split(",") if part.strip())
    if tokens & {"fake", "fake_llm", "offline_llm"} and not str_to_bool(os.environ.get("ALLOW_OFFLINE_FAKE_LLM", "0")):
        raise RuntimeError(
            "Offline fake LLM is not allowed for MBTI acceptance experiments. "
            "Use a real provider such as LLM_PROVIDER=weapi, or set "
            "ALLOW_OFFLINE_FAKE_LLM=1 only for CI/unit smoke."
        )


def configure_experiment_env() -> str:
    """Load .env and pin MODEL_POOL to the selected real provider."""
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
    provider = os.environ.get("LLM_PROVIDER", "").strip()
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


def _personas_by_mbti() -> dict[str, list[dict[str, Any]]]:
    from backend.agents.characters import PERSONA_POOL

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in PERSONA_POOL:
        mbti = str(entry.get("mbti") or "").upper()
        if mbti:
            grouped[mbti].append(dict(entry))
    missing = [mbti for mbti in MBTI_TYPES if not grouped.get(mbti)]
    if missing:
        raise RuntimeError(f"PERSONA_POOL missing MBTI types: {', '.join(missing)}")
    return grouped


def _roster_for_target(
    target_mbti: str,
    game_index: int,
    *,
    target_seat: int,
    player_count: int,
    grouped: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    from backend.agents.characters import PERSONA_POOL

    target_candidates = grouped[target_mbti]
    target = dict(target_candidates[game_index % len(target_candidates)])
    filler_pool = [dict(entry) for entry in PERSONA_POOL if entry["name"] != target["name"]]
    if not filler_pool:
        raise RuntimeError("PERSONA_POOL has no filler personas")

    roster: list[dict[str, Any]] = []
    offset = (game_index * 5 + MBTI_TYPES.index(target_mbti) * 3) % len(filler_pool)
    for seat in range(1, player_count + 1):
        if seat == target_seat:
            roster.append(target)
        else:
            roster.append(dict(filler_pool[(offset + seat) % len(filler_pool)]))
    return roster


def _record_is_fallback(record: Any) -> bool:
    parsed = record.parsed_action if isinstance(record.parsed_action, dict) else {}
    metadata = parsed.get("metadata") if isinstance(parsed.get("metadata"), dict) else {}
    return (
        bool(metadata.get("fallback"))
        or bool(metadata.get("fallback_used"))
        or bool(parsed.get("agent_fallback"))
        or str(metadata.get("source", "")).lower() == "fallback"
    )


def _record_is_llm(record: Any) -> bool:
    parsed = record.parsed_action if isinstance(record.parsed_action, dict) else {}
    metadata = parsed.get("metadata") if isinstance(parsed.get("metadata"), dict) else {}
    return str(metadata.get("source", "")).lower() == "llm" and not _record_is_fallback(record)


def play_one(
    seed: int,
    target_mbti: str,
    game_index: int,
    *,
    player_count: int = 7,
    strict_no_fallback: bool = True,
) -> dict[str, Any]:
    """Run one target-MBTI game in the current process."""
    from backend.agents.llm_agent import LLMAgent
    from backend.engine.game import WerewolfGame

    model_pool = configure_experiment_env()
    LLMAgent.STRICT_NO_FALLBACK = strict_no_fallback
    grouped = _personas_by_mbti()
    target_seat = (game_index % player_count) + 1
    roster = _roster_for_target(
        target_mbti,
        game_index,
        target_seat=target_seat,
        player_count=player_count,
        grouped=grouped,
    )
    started = time.perf_counter()
    game = WerewolfGame(seed=seed, player_count=player_count, sampled_personas=roster)
    state = game.play()
    duration = time.perf_counter() - started
    target_player = next(player for player in state.players if player.seat == target_seat)
    actual_mbti = str((target_player.persona or {}).get("mbti", "")).upper()
    if actual_mbti != target_mbti:
        raise RuntimeError(f"target MBTI mismatch: expected {target_mbti}, got {actual_mbti}")

    winner = state.winner.value if state.winner else None
    target_alignment = target_player.alignment.value
    decisions = list(state.decision_records)
    target_decisions = [record for record in decisions if record.player_id == target_player.id]
    fallback_decisions = sum(1 for record in decisions if _record_is_fallback(record))
    invalid_decisions = sum(1 for record in decisions if not getattr(record, "is_valid", True))
    player_fallback_count = sum(getattr(player, "fallback_count", 0) or 0 for player in state.players)
    fallback_count = fallback_decisions + player_fallback_count
    if strict_no_fallback and (fallback_count or invalid_decisions):
        raise RuntimeError(f"strict_no_fallback violation: fallback={fallback_count} invalid={invalid_decisions}")

    players = []
    for player in state.players:
        role = player.role.value
        alignment = player.alignment.value
        mbti = (player.persona or {}).get("mbti", "UNKNOWN")
        players.append(
            {
                "name": player.name,
                "seat": player.seat,
                "role": role,
                "alignment": alignment,
                "team": alignment,
                "mbti": mbti,
                "alive": player.alive,
                "won": alignment == winner,
            }
        )

    return {
        "seed": seed,
        "game_id": state.id,
        "target_mbti": target_mbti,
        "target_seat": target_seat,
        "target_player_id": target_player.id,
        "target_name": target_player.name,
        "target_role": target_player.role.value,
        "target_alignment": target_alignment,
        "target_won": winner == target_alignment,
        "target_alive": target_player.alive,
        "winner": winner,
        "days": state.day,
        "events": len(state.events),
        "decisions": len(decisions),
        "target_decisions": len(target_decisions),
        "llm_decisions": sum(1 for record in decisions if _record_is_llm(record)),
        "fallback_decisions": fallback_decisions,
        "player_fallback_count": player_fallback_count,
        "fallback_count": fallback_count,
        "invalid_decisions": invalid_decisions,
        "duration_s": round(duration, 2),
        "provider": os.environ.get("LLM_PROVIDER", ""),
        "model": current_model_name(),
        "model_pool": model_pool,
        "player_count": player_count,
        "strict_no_fallback": strict_no_fallback,
        "anti_patterns": str_to_bool(os.environ.get("COGNITIVE_ENABLE_ANTI_PATTERNS", "0")),
        "track_c": str_to_bool(os.environ.get("COGNITIVE_ENABLE_TRACK_C", "0")),
        **llm_runtime_config(),
        "players": players,
    }


def run_one_isolated(
    *,
    seed: int,
    target_mbti: str,
    game_index: int,
    batch_index: int,
    total: int,
    player_count: int,
    strict_no_fallback: bool,
    anti_patterns: bool,
    track_c: bool,
    game_timeout_s: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--single-game",
        "--single-seed",
        str(seed),
        "--target-mbti",
        target_mbti,
        "--game-index",
        str(game_index),
        "--player-count",
        str(player_count),
        "--strict-fallback",
        "true" if strict_no_fallback else "false",
        "--anti-patterns",
        "true" if anti_patterns else "false",
        "--track-c",
        "true" if track_c else "false",
    ]
    base = {
        "seed": seed,
        "target_mbti": target_mbti,
        "_batch_index": batch_index,
        "_total": total,
        "_at": utcnow_iso(),
    }
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            timeout=game_timeout_s if game_timeout_s > 0 else None,
        )
    except subprocess.TimeoutExpired:
        return {
            "failed": {
                **base,
                "error_type": "TimeoutError",
                "error_message": f"timeout after {game_timeout_s}s",
                "duration_s": round(time.perf_counter() - started, 1),
            }
        }

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout)[-1600:]
        return {
            "failed": {
                **base,
                "error_type": "ChildProcessError",
                "error_message": f"game child exited with code {proc.returncode}: {detail}",
                "duration_s": round(time.perf_counter() - started, 1),
            }
        }

    try:
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        metric = json.loads(lines[-1])
        metric["_batch_index"] = batch_index
        metric["_total"] = total
        metric["_at"] = utcnow_iso()
        return metric
    except Exception as exc:
        return {
            "failed": {
                **base,
                "error_type": type(exc).__name__,
                "error_message": f"single-game subprocess produced invalid JSON: {proc.stdout[-1600:]}",
                "duration_s": round(time.perf_counter() - started, 1),
            }
        }


def run_batch(
    games_per_mbti: int,
    seed_start: int,
    strict: bool,
    label: str,
    *,
    workers: int,
    fail_fast: bool,
    player_count: int,
    game_timeout_s: int,
    anti_patterns: bool,
    track_c: bool,
    output_dir: Path = HEALTH_DIR,
    append: bool = False,
    resume: bool = False,
) -> Path:
    from backend.agents.llm_agent import LLMAgent

    os.environ["COGNITIVE_ENABLE_ANTI_PATTERNS"] = "1" if anti_patterns else "0"
    os.environ["COGNITIVE_ENABLE_TRACK_C"] = "1" if track_c else "0"
    model_pool = configure_experiment_env()
    LLMAgent.STRICT_NO_FALLBACK = strict

    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / f"mbti_acceptance_{label}.jsonl"
    summary_path = output_dir / f"mbti_acceptance_{label}.summary.json"
    if not append:
        log_path.write_text("", encoding="utf-8")
    else:
        log_path.touch(exist_ok=True)

    existing_successes: list[dict[str, Any]] = []
    if append and resume and log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if "failed" not in row and row.get("target_mbti"):
                existing_successes.append(row)
    existing_by_mbti = Counter(row.get("target_mbti") for row in existing_successes)

    started_at = utcnow_iso()
    succeeded: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    jobs: list[dict[str, Any]] = []
    batch_index = 0
    for mbti in MBTI_TYPES:
        already_done = int(existing_by_mbti.get(mbti, 0) or 0)
        needed = max(0, games_per_mbti - already_done) if resume else games_per_mbti
        for local_index in range(already_done, already_done + needed):
            batch_index += 1
            jobs.append(
                {
                    "seed": seed_start + batch_index - 1,
                    "target_mbti": mbti,
                    "game_index": local_index,
                    "batch_index": batch_index,
                    "total": 0,
                    "player_count": player_count,
                    "strict_no_fallback": strict,
                    "anti_patterns": anti_patterns,
                    "track_c": track_c,
                    "game_timeout_s": game_timeout_s,
                }
            )
    total = len(jobs)
    for job in jobs:
        job["total"] = total
    print(
        f"[{started_at}] Starting MBTI acceptance: {len(MBTI_TYPES)} MBTI x "
        f"{games_per_mbti} target = {total} queued games, provider={os.environ.get('LLM_PROVIDER', '')}, "
        f"model={current_model_name()}, model_pool={model_pool}, workers={workers}, "
        f"strict={strict}, player_count={player_count}P, timeout={game_timeout_s}s, "
        f"append={append}, resume={resume}",
        flush=True,
    )

    raised: RuntimeError | None = None
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures: dict[Future[dict[str, Any]], dict[str, Any]] = {
            executor.submit(run_one_isolated, **job): job for job in jobs
        }
        for future in as_completed(futures):
            job = futures[future]
            try:
                row = future.result()
            except Exception as exc:
                row = {
                    "failed": {
                        "seed": job["seed"],
                        "target_mbti": job["target_mbti"],
                        "_batch_index": job["batch_index"],
                        "_total": total,
                        "_at": utcnow_iso(),
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                        "traceback": traceback.format_exc()[-1200:],
                    }
                }

            with log_path.open("a", encoding="utf-8") as logf:
                logf.write(json.dumps(row, ensure_ascii=False) + "\n")
                logf.flush()

            if "failed" in row:
                err = row["failed"]
                failed.append(err)
                print(
                    f"[{utcnow_iso()}] ({err.get('_batch_index')}/{total}) "
                    f"mbti={err.get('target_mbti')} seed={err.get('seed')} FAILED "
                    f"{err.get('error_type')}: {str(err.get('error_message', ''))[:240]}",
                    flush=True,
                )
                if fail_fast and raised is None:
                    raised = RuntimeError(str(err.get("error_message", "MBTI game failed")))
                    for pending in futures:
                        if not pending.done():
                            pending.cancel()
            else:
                succeeded.append(row)
                print(
                    f"[{utcnow_iso()}] ({row.get('_batch_index')}/{total}) "
                    f"mbti={row['target_mbti']} seed={row['seed']} winner={row.get('winner')} "
                    f"target={row.get('target_role')}/{row.get('target_alignment')} "
                    f"won={row.get('target_won')} llm/fb/invalid="
                    f"{row.get('llm_decisions', 0)}/{row.get('fallback_count', row.get('fallback_decisions', 0))}/"
                    f"{row.get('invalid_decisions', 0)} took={row.get('duration_s')}s",
                    flush=True,
                )
            if raised is not None:
                break

    summary = build_summary(
        label=label,
        started_at=started_at,
        succeeded=succeeded,
        failed=failed,
        log_path=log_path,
        games_per_mbti=games_per_mbti,
        player_count=player_count,
        strict_no_fallback=strict,
        workers=workers,
        fail_fast=fail_fast,
        game_timeout_s=game_timeout_s,
        anti_patterns=anti_patterns,
        track_c=track_c,
    )
    if append:
        summary = build_summary_from_log(
            label=label,
            started_at=started_at,
            log_path=log_path,
            games_per_mbti=games_per_mbti,
            player_count=player_count,
            strict_no_fallback=strict,
            workers=workers,
            fail_fast=fail_fast,
            game_timeout_s=game_timeout_s,
            anti_patterns=anti_patterns,
            track_c=track_c,
        )
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"\n[{summary['finished_at']}] MBTI acceptance done: "
        f"{summary['games_succeeded']}/{summary['games_requested']} ok. Summary: {summary_path}",
        flush=True,
    )
    if raised is not None:
        raise raised
    return summary_path


def _summary(
    label: str,
    started_at: str,
    succeeded: list[dict[str, Any]],
    failed: list[dict[str, Any]],
    log_path: Path | str,
    games_per_mbti: int,
) -> dict[str, Any]:
    """Compatibility wrapper used by tests and older scripts."""
    return build_summary(
        label=label,
        started_at=started_at,
        succeeded=succeeded,
        failed=failed,
        log_path=Path(log_path),
        games_per_mbti=games_per_mbti,
        player_count=7,
        strict_no_fallback=True,
        workers=1,
        fail_fast=False,
        game_timeout_s=DEFAULT_GAME_TIMEOUT_SECONDS,
        anti_patterns=str_to_bool(os.environ.get("COGNITIVE_ENABLE_ANTI_PATTERNS", "0")),
        track_c=str_to_bool(os.environ.get("COGNITIVE_ENABLE_TRACK_C", "0")),
    )


def build_summary_from_log(
    *,
    label: str,
    started_at: str,
    log_path: Path,
    games_per_mbti: int,
    player_count: int,
    strict_no_fallback: bool,
    workers: int,
    fail_fast: bool,
    game_timeout_s: int,
    anti_patterns: bool,
    track_c: bool,
) -> dict[str, Any]:
    succeeded: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if "failed" in row:
                failed.append(row["failed"])
            else:
                succeeded.append(row)
    summary = build_summary(
        label=label,
        started_at=started_at,
        succeeded=succeeded,
        failed=failed,
        log_path=log_path,
        games_per_mbti=games_per_mbti,
        player_count=player_count,
        strict_no_fallback=strict_no_fallback,
        workers=workers,
        fail_fast=fail_fast,
        game_timeout_s=game_timeout_s,
        anti_patterns=anti_patterns,
        track_c=track_c,
    )
    summary["summary_scope"] = "cumulative_log"
    summary["games_requested_this_run"] = len(MBTI_TYPES) * games_per_mbti
    return summary


def build_summary(
    *,
    label: str,
    started_at: str,
    succeeded: list[dict[str, Any]],
    failed: list[dict[str, Any]],
    log_path: Path,
    games_per_mbti: int,
    player_count: int,
    strict_no_fallback: bool,
    workers: int,
    fail_fast: bool,
    game_timeout_s: int,
    anti_patterns: bool,
    track_c: bool,
) -> dict[str, Any]:
    return {
        "batch_label": label,
        "started_at": started_at,
        "finished_at": utcnow_iso(),
        "provider": os.environ.get("LLM_PROVIDER", ""),
        "model": current_model_name(),
        "model_pool": os.environ.get("MODEL_POOL", ""),
        "player_count": player_count,
        "anti_patterns": anti_patterns,
        "track_c": track_c,
        "strict_no_fallback": strict_no_fallback,
        "workers": workers,
        "fail_fast": fail_fast,
        "game_timeout_s": game_timeout_s,
        **llm_runtime_config(),
        "games_requested": len(MBTI_TYPES) * games_per_mbti,
        "games_succeeded": len(succeeded),
        "games_failed": len(failed),
        "games_per_mbti": games_per_mbti,
        "winner_breakdown": dict(sorted(Counter(row.get("winner", "unknown") for row in succeeded).items())),
        "llm_decision_total": sum(int(row.get("llm_decisions", 0) or 0) for row in succeeded),
        "fallback_decision_total": sum(
            int(row.get("fallback_count", row.get("fallback_decisions", 0)) or 0) for row in succeeded
        ),
        "invalid_decision_total": sum(int(row.get("invalid_decisions", 0) or 0) for row in succeeded),
        "avg_duration_s": round(
            sum(float(row.get("duration_s", 0) or 0) for row in succeeded) / max(len(succeeded), 1),
            2,
        ),
        "mbti_stats": summarize_mbti_rows(succeeded, games_per_mbti),
        "role_stats": summarize_rows(succeeded, "target_role", "target_won"),
        "alignment_stats": summarize_rows(succeeded, "target_alignment", "target_won"),
        "mbti_role_stats": summarize_rows(succeeded, ("target_mbti", "target_role"), "target_won"),
        "mbti_alignment_stats": summarize_rows(succeeded, ("target_mbti", "target_alignment"), "target_won"),
        "errors": failed[:20],
        "log_path": str(log_path),
    }


def summarize_mbti_rows(rows: list[dict[str, Any]], expected_games: int) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for mbti in MBTI_TYPES:
        group = [row for row in rows if row.get("target_mbti") == mbti]
        role_counts = Counter(row.get("target_role", "UNKNOWN") for row in group)
        wins = sum(1 for row in group if row.get("target_won"))
        out[mbti] = {
            **stat(wins, len(group)),
            "expected_games": expected_games,
            "avg_target_decisions": round(
                sum(int(row.get("target_decisions", 0) or 0) for row in group) / max(len(group), 1),
                2,
            ),
            "role_counts": dict(sorted(role_counts.items())),
            "fallback_decisions": sum(
                int(row.get("fallback_count", row.get("fallback_decisions", 0)) or 0) for row in group
            ),
            "invalid_decisions": sum(int(row.get("invalid_decisions", 0) or 0) for row in group),
        }
    return out


def summarize_rows(
    rows: list[dict[str, Any]],
    key_fields: str | tuple[str, ...],
    win_field: str,
) -> dict[str, dict[str, Any]]:
    fields = (key_fields,) if isinstance(key_fields, str) else key_fields
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped["+".join(str(row.get(field, "UNKNOWN")) for field in fields)].append(row)

    out: dict[str, dict[str, Any]] = {}
    for key, group in sorted(grouped.items()):
        wins = sum(1 for row in group if row.get(win_field))
        out[key] = {
            **stat(wins, len(group)),
            "fallback_decisions": sum(
                int(row.get("fallback_count", row.get("fallback_decisions", 0)) or 0) for row in group
            ),
            "invalid_decisions": sum(int(row.get("invalid_decisions", 0) or 0) for row in group),
        }
    return out


def stat(wins: int, games: int) -> dict[str, Any]:
    return {
        "wins": wins,
        "games": games,
        "win_rate": round(wins / games, 4) if games else None,
        "wilson_95_ci": wilson_ci(wins, games),
    }


def wilson_ci(wins: int, games: int, z: float = 1.96) -> list[float | None]:
    if games <= 0:
        return [None, None]
    p = wins / games
    denom = 1 + z * z / games
    center = (p + z * z / (2 * games)) / denom
    margin = z * ((p * (1 - p) + z * z / (4 * games)) / games) ** 0.5 / denom
    return [round(max(0.0, center - margin), 4), round(min(1.0, center + margin), 4)]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run real-LLM MBTI acceptance games.")
    parser.add_argument("--games-per-mbti", type=int, default=20)
    parser.add_argument("--seed-start", type=int, default=9001)
    parser.add_argument("--strict-fallback", default="true")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--fail-fast", default="false")
    parser.add_argument("--label", default=None)
    parser.add_argument("--player-count", type=int, default=7)
    parser.add_argument("--game-timeout", type=int, default=DEFAULT_GAME_TIMEOUT_SECONDS)
    parser.add_argument("--anti-patterns", default=os.environ.get("COGNITIVE_ENABLE_ANTI_PATTERNS", "1"))
    parser.add_argument("--track-c", default=os.environ.get("COGNITIVE_ENABLE_TRACK_C", "1"))
    parser.add_argument("--output-dir", type=Path, default=HEALTH_DIR)
    parser.add_argument("--append", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--single-game", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--single-seed", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--target-mbti", choices=MBTI_TYPES, help=argparse.SUPPRESS)
    parser.add_argument("--game-index", type=int, default=0, help=argparse.SUPPRESS)
    args = parser.parse_args()

    strict = str_to_bool(args.strict_fallback)
    anti_patterns = str_to_bool(args.anti_patterns)
    track_c = str_to_bool(args.track_c)
    os.environ["COGNITIVE_ENABLE_ANTI_PATTERNS"] = "1" if anti_patterns else "0"
    os.environ["COGNITIVE_ENABLE_TRACK_C"] = "1" if track_c else "0"

    if args.single_game:
        if not args.target_mbti:
            raise SystemExit("--single-game requires --target-mbti")
        payload = play_one(
            args.single_seed,
            args.target_mbti,
            args.game_index,
            player_count=args.player_count,
            strict_no_fallback=strict,
        )
        print(json.dumps(payload, ensure_ascii=False), flush=True)
        return 0

    label = args.label or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_batch(
        args.games_per_mbti,
        args.seed_start,
        strict,
        label,
        workers=args.workers,
        fail_fast=str_to_bool(args.fail_fast),
        player_count=args.player_count,
        game_timeout_s=args.game_timeout,
        anti_patterns=anti_patterns,
        track_c=track_c,
        output_dir=args.output_dir,
        append=args.append,
        resume=args.resume,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
