"""Collect calibration anchors from open-source werewolf datasets.

Datasets:
  - Werewolf-bench (Foaster.ai): 4 complete LLM games with reasoning traces
  - LLMafia (HuggingFace): 33 games, 3,593 messages, human + LLM play
  - Werewolf Among Us (ACL 2023): 199 dialogs, 26,647 utterance annotations

Usage:
  python scripts/collect_calibration_anchors.py --source werewolf_bench --output data/anchors/
  python scripts/collect_calibration_anchors.py --source all --validate

Output:
  data/anchors/{dimension}_anchors.json  — calibration anchor files
  data/anchors/calibration_summary.json  — per-dimension counts
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any
from typing import Dict
from typing import List
from typing import Optional


@dataclass
class CalibrationAnchor:
    """A single calibration anchor point."""

    source: str  # dataset name
    game_id: str
    player_id: str
    role: str  # Seer / Werewolf / Witch / ...
    speech_text: str
    # Annotation dimensions
    persuasion_score: Optional[float] = None  # From Werewolf Among Us
    deception_label: Optional[str] = None  # WOLF 5-class
    reasoning_quality: Optional[float] = None  # AIWolfDial
    naturalness_score: Optional[float] = None  # AIWolfDial (A)
    consistency_score: Optional[float] = None  # AIWolfDial (C)
    # Metadata
    evidence_event_ids: List[str] = field(default_factory=list)
    human_label: Optional[Dict[str, float]] = None


def parse_werewolf_bench(path: str) -> List[CalibrationAnchor]:
    """Parse Foaster.ai werewolf-bench transcripts.

    Format: Plain text with speaker labels and [REASONING] blocks.
    """
    anchors = []
    text = Path(path).read_text()
    # Parse game transcripts
    games = text.split("Game ")
    for game_block in games[1:]:  # Skip preamble
        game_id = game_block[:20].strip()
        # Extract speeches and reasoning
        speeches = re.findall(r"(\w+)\s*:\s*(.+?)(?=\n\w+\s*:|\n\[|\Z)", game_block, re.DOTALL)
        reasonings = re.findall(r"\[REASONING\]\s*(.+?)(?=\n\n|\Z)", game_block, re.DOTALL)
        for i, (speaker, speech) in enumerate(speeches):
            anchor = CalibrationAnchor(
                source="werewolf_bench",
                game_id=game_id,
                player_id=speaker.strip(),
                role=_infer_role(speech + (reasonings[i] if i < len(reasonings) else "")),
                speech_text=speech.strip()[:500],
            )
            anchors.append(anchor)
    return anchors


def parse_llmafia(path: str) -> List[CalibrationAnchor]:
    """Parse LLMafia dataset (HuggingFace format).

    Format: JSON files with chat logs, voting records, role assignments.
    """
    import json as json_mod

    anchors = []
    data_dir = Path(path)
    for game_file in data_dir.glob("*.json"):
        game = json_mod.loads(game_file.read_text())
        game_id = game_file.stem
        roles = game.get("roles", {})
        for msg in game.get("messages", []):
            speaker = msg.get("speaker", "")
            role = roles.get(speaker, "unknown")
            anchor = CalibrationAnchor(
                source="llmafia",
                game_id=game_id,
                player_id=speaker,
                role=role,
                speech_text=msg.get("text", "")[:500],
                # LLMafia has voting records → derive vote accuracy
            )
            anchors.append(anchor)
    return anchors


def parse_werewolf_among_us(path: str) -> List[CalibrationAnchor]:
    """Parse Werewolf Among Us (ACL 2023) — utterance-level annotations.

    6 persuasion strategies annotated per utterance:
    Identity Declaration, Accusation, Interrogation, Call for Action, Defense, Evidence
    """
    import json as json_mod

    anchors = []
    data_dir = Path(path)
    for game_file in data_dir.glob("*.json"):
        game = json_mod.loads(game_file.read_text())
        game_id = game_file.stem
        for utt in game.get("utterances", []):
            strategies = utt.get("persuasion_strategies", {})
            # Convert strategy annotations to scores
            has_evidence = strategies.get("Evidence", 0) > 0
            is_accusation = strategies.get("Accusation", 0) > 0
            persuasion = has_evidence * 0.5 + is_accusation * 0.3 + 0.2
            anchor = CalibrationAnchor(
                source="werewolf_among_us",
                game_id=game_id,
                player_id=utt.get("speaker_id", ""),
                role=utt.get("role", "unknown"),
                speech_text=utt.get("text", "")[:500],
                persuasion_score=round(persuasion, 3),
                human_label={"persuasive": round(persuasion, 3)},
            )
            anchors.append(anchor)
    return anchors


def _infer_role(text: str) -> str:
    """Heuristic role inference from text."""
    text_lower = text.lower()
    if any(kw in text_lower for kw in ["seer", "预言家", "check result", "查验"]):
        return "Seer"
    if any(kw in text_lower for kw in ["werewolf", "wolf team", "狼队友", "狼人"]):
        return "Werewolf"
    if any(kw in text_lower for kw in ["witch", "poison", "save", "解药", "毒药", "女巫"]):
        return "Witch"
    if any(kw in text_lower for kw in ["hunter", "shoot", "猎人", "开枪"]):
        return "Hunter"
    if any(kw in text_lower for kw in ["guard", "protect", "守卫", "守护"]):
        return "Guard"
    return "Villager"


def summarize_anchors(anchors: List[CalibrationAnchor]) -> Dict[str, Any]:
    """Generate per-dimension calibration summary."""
    from collections import Counter

    by_role = Counter(a.role for a in anchors)
    by_source = Counter(a.source for a in anchors)
    has_persuasion = sum(1 for a in anchors if a.persuasion_score is not None)
    has_human_label = sum(1 for a in anchors if a.human_label)
    return {
        "total_anchors": len(anchors),
        "by_role": dict(by_role),
        "by_source": dict(by_source),
        "with_persuasion_score": has_persuasion,
        "with_human_label": has_human_label,
        "ready_dimensions": {
            "persuasive": has_persuasion,
            "persona_consistency": 0,  # Needs manual labeling
            "strategy_impact": 0,  # Needs manual labeling
        },
        "min_anchors_required": 50,
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Collect calibration anchors from open datasets")
    parser.add_argument("--source", default="all", choices=["werewolf_bench", "llmafia", "werewolf_among_us", "all"])
    parser.add_argument("--data-dir", default="data/raw_datasets/")
    parser.add_argument("--output", default="data/anchors/")
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()

    all_anchors: List[CalibrationAnchor] = []

    # Collect from each source
    sources = {
        "werewolf_bench": (parse_werewolf_bench, "werewolf_bench/"),
        "llmafia": (parse_llmafia, "llmafia/"),
        "werewolf_among_us": (parse_werewolf_among_us, "werewolf_among_us/"),
    }
    for name, (parser_fn, subdir) in sources.items():
        if args.source in (name, "all"):
            path = Path(args.data_dir) / subdir
            if path.exists():
                try:
                    parsed = parser_fn(str(path))
                    all_anchors.extend(parsed)
                    print(f"  {name}: {len(parsed)} anchors")
                except Exception as e:
                    print(f"  {name}: ERROR — {e}")
            else:
                print(f"  {name}: SKIP — {path} not found (download dataset first)")

    # Save
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = summarize_anchors(all_anchors)
    with open(out_dir / "calibration_summary.json", "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    with open(out_dir / "all_anchors.json", "w") as f:
        json.dump(
            [
                {
                    "source": a.source,
                    "game_id": a.game_id,
                    "player_id": a.player_id,
                    "role": a.role,
                    "speech": a.speech_text[:200],
                    "persuasion": a.persuasion_score,
                    "human_label": a.human_label,
                }
                for a in all_anchors
            ],
            f,
            indent=2,
            ensure_ascii=False,
        )

    print(f"\nTotal: {summary['total_anchors']} anchors collected")
    print(f"Ready for calibration: {summary['ready_dimensions']}")
    if args.validate:
        ready_count = sum(1 for v in summary["ready_dimensions"].values() if v >= 50)
        print(f"Dimensions with ≥50 anchors: {ready_count}/{len(summary['ready_dimensions'])}")


if __name__ == "__main__":
    main()
