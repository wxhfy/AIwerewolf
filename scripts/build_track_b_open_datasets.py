#!/usr/bin/env python3
"""Unified Track B open dataset builder.

Runs all available adapters and merges outputs into combined dataset files
under data/open/combined/.

Usage:
  python scripts/build_track_b_open_datasets.py --all
  python scripts/build_track_b_open_datasets.py --source werewolf_among_us
  python scripts/build_track_b_open_datasets.py --list
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OPEN_DATA_DIR = ROOT / "data" / "open"
COMBINED_DIR = OPEN_DATA_DIR / "combined"
SPLITS_DIR = ROOT / "data" / "splits" / "open_data"


def _ensure_dirs():
    COMBINED_DIR.mkdir(parents=True, exist_ok=True)
    SPLITS_DIR.mkdir(parents=True, exist_ok=True)


def _save_jsonl(items: list[dict], path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    items = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    items.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return items


def _enrich_sample(sample: dict, source_name: str, rule_variant: str, license_val: str) -> dict:
    """Ensure every sample has canonical metadata fields."""
    if "source" not in sample:
        sample["source"] = source_name
    if "license" not in sample:
        sample["license"] = license_val
    if "rule_variant" not in sample:
        sample["rule_variant"] = rule_variant
    if "do_not_train_final_q_directly" not in sample:
        sample["do_not_train_final_q_directly"] = True
    if "weak_label_source" not in sample:
        sample["weak_label_source"] = "unknown"
    # Ensure no final_q leaks
    sample.pop("final_q", None)
    sample.pop("calibrated_q", None)
    sample.pop("raw_model_q", None)
    return sample


# ===========================================================================
# Source: Werewolf Among Us
# ===========================================================================


def build_werewolf_among_us() -> dict[str, Any]:
    """Rebuild Werewolf Among Us speech samples."""
    from backend.eval.open_data.adapters import WerewolfAmongUsAdapter

    adapter = WerewolfAmongUsAdapter()
    logs, samples = adapter.run(split="all")

    source_dir = OPEN_DATA_DIR / "werewolf_among_us"
    source_dir.mkdir(parents=True, exist_ok=True)

    # Save per-source outputs
    speech_path = source_dir / "track_b_open_speech_samples.jsonl"
    speech_dicts = []
    for s in samples:
        d = s.to_dict()
        d = _enrich_sample(d, "werewolf_among_us", adapter.rule_variant, adapter.license.value)
        speech_dicts.append(d)
    _save_jsonl(speech_dicts, speech_path)

    # Save speech act labels (annotation counts per utterance)
    labels_path = source_dir / "track_b_open_speech_act_labels.jsonl"
    label_dicts = []
    for s in samples:
        label_dicts.append(
            {
                "sample_id": s.sample_id,
                "game_id": s.game_id,
                "player_id": s.player_id,
                "role": s.role,
                "utterance": s.utterance[:200],
                "annotations": {
                    k: v.label_value for k, v in s.weak_labels.items() if v.source.value == "open_dataset_annotation"
                },
                "annotation_count": sum(
                    1 for v in s.weak_labels.values() if v.source.value == "open_dataset_annotation"
                ),
            }
        )
    _save_jsonl(label_dicts, labels_path)

    # Save logs
    log_path = source_dir / "track_b_open_game_logs.jsonl"
    log_dicts = []
    for log in logs:
        log_dicts.append(
            {
                "source": log.source,
                "license": log.license.value,
                "rule_variant": log.rule_variant,
                "game_id": log.game_id,
                "n_events": len(log.events),
                "n_players": len(log.players),
                "winner": log.winner,
                "metadata": log.metadata,
            }
        )
    _save_jsonl(log_dicts, log_path)

    return {
        "source": "werewolf_among_us",
        "status": "OK",
        "total_games": len(logs),
        "total_speech_samples": len(speech_dicts),
        "outputs": {
            "speech_samples": str(speech_path),
            "speech_act_labels": str(labels_path),
            "game_logs": str(log_path),
        },
    }


# ===========================================================================
# Source: Track B Native
# ===========================================================================


def build_track_b_native() -> dict[str, Any]:
    """Extract speech and vote samples from Track B native real LLM games."""
    source_dir = OPEN_DATA_DIR / "track_b_native"
    source_dir.mkdir(parents=True, exist_ok=True)

    # Load existing games from leaderboard
    leaderboard_path = ROOT / "data" / "health" / "track_b_minimal_leaderboard_games.jsonl"
    games = _load_jsonl(leaderboard_path)

    speech_samples: list[dict] = []
    vote_samples: list[dict] = []
    critical_samples: list[dict] = []
    speech_idx = 0
    vote_idx = 0
    cd_idx = 0

    for g in games:
        game_id = g["game_id"]
        agent_version = g.get("agent_version", "unknown")
        g.get("role_setup", {})
        player_scores = g.get("player_scores", [])

        # Build opportunities from each game's player scores as structured samples
        for ps in player_scores:
            player_id = ps.get("player_id", "")
            role = ps.get("role", "")

            # Speech sample
            speech_idx += 1
            speech_samples.append(
                {
                    "sample_id": f"native_speech_{speech_idx:06d}",
                    "source": "track_b_native",
                    "license": "internal",
                    "rule_variant": "wolfcha_default_7_player",
                    "game_id": game_id,
                    "turn_id": "0",
                    "phase": "DAY_DISCUSSION",
                    "player_id": player_id,
                    "role": role,
                    "utterance": "",
                    "visible_public_context": {"game_id": game_id, "agent_version": agent_version},
                    "visible_private_context": {"own_role": role},
                    "weak_labels": {
                        "speech_score_heuristic": {
                            "label_name": "speech_score",
                            "label_value": ps.get("speech_score", 0),
                            "source": "heuristic",
                            "confidence": 0.5,
                        },
                    },
                    "weak_label_source": "heuristic",
                    "do_not_train_final_q_directly": True,
                }
            )

            # Vote sample
            vote_idx += 1
            vote_samples.append(
                {
                    "sample_id": f"native_vote_{vote_idx:06d}",
                    "source": "track_b_native",
                    "license": "internal",
                    "rule_variant": "wolfcha_default_7_player",
                    "game_id": game_id,
                    "phase": "DAY_VOTE",
                    "player_id": player_id,
                    "role": role,
                    "visible_public_context": {"game_id": game_id},
                    "visible_private_context": {"own_role": role},
                    "vote_target": "",
                    "candidate_targets": [],
                    "weak_labels": {
                        "vote_score_heuristic": {
                            "label_name": "vote_score",
                            "label_value": ps.get("vote_score", 0),
                            "source": "heuristic",
                            "confidence": 0.5,
                        },
                        "skill_score_heuristic": {
                            "label_name": "skill_score",
                            "label_value": ps.get("skill_score", 0),
                            "source": "heuristic",
                            "confidence": 0.5,
                        },
                    },
                    "weak_label_source": "heuristic",
                    "do_not_train_final_q_directly": True,
                }
            )

        # Record process scores as critical decision samples
        for ps in player_scores:
            cd_idx += 1
            critical_samples.append(
                {
                    "sample_id": f"native_cd_{cd_idx:06d}",
                    "source": "track_b_native",
                    "game_id": game_id,
                    "player_id": ps.get("player_id", ""),
                    "role": ps.get("role", ""),
                    "process_score": ps.get("process_score", 0),
                    "final_score": ps.get("final_score", 0),
                    "speech_score": ps.get("speech_score", 0),
                    "vote_score": ps.get("vote_score", 0),
                    "skill_score": ps.get("skill_score", 0),
                    "survival_score": ps.get("survival_score", 0),
                    "mistake_penalty": ps.get("mistake_penalty", 0),
                    "agent_version": agent_version,
                }
            )

    # Save
    _save_jsonl(speech_samples, source_dir / "track_b_real_speech_samples.jsonl")
    _save_jsonl(vote_samples, source_dir / "track_b_real_vote_samples.jsonl")
    _save_jsonl(critical_samples, source_dir / "track_b_real_critical_decisions.jsonl")

    # Also save the raw opportunities if available
    opp_path = ROOT / "data" / "health" / "track_b_minimal_leaderboard_games.jsonl"
    if opp_path.exists():
        import shutil

        dest = source_dir / "track_b_real_opportunities.jsonl"
        shutil.copy(opp_path, dest)

    return {
        "source": "track_b_native",
        "status": "OK",
        "total_games": len(games),
        "total_speech_samples": len(speech_samples),
        "total_vote_samples": len(vote_samples),
        "total_critical_samples": len(critical_samples),
    }


# ===========================================================================
# Merge into combined
# ===========================================================================

BUILDERS = {
    "werewolf_among_us": build_werewolf_among_us,
    "track_b_native": build_track_b_native,
}


def merge_combined(results: dict[str, Any]):
    """Merge all per-source outputs into combined dataset files."""
    combined_speech = []
    combined_vote = []
    combined_pairwise = []
    combined_value = []
    combined_role_action = []
    combined_opportunities = []

    # Collect from werewolf_among_us
    wau_dir = OPEN_DATA_DIR / "werewolf_among_us"
    wau_speech = _load_jsonl(wau_dir / "track_b_open_speech_samples.jsonl")
    for s in wau_speech:
        s = _enrich_sample(s, "werewolf_among_us", "one_night_ultimate_werewolf", "verify_before_use")
        combined_speech.append(s)

    # Collect from track_b_native
    native_dir = OPEN_DATA_DIR / "track_b_native"
    native_speech = _load_jsonl(native_dir / "track_b_real_speech_samples.jsonl")
    native_vote = _load_jsonl(native_dir / "track_b_real_vote_samples.jsonl")
    native_cd = _load_jsonl(native_dir / "track_b_real_critical_decisions.jsonl")
    for s in native_speech:
        combined_speech.append(s)
    for s in native_vote:
        combined_vote.append(s)
    for s in native_cd:
        combined_role_action.append(s)

    # Also include leaderboard games as opportunities
    lb_path = ROOT / "data" / "health" / "track_b_minimal_leaderboard_games.jsonl"
    lb_games = _load_jsonl(lb_path)
    for g in lb_games:
        combined_opportunities.append(
            {
                "game_id": g.get("game_id", ""),
                "agent_version": g.get("agent_version", ""),
                "source": "track_b_native",
                "license": "internal",
                "rule_variant": "wolfcha_default_7_player",
                "winner": g.get("winner", ""),
                "player_scores": g.get("player_scores", []),
            }
        )

    # Save combined files
    _save_jsonl(combined_speech, COMBINED_DIR / "track_b_open_speech_samples.jsonl")
    _save_jsonl(combined_vote, COMBINED_DIR / "track_b_open_vote_samples.jsonl")
    _save_jsonl(combined_pairwise, COMBINED_DIR / "track_b_open_pairwise_samples.jsonl")
    _save_jsonl(combined_value, COMBINED_DIR / "track_b_open_value_samples.jsonl")
    _save_jsonl(combined_role_action, COMBINED_DIR / "track_b_open_role_action_samples.jsonl")
    _save_jsonl(combined_opportunities, COMBINED_DIR / "track_b_open_opportunities.jsonl")

    # Generate game-id splits for speech
    speech_games = sorted({s.get("game_id", "") for s in combined_speech if s.get("game_id")})
    if len(speech_games) >= 4:
        n_train = int(len(speech_games) * 0.7)
        n_val = int(len(speech_games) * 0.15)
        train_games = speech_games[:n_train]
        val_games = speech_games[n_train : n_train + n_val]
        test_games = speech_games[n_train + n_val :]

        SPLITS_DIR.mkdir(parents=True, exist_ok=True)
        (SPLITS_DIR / "speech_train_games.txt").write_text("\n".join(train_games), encoding="utf-8")
        (SPLITS_DIR / "speech_val_games.txt").write_text("\n".join(val_games), encoding="utf-8")
        (SPLITS_DIR / "speech_test_games.txt").write_text("\n".join(test_games), encoding="utf-8")

    results["combined"] = {
        "speech_samples": len(combined_speech),
        "vote_samples": len(combined_vote),
        "pairwise_samples": len(combined_pairwise),
        "value_samples": len(combined_value),
        "role_action_samples": len(combined_role_action),
        "opportunities": len(combined_opportunities),
        "speech_games": len(speech_games),
        "splits": str(SPLITS_DIR),
    }


# ===========================================================================
# Main
# ===========================================================================


def main():
    parser = argparse.ArgumentParser(description="Build Track B open datasets")
    parser.add_argument("--all", action="store_true", help="Build all sources")
    parser.add_argument("--source", choices=list(BUILDERS.keys()), help="Build specific source")
    parser.add_argument("--list", action="store_true", help="List available sources")
    args = parser.parse_args()

    if args.list:
        print("Available sources:")
        for name in BUILDERS:
            print(f"  - {name}")
        return 0

    _ensure_dirs()
    results: dict[str, Any] = {}

    targets = list(BUILDERS.keys()) if args.all else ([args.source] if args.source else [])
    if not targets:
        print("Use --all or --source <name>")
        return 1

    for name in targets:
        print(f"\n[{name}]")
        try:
            fn = BUILDERS[name]
            results[name] = fn()
            print(f"  Status: {results[name].get('status', 'ERROR')}")
        except Exception as e:
            print(f"  FAILED: {e}")
            import traceback

            traceback.print_exc()
            results[name] = {"source": name, "status": "ERROR", "error": str(e)}

    # Merge
    print("\n[Merging into combined datasets...]")
    merge_combined(results)

    # Summary
    print("\n" + "=" * 60)
    print("Build Complete")
    print("=" * 60)
    for name, r in results.items():
        print(f"  {name}: {r.get('status', '?')}")
    if "combined" in results:
        c = results["combined"]
        print("\n  Combined dataset:")
        print(f"    Speech:     {c['speech_samples']}")
        print(f"    Vote:       {c['vote_samples']}")
        print(f"    Pairwise:   {c['pairwise_samples']}")
        print(f"    Value:      {c['value_samples']}")
        print(f"    RoleAction: {c['role_action_samples']}")
        print(f"    Splits:     {c['splits']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
