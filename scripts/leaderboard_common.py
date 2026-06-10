#!/usr/bin/env python3
"""Shared aggregation helpers for experiment leaderboards.

The primary source is every ``outputs/exp_*/game_runs.jsonl`` file. Adjacent
``group_results.csv`` files are used only to enrich score dimensions that are
not present in the raw game-run records.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from collections import defaultdict
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
OUTPUTS_DIR = ROOT / "outputs"

ROLE_ORDER = ["Werewolf", "WhiteWolfKing", "Seer", "Witch", "Hunter", "Guard", "Idiot", "Villager"]
SCORE_FIELDS = {
    "avg_adjusted_final_score": "avg_score",
    "avg_final_score": "avg_final_score",
    "avg_vote_score": "avg_vote_score",
    "avg_speech_score": "avg_speech_score",
    "avg_skill_score": "avg_skill_score",
}


@dataclass
class ModelAccumulator:
    model: str
    seat_samples: int = 0
    wins: int = 0
    games: set[str] = field(default_factory=set)
    experiments: set[str] = field(default_factory=set)
    roles: Counter[str] = field(default_factory=Counter)
    role_wins: Counter[str] = field(default_factory=Counter)
    alignments: Counter[str] = field(default_factory=Counter)
    score_weight: Counter[str] = field(default_factory=Counter)
    score_samples: int = 0
    decision_count: float = 0.0
    fallback_count: float = 0.0
    invalid_count: float = 0.0
    retrieved_count: float = 0.0


@dataclass
class RoleAccumulator:
    role: str
    samples: int = 0
    wins: int = 0
    models: Counter[str] = field(default_factory=Counter)
    alignments: Counter[str] = field(default_factory=Counter)


def utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path)


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def round6(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 6)


def parse_json_field(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def discover_game_run_paths(outputs_dir: Path = OUTPUTS_DIR) -> list[Path]:
    return sorted(path for path in outputs_dir.glob("exp_*/game_runs.jsonl") if path.is_file())


def read_jsonl(path: Path) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    skipped = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                skipped += 1
                continue
            if isinstance(parsed, dict):
                rows.append(parsed)
            else:
                skipped += 1
    return rows, skipped


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def canonical_model(value: Any) -> str:
    text = str(value or "").strip()
    if text.startswith("model:"):
        text = text[len("model:") :]
    return text or "unknown"


def model_suffix(label: str) -> str:
    return label.split(":", 1)[1] if ":" in label else label


def match_model_label(raw_key: str, known_labels: set[str]) -> str:
    key = canonical_model(raw_key)
    if key in known_labels:
        return key
    matches = [label for label in known_labels if model_suffix(label) == key]
    if len(matches) == 1:
        return matches[0]
    return key


def winner_matches_alignment(winner: Any, alignment: Any) -> bool:
    winner_text = str(winner or "").strip().lower()
    alignment_text = str(alignment or "").strip().lower()
    if not winner_text or not alignment_text:
        return False
    if winner_text in {"village", "villager", "villagers", "good", "human"}:
        return alignment_text in {"village", "villager", "villagers", "good", "human"}
    if winner_text in {"wolf", "werewolf", "werewolves", "wolves"}:
        return alignment_text in {"wolf", "werewolf", "werewolves", "wolves"}
    return winner_text == alignment_text


def score_value(score: dict[str, Any], field_name: str) -> float | None:
    aliases = {
        "avg_score": ["adjusted_final_score", "final_score", "process_score"],
        "avg_final_score": ["final_score", "adjusted_final_score", "process_score"],
        "avg_vote_score": ["vote_score"],
        "avg_speech_score": ["speech_score"],
        "avg_skill_score": ["skill_score"],
    }
    for key in aliases[field_name]:
        if key in score:
            return as_float(score.get(key))
    return None


def add_score_sample(acc: ModelAccumulator, score: dict[str, Any], weight: int = 1) -> None:
    if weight <= 0:
        return
    captured = False
    for output_field in SCORE_FIELDS.values():
        value = score_value(score, output_field)
        if value is not None:
            acc.score_weight[output_field] += value * weight
            captured = True
    if captured:
        acc.score_samples += weight


def add_group_score_sample(acc: ModelAccumulator, row: dict[str, str]) -> None:
    players = max(as_int(row.get("players"), 0), 0)
    if players <= 0:
        return
    captured = False
    for input_field, output_field in SCORE_FIELDS.items():
        if input_field in row:
            acc.score_weight[output_field] += as_float(row.get(input_field)) * players
            captured = True
    if captured:
        acc.score_samples += players


def score_averages(acc: ModelAccumulator) -> dict[str, float | None]:
    if acc.score_samples <= 0:
        return dict.fromkeys(SCORE_FIELDS.values(), None)
    return {
        field_name: round6(acc.score_weight.get(field_name, 0.0) / acc.score_samples)
        for field_name in SCORE_FIELDS.values()
    }


def role_sort_key(role: str) -> tuple[int, str]:
    if role in ROLE_ORDER:
        return (ROLE_ORDER.index(role), role)
    return (len(ROLE_ORDER), role)


def model_sort_key(row: dict[str, Any]) -> tuple[float, float, float, str]:
    return (
        -as_float(row.get("win_rate")),
        -as_float(row.get("avg_score")),
        as_float(row.get("fallback_rate")),
        str(row.get("model", "")),
    )


def update_health_from_game(
    row: dict[str, Any],
    model_accs: dict[str, ModelAccumulator],
    known_labels: set[str],
) -> None:
    total_decisions = as_float(row.get("decision_count"))
    total_fallback = as_float(row.get("fallback_count"))
    total_invalid = as_float(row.get("invalid_count"))
    total_retrieved = as_float(row.get("retrieved_count"))
    model_counts = parse_json_field(row.get("model_counts"))

    if isinstance(row.get("model_counts"), dict):
        model_counts = row["model_counts"]

    if model_counts:
        counted_decisions = sum(as_float(value) for value in model_counts.values()) or total_decisions or 1.0
        for raw_model, count_value in model_counts.items():
            decision_count = as_float(count_value)
            if decision_count <= 0:
                continue
            model = match_model_label(str(raw_model), known_labels)
            acc = model_accs[model]
            fraction = decision_count / counted_decisions
            acc.decision_count += decision_count
            acc.fallback_count += total_fallback * fraction
            acc.invalid_count += total_invalid * fraction
            acc.retrieved_count += total_retrieved * fraction
        return

    seats = [seat for seat in row.get("seat_assignments", []) if isinstance(seat, dict)]
    seat_counts = Counter(canonical_model(seat.get("model")) for seat in seats)
    counted_seats = sum(seat_counts.values()) or 1
    for model, seat_count in seat_counts.items():
        fraction = seat_count / counted_seats
        acc = model_accs[model]
        acc.decision_count += total_decisions * fraction
        acc.fallback_count += total_fallback * fraction
        acc.invalid_count += total_invalid * fraction
        acc.retrieved_count += total_retrieved * fraction


def attach_player_scores(
    row: dict[str, Any],
    model_accs: dict[str, ModelAccumulator],
    player_to_model: dict[str, str],
) -> None:
    score_lists: list[Any] = []
    for key in ("player_scores", "scores"):
        if isinstance(row.get(key), list):
            score_lists.append(row[key])
    metadata = row.get("metadata")
    if isinstance(metadata, dict) and isinstance(metadata.get("player_scores"), list):
        score_lists.append(metadata["player_scores"])

    for score_list in score_lists:
        for score in score_list:
            if not isinstance(score, dict):
                continue
            player_id = str(score.get("player_id") or "")
            model = player_to_model.get(player_id)
            if model:
                add_score_sample(model_accs[model], score)

    target = row.get("target")
    target_score = row.get("target_score")
    if isinstance(target, dict) and isinstance(target_score, dict):
        model = player_to_model.get(str(target.get("player_id") or ""))
        if model:
            add_score_sample(model_accs[model], target_score)


def aggregate_experiment_games(game_paths: list[Path]) -> dict[str, Any]:
    model_accs: defaultdict[str, ModelAccumulator] = defaultdict(lambda: ModelAccumulator(model="unknown"))
    role_accs: defaultdict[str, RoleAccumulator] = defaultdict(lambda: RoleAccumulator(role="unknown"))
    game_records: list[dict[str, Any]] = []
    player_samples: list[dict[str, Any]] = []
    camp_wins: Counter[str] = Counter()
    skipped_jsonl_rows = 0
    score_source_rows = 0

    for game_path in game_paths:
        experiment = game_path.parent.name
        rows, skipped = read_jsonl(game_path)
        skipped_jsonl_rows += skipped
        group_rows = read_csv_rows(game_path.parent / "group_results.csv")
        group_rows_available = bool(group_rows)

        for row in rows:
            game_id = str(row.get("game_id") or row.get("id") or "")
            winner = str(row.get("winner") or "unknown")
            camp_wins[winner or "unknown"] += 1
            seats = [seat for seat in row.get("seat_assignments", []) if isinstance(seat, dict)]
            known_labels = {canonical_model(seat.get("model")) for seat in seats}
            player_to_model: dict[str, str] = {}

            game_records.append(
                {
                    "experiment": experiment,
                    "source_file": rel(game_path),
                    "game_id": game_id,
                    "seed": row.get("seed"),
                    "framework": row.get("framework") or row.get("side") or "",
                    "winner": winner,
                    "days": row.get("days"),
                    "events": row.get("events"),
                    "player_count": row.get("player_count"),
                    "axis": row.get("axis"),
                    "decision_count": as_int(row.get("decision_count")),
                    "fallback_count": as_int(row.get("fallback_count")),
                    "invalid_count": as_int(row.get("invalid_count")),
                }
            )

            for seat in seats:
                model = canonical_model(seat.get("model"))
                role = str(seat.get("role") or "unknown")
                alignment = str(seat.get("alignment") or "unknown")
                player_id = str(seat.get("player_id") or "")
                won = winner_matches_alignment(winner, alignment)
                player_to_model[player_id] = model

                acc = model_accs[model]
                acc.model = model
                acc.seat_samples += 1
                acc.wins += int(won)
                if game_id:
                    acc.games.add(game_id)
                acc.experiments.add(experiment)
                acc.roles[role] += 1
                acc.role_wins[role] += int(won)
                acc.alignments[alignment] += 1

                role_acc = role_accs[role]
                role_acc.role = role
                role_acc.samples += 1
                role_acc.wins += int(won)
                role_acc.models[model] += 1
                role_acc.alignments[alignment] += 1

                player_samples.append(
                    {
                        "experiment": experiment,
                        "game_id": game_id,
                        "seed": row.get("seed"),
                        "player_id": player_id,
                        "seat": seat.get("seat"),
                        "name": seat.get("name"),
                        "role": role,
                        "alignment": alignment,
                        "model": model,
                        "winner": winner,
                        "won": won,
                    }
                )

            update_health_from_game(row, model_accs, known_labels)
            if not group_rows_available:
                attach_player_scores(row, model_accs, player_to_model)

        for group_row in group_rows:
            model = canonical_model(group_row.get("group_key"))
            if not model or model.startswith("framework:"):
                continue
            acc = model_accs[model]
            acc.model = model
            acc.experiments.add(experiment)
            add_group_score_sample(acc, group_row)
            score_source_rows += 1

    model_rows = [model_row(acc) for acc in model_accs.values() if acc.model != "unknown"]
    model_rows.sort(key=model_sort_key)
    for rank, row in enumerate(model_rows, start=1):
        row["rank"] = rank

    role_rows = [role_row(acc) for acc in role_accs.values() if acc.role != "unknown"]
    role_rows.sort(key=lambda row: role_sort_key(str(row["role"])))

    roles = sorted({row["role"] for row in role_rows}, key=role_sort_key)
    heatmap = build_role_heatmap(model_rows, roles)
    total_games = len(game_records)
    camp_win_rates = {
        camp: {
            "wins": count,
            "win_rate": round6(count / total_games) if total_games else 0.0,
        }
        for camp, count in sorted(camp_wins.items())
    }

    total_decisions = sum(row["decision_count"] for row in model_rows)
    total_fallback = sum(row["fallback_count"] for row in model_rows)
    total_invalid = sum(row["invalid_count"] for row in model_rows)

    return {
        "generated_at": utc_now(),
        "source": {
            "game_run_files": [rel(path) for path in game_paths],
            "game_run_file_count": len(game_paths),
            "game_count": total_games,
            "player_samples": len(player_samples),
            "score_source_rows": score_source_rows,
            "skipped_jsonl_rows": skipped_jsonl_rows,
        },
        "games": game_records,
        "player_samples": player_samples,
        "models": model_rows,
        "roles": role_rows,
        "role_heatmap": heatmap,
        "camp_win_rates": camp_win_rates,
        "decision_health_totals": {
            "decision_count": round6(total_decisions),
            "fallback_count": round6(total_fallback),
            "invalid_count": round6(total_invalid),
            "fallback_rate": round6(total_fallback / total_decisions) if total_decisions else 0.0,
            "invalid_rate": round6(total_invalid / total_decisions) if total_decisions else 0.0,
        },
    }


def model_row(acc: ModelAccumulator) -> dict[str, Any]:
    score_fields = score_averages(acc)
    per_role = {
        role: {
            "samples": int(samples),
            "wins": int(acc.role_wins.get(role, 0)),
            "win_rate": round6(acc.role_wins.get(role, 0) / samples) if samples else 0.0,
        }
        for role, samples in sorted(acc.roles.items(), key=lambda item: role_sort_key(item[0]))
    }
    fallback_rate = acc.fallback_count / acc.decision_count if acc.decision_count else 0.0
    invalid_rate = acc.invalid_count / acc.decision_count if acc.decision_count else 0.0
    return {
        "rank": 0,
        "model": acc.model,
        "games_played": len(acc.games),
        "seat_samples": acc.seat_samples,
        "wins": acc.wins,
        "win_rate": round6(acc.wins / acc.seat_samples) if acc.seat_samples else 0.0,
        "avg_score": score_fields["avg_score"],
        "avg_final_score": score_fields["avg_final_score"],
        "avg_vote_score": score_fields["avg_vote_score"],
        "avg_speech_score": score_fields["avg_speech_score"],
        "avg_skill_score": score_fields["avg_skill_score"],
        "decision_count": round6(acc.decision_count),
        "fallback_count": round6(acc.fallback_count),
        "invalid_count": round6(acc.invalid_count),
        "fallback_rate": round6(fallback_rate),
        "invalid_rate": round6(invalid_rate),
        "knowledge_hit_rate": round6(acc.retrieved_count / acc.decision_count) if acc.decision_count else 0.0,
        "roles": dict(sorted(acc.roles.items(), key=lambda item: role_sort_key(item[0]))),
        "alignments": dict(sorted(acc.alignments.items())),
        "per_role_win_rate": per_role,
        "experiments": sorted(acc.experiments),
    }


def role_row(acc: RoleAccumulator) -> dict[str, Any]:
    return {
        "role": acc.role,
        "samples": acc.samples,
        "wins": acc.wins,
        "win_rate": round6(acc.wins / acc.samples) if acc.samples else 0.0,
        "models": dict(sorted(acc.models.items())),
        "alignments": dict(sorted(acc.alignments.items())),
    }


def build_role_heatmap(model_rows: list[dict[str, Any]], roles: list[str]) -> dict[str, Any]:
    data: list[list[Any]] = []
    for y_index, model in enumerate(model_rows):
        role_rates = model.get("per_role_win_rate", {})
        for x_index, role in enumerate(roles):
            payload = role_rates.get(role, {})
            win_rate = payload.get("win_rate")
            samples = payload.get("samples", 0)
            data.append([x_index, y_index, round(float(win_rate) * 100, 2) if samples else None, samples])
    return {
        "roles": roles,
        "models": [row["model"] for row in model_rows],
        "data": data,
    }


def build_leaderboard_payload() -> dict[str, Any]:
    aggregate = aggregate_experiment_games(discover_game_run_paths())
    return {
        "generated_at": aggregate["generated_at"],
        "source": aggregate["source"],
        "model_rankings": aggregate["models"],
        "role_analysis": {
            "roles": aggregate["roles"],
            "per_role_win_rate": aggregate["role_heatmap"],
        },
        "decision_health": {
            "totals": aggregate["decision_health_totals"],
            "by_model": [
                {
                    "rank": row["rank"],
                    "model": row["model"],
                    "decision_count": row["decision_count"],
                    "fallback_count": row["fallback_count"],
                    "invalid_count": row["invalid_count"],
                    "fallback_rate": row["fallback_rate"],
                    "invalid_rate": row["invalid_rate"],
                    "knowledge_hit_rate": row["knowledge_hit_rate"],
                }
                for row in aggregate["models"]
            ],
        },
    }


def summarize_side(results: list[dict[str, Any]]) -> dict[str, Any]:
    if not results:
        return {
            "games": 0,
            "target_wins": 0,
            "target_win_rate": 0.0,
            "avg_score": None,
            "avg_vote_score": None,
            "avg_speech_score": None,
            "avg_skill_score": None,
            "knowledge_hit_rate": 0.0,
            "fallback_rate": 0.0,
            "invalid_rate": 0.0,
        }
    scores = [row.get("target_score", {}) for row in results if isinstance(row.get("target_score"), dict)]

    def avg_score_field(field_name: str) -> float | None:
        values = [as_float(score.get(field_name)) for score in scores if field_name in score]
        return round6(sum(values) / len(values)) if values else None

    decisions = sum(as_float(row.get("decision_summary", {}).get("decision_count")) for row in results)
    retrieved = sum(as_float(row.get("decision_summary", {}).get("retrieved_count")) for row in results)
    fallback = sum(as_float(row.get("decision_summary", {}).get("fallback_count")) for row in results)
    invalid = sum(as_float(row.get("decision_summary", {}).get("invalid_count")) for row in results)
    wins = sum(1 for row in results if bool(row.get("target_won")))
    return {
        "games": len(results),
        "target_wins": wins,
        "target_win_rate": round6(wins / len(results)),
        "avg_score": avg_score_field("adjusted_final_score") or avg_score_field("final_score"),
        "avg_vote_score": avg_score_field("vote_score"),
        "avg_speech_score": avg_score_field("speech_score"),
        "avg_skill_score": avg_score_field("skill_score"),
        "knowledge_hit_rate": round6(retrieved / decisions) if decisions else 0.0,
        "fallback_rate": round6(fallback / decisions) if decisions else 0.0,
        "invalid_rate": round6(invalid / decisions) if decisions else 0.0,
    }


def summarize_track_c(outputs_dir: Path = OUTPUTS_DIR) -> dict[str, Any]:
    summary_paths = sorted(
        path
        for path in outputs_dir.glob("exp_trackc*/*.json")
        if path.is_file() and not path.name.endswith(".lock") and ".partial" not in path.name
    )
    experiments: list[dict[str, Any]] = []
    score_deltas: list[float] = []
    win_deltas: list[float] = []
    knowledge_deltas: list[float] = []

    for path in summary_paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        baseline = [row for row in payload.get("baseline_results", []) if isinstance(row, dict)]
        candidate = [row for row in payload.get("candidate_results", []) if isinstance(row, dict)]
        if not baseline and not candidate:
            continue

        baseline_by_seed = {row.get("seed"): row for row in baseline}
        candidate_by_seed = {row.get("seed"): row for row in candidate}
        paired_seeds = sorted(set(baseline_by_seed) & set(candidate_by_seed))
        local_score_deltas: list[float] = []
        local_win_deltas: list[float] = []
        for seed in paired_seeds:
            b_score = baseline_by_seed[seed].get("target_score", {})
            c_score = candidate_by_seed[seed].get("target_score", {})
            if isinstance(b_score, dict) and isinstance(c_score, dict):
                local_score_deltas.append(
                    as_float(c_score.get("adjusted_final_score", c_score.get("final_score")))
                    - as_float(b_score.get("adjusted_final_score", b_score.get("final_score")))
                )
            local_win_deltas.append(
                float(bool(candidate_by_seed[seed].get("target_won")))
                - float(bool(baseline_by_seed[seed].get("target_won")))
            )

        baseline_summary = summarize_side(baseline)
        candidate_summary = summarize_side(candidate)
        local_knowledge_delta = as_float(candidate_summary["knowledge_hit_rate"]) - as_float(
            baseline_summary["knowledge_hit_rate"]
        )
        score_deltas.extend(local_score_deltas)
        win_deltas.extend(local_win_deltas)
        if paired_seeds:
            knowledge_deltas.append(local_knowledge_delta)

        experiments.append(
            {
                "source_file": rel(path),
                "target_role": payload.get("target_role"),
                "baseline_framework": payload.get("baseline_framework"),
                "candidate_framework": payload.get("candidate_framework"),
                "paired_seed_count": len(paired_seeds),
                "baseline": baseline_summary,
                "candidate": candidate_summary,
                "delta": {
                    "avg_score_delta": round6(sum(local_score_deltas) / len(local_score_deltas))
                    if local_score_deltas
                    else None,
                    "target_win_rate_delta": round6(sum(local_win_deltas) / len(local_win_deltas))
                    if local_win_deltas
                    else 0.0,
                    "knowledge_hit_rate_delta": round6(local_knowledge_delta),
                    "positive_score_delta_seeds": sum(1 for value in local_score_deltas if value > 0),
                },
            }
        )

    return {
        "source_files": [rel(path) for path in summary_paths],
        "experiment_count": len(experiments),
        "paired_seed_count": sum(exp["paired_seed_count"] for exp in experiments),
        "avg_score_delta": round6(sum(score_deltas) / len(score_deltas)) if score_deltas else None,
        "target_win_rate_delta": round6(sum(win_deltas) / len(win_deltas)) if win_deltas else 0.0,
        "knowledge_hit_rate_delta": round6(sum(knowledge_deltas) / len(knowledge_deltas)) if knowledge_deltas else 0.0,
        "experiments": experiments,
    }


def build_global_review_payload() -> dict[str, Any]:
    aggregate = aggregate_experiment_games(discover_game_run_paths())
    track_c = summarize_track_c()
    camp_rates = aggregate["camp_win_rates"]
    village_rate = as_float(camp_rates.get("village", {}).get("win_rate"))
    wolf_rate = as_float(camp_rates.get("wolf", {}).get("win_rate"))
    top_models = aggregate["models"][:3]
    top_roles = sorted(
        aggregate["roles"], key=lambda row: (-as_float(row.get("win_rate")), -as_int(row.get("samples")))
    )[:3]

    observations = [
        f"Across {aggregate['source']['game_count']} experiment games, wolf win rate is {wolf_rate:.1%} and village win rate is {village_rate:.1%}.",
        "Decision health is clean when fallback and invalid rates stay near zero.",
    ]
    if top_models:
        observations.append(
            f"Top model by ranking is {top_models[0]['model']} with win rate {as_float(top_models[0]['win_rate']):.1%}."
        )
    if top_roles:
        observations.append(
            "Best sampled roles: "
            + ", ".join(f"{row['role']} ({as_float(row['win_rate']):.1%}, n={row['samples']})" for row in top_roles)
            + "."
        )
    if track_c["experiment_count"]:
        observations.append(
            "Track C candidate vs baseline: "
            f"score delta {track_c['avg_score_delta']}, target win-rate delta {track_c['target_win_rate_delta']}, "
            f"knowledge-hit delta {track_c['knowledge_hit_rate_delta']}."
        )

    return {
        "generated_at": aggregate["generated_at"],
        "source": aggregate["source"],
        "camp_win_rates": camp_rates,
        "role_performance": aggregate["roles"],
        "track_c_evolution_effect": track_c,
        "observations": observations,
        "data_quality": {
            "score_source_rows": aggregate["source"]["score_source_rows"],
            "skipped_jsonl_rows": aggregate["source"]["skipped_jsonl_rows"],
            "decision_health_totals": aggregate["decision_health_totals"],
        },
    }
