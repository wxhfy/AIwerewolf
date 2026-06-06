"""Run controlled LLM-only MBTI coverage games.

This acceptance harness runs 20 games for each of the 16 MBTI types by
pinning one target persona of that MBTI into every game. Other seats are
filled from the persona pool. All AI seats still use the normal LLM-compatible
agent factory; no heuristic agent is created.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from collections import Counter
from collections import defaultdict
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.agents.characters import PERSONA_POOL
from backend.agents.llm_agent import LLMAgent
from backend.engine.game import WerewolfGame

HEALTH_DIR = ROOT / "data" / "health"
HEALTH_DIR.mkdir(parents=True, exist_ok=True)

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


def _personas_by_mbti() -> dict[str, list[dict[str, Any]]]:
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
    grouped: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    target_candidates = grouped[target_mbti]
    target = dict(target_candidates[game_index % len(target_candidates)])
    roster: list[dict[str, Any]] = []
    filler_pool = [dict(entry) for entry in PERSONA_POOL if entry["name"] != target["name"]]
    offset = (game_index * 5) % len(filler_pool)
    for seat in range(1, 8):
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
        or bool(parsed.get("agent_fallback"))
        or str(metadata.get("source", "")).lower() == "fallback"
    )


def _record_is_llm(record: Any) -> bool:
    parsed = record.parsed_action if isinstance(record.parsed_action, dict) else {}
    metadata = parsed.get("metadata") if isinstance(parsed.get("metadata"), dict) else {}
    return str(metadata.get("source", "")).lower() == "llm"


def play_one(seed: int, target_mbti: str, game_index: int) -> dict[str, Any]:
    grouped = _personas_by_mbti()
    target_seat = (game_index % 7) + 1
    roster = _roster_for_target(target_mbti, game_index, target_seat=target_seat, grouped=grouped)
    started = time.time()
    game = WerewolfGame(seed=seed, player_count=7, sampled_personas=roster)
    state = game.play()
    duration = time.time() - started
    target_player = next(player for player in state.players if player.seat == target_seat)
    if str((target_player.persona or {}).get("mbti", "")).upper() != target_mbti:
        raise RuntimeError(
            f"target MBTI mismatch: expected {target_mbti}, got {(target_player.persona or {}).get('mbti')}"
        )
    winner = state.winner.value if state.winner else None
    target_team = target_player.alignment.value
    decisions = list(state.decision_records)
    target_decisions = [record for record in decisions if record.player_id == target_player.id]
    return {
        "seed": seed,
        "game_id": state.id,
        "target_mbti": target_mbti,
        "target_seat": target_seat,
        "target_player_id": target_player.id,
        "target_name": target_player.name,
        "target_role": target_player.role.value,
        "target_alignment": target_team,
        "target_won": winner == target_team,
        "target_alive": target_player.alive,
        "winner": winner,
        "days": state.day,
        "events": len(state.events),
        "decisions": len(decisions),
        "target_decisions": len(target_decisions),
        "llm_decisions": sum(1 for record in decisions if _record_is_llm(record)),
        "fallback_decisions": sum(1 for record in decisions if _record_is_fallback(record)),
        "invalid_decisions": sum(1 for record in decisions if not record.is_valid),
        "duration_s": round(duration, 2),
    }


def run_batch(games_per_mbti: int, seed_start: int, strict: bool, label: str) -> Path:
    os.environ.setdefault("LLM_PROVIDER", "fake")
    LLMAgent.STRICT_NO_FALLBACK = strict
    total = games_per_mbti * len(MBTI_TYPES)
    log_path = HEALTH_DIR / f"mbti_acceptance_{label}.jsonl"
    summary_path = HEALTH_DIR / f"mbti_acceptance_{label}.summary.json"
    started_at = utcnow_iso()
    succeeded: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    print(
        f"[{started_at}] Starting MBTI acceptance — "
        f"{len(MBTI_TYPES)} MBTI × {games_per_mbti} = {total} games, strict={strict}",
        flush=True,
    )
    with open(log_path, "a", encoding="utf-8") as logf:
        index = 0
        for mbti in MBTI_TYPES:
            for local_index in range(games_per_mbti):
                index += 1
                seed = seed_start + index - 1
                print(f"[{utcnow_iso()}] ({index}/{total}) mbti={mbti} seed={seed} starting", flush=True)
                try:
                    metric = play_one(seed, mbti, local_index)
                    metric["_batch_index"] = index
                    metric["_at"] = utcnow_iso()
                    logf.write(json.dumps(metric, ensure_ascii=False) + "\n")
                    logf.flush()
                    succeeded.append(metric)
                    print(
                        f"  ✓ winner={metric['winner']} target={metric['target_role']} "
                        f"won={metric['target_won']} llm/fallback="
                        f"{metric['llm_decisions']}/{metric['fallback_decisions']} "
                        f"took={metric['duration_s']}s",
                        flush=True,
                    )
                except Exception as exc:
                    err = {
                        "seed": seed,
                        "target_mbti": mbti,
                        "_batch_index": index,
                        "_at": utcnow_iso(),
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                        "traceback": traceback.format_exc()[-1200:],
                    }
                    logf.write(json.dumps({"failed": err}, ensure_ascii=False) + "\n")
                    logf.flush()
                    failed.append(err)
                    traceback.print_exc()
                    print(f"  ✗ FAILED: {type(exc).__name__}: {exc}", flush=True)
                    if strict:
                        raise
    summary = _summary(label, started_at, succeeded, failed, log_path, games_per_mbti)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"\n[{summary['finished_at']}] MBTI acceptance done — "
        f"{summary['games_succeeded']}/{summary['games_requested']} ok. "
        f"Summary: {summary_path}",
        flush=True,
    )
    return summary_path


def _summary(
    label: str,
    started_at: str,
    succeeded: list[dict[str, Any]],
    failed: list[dict[str, Any]],
    log_path: Path,
    games_per_mbti: int,
) -> dict[str, Any]:
    mbti_stats: dict[str, dict[str, Any]] = {}
    for mbti in MBTI_TYPES:
        rows = [row for row in succeeded if row["target_mbti"] == mbti]
        role_counts = Counter(row["target_role"] for row in rows)
        mbti_stats[mbti] = {
            "games": len(rows),
            "expected_games": games_per_mbti,
            "wins": sum(1 for row in rows if row["target_won"]),
            "win_rate": round(sum(1 for row in rows if row["target_won"]) / max(len(rows), 1), 4),
            "avg_target_decisions": round(sum(row["target_decisions"] for row in rows) / max(len(rows), 1), 2),
            "role_counts": dict(sorted(role_counts.items())),
            "fallback_decisions": sum(row["fallback_decisions"] for row in rows),
            "invalid_decisions": sum(row["invalid_decisions"] for row in rows),
        }
    return {
        "batch_label": label,
        "started_at": started_at,
        "finished_at": utcnow_iso(),
        "provider": os.environ.get("LLM_PROVIDER", ""),
        "games_requested": len(MBTI_TYPES) * games_per_mbti,
        "games_succeeded": len(succeeded),
        "games_failed": len(failed),
        "games_per_mbti": games_per_mbti,
        "winner_breakdown": dict(Counter(row["winner"] for row in succeeded)),
        "llm_decision_total": sum(row["llm_decisions"] for row in succeeded),
        "fallback_decision_total": sum(row["fallback_decisions"] for row in succeeded),
        "invalid_decision_total": sum(row["invalid_decisions"] for row in succeeded),
        "avg_duration_s": round(sum(row["duration_s"] for row in succeeded) / max(len(succeeded), 1), 2),
        "mbti_stats": mbti_stats,
        "errors": failed[:20],
        "log_path": str(log_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--games-per-mbti", type=int, default=20)
    parser.add_argument("--seed-start", type=int, default=9001)
    parser.add_argument("--strict-fallback", default="true")
    parser.add_argument("--label", default=None)
    args = parser.parse_args()
    strict = args.strict_fallback.lower() not in {"false", "0", "no", "off"}
    label = args.label or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_batch(args.games_per_mbti, args.seed_start, strict, label)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
