"""Werewolf Among Us dataset adapter.

Converts the Werewolf Among Us dataset (bolinlai/Werewolf-Among-Us on HuggingFace)
into Track B SpeechQualitySamples.

Dataset format (per game):
  {
    "EG_ID": "...",
    "Game_ID": "...",
    "Dialogue": [
      {
        "Rec_Id": 1,
        "speaker": "Alice",
        "timestamp": "02:46",
        "utterance": "What?",
        "annotation": ["Interrogation", "Defense"]
      },
      ...
    ],
    "playerNames": ["Alice", "Bob", ...],
    "startRoles": ["Werewolf", "Seer", ...],
    "endRoles": ["Werewolf", "Seer", ...],
    "votingOutcome": ["alive", "dead", ...]
  }

Annotation labels (persuasion strategies):
  Identity Declaration, Accusation, Interrogation,
  Call for Action, Defense, Evidence

Track B mapping:
  utterance -> speech DecisionOpportunity
  annotation -> persuasion strategy weak labels
  speaker -> player
  startRoles[i] -> role

IMPORTANT:
  - Never generates final_q.
  - Persuasion strategy != decision quality.
  - Role assignment uses startRoles (PreAction).
  - All labels tagged WeakLabelSource.OPEN_DATASET_ANNOTATION.
"""

from __future__ import annotations

import json
from pathlib import Path

from backend.eval.open_data.schema import CanonicalGameEvent
from backend.eval.open_data.schema import OpenDataLicense
from backend.eval.open_data.schema import OpenGameLog
from backend.eval.open_data.schema import SpeechQualitySample
from backend.eval.open_data.schema import WeakLabel
from backend.eval.open_data.schema import WeakLabelSource

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATASET_SOURCE = "werewolf_among_us"
DATASET_LICENSE = OpenDataLicense.VERIFY_BEFORE_USE
DATASET_RULE_VARIANT = "one_night_werewolf"  # One Night Ultimate Werewolf variant

# Mapping from persuasion strategy to speech weak labels
PERSUASION_TO_WEAK_LABEL: dict[str, str] = {
    "Identity Declaration": "identity_declaration",
    "Accusation": "accusation",
    "Interrogation": "interrogation",
    "Call for Action": "call_for_action",
    "Defense": "defense",
    "Evidence": "evidence_use",
}

# Mapping from ONUW roles to Track B roles (best-effort)
ONUW_ROLE_MAP: dict[str, str] = {
    "Werewolf": "Werewolf",
    "Seer": "Seer",
    "Robber": "Villager",
    "Troublemaker": "Villager",
    "Minion": "Werewolf",
    "Villager": "Villager",
    "Mason": "Villager",
    "Insomniac": "Villager",
    "Hunter": "Hunter",
    "Tanner": "Villager",
    "Drunk": "Villager",
    "Doppelganger": "Villager",
}


def _normalize_role(onuw_role: str) -> str:
    return ONUW_ROLE_MAP.get(onuw_role, "Unknown")


def _parse_timestamp(ts: str) -> int:
    """Convert 'MM:SS' to seconds."""
    try:
        parts = ts.split(":")
        return int(parts[0]) * 60 + int(parts[1])
    except (ValueError, IndexError):
        return 0


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class WerewolfAmongUsAdapter:
    """Adapter for the Werewolf Among Us dataset."""

    def __init__(self, data_dir: str | Path | None = None):
        self.data_dir = Path(data_dir) if data_dir else self._default_data_dir()
        self.source = DATASET_SOURCE
        self.license = DATASET_LICENSE
        self.rule_variant = DATASET_RULE_VARIANT

    @staticmethod
    def _default_data_dir() -> Path:
        """Locate the cached HuggingFace dataset directory."""
        hf_cache = Path.home() / ".cache" / "huggingface" / "hub"
        pattern = "datasets--bolinlai--Werewolf-Among-Us"
        if hf_cache.exists():
            for child in hf_cache.iterdir():
                if pattern in child.name:
                    snapshots = child / "snapshots"
                    if snapshots.exists():
                        dirs = list(snapshots.iterdir())
                        if dirs:
                            return dirs[0]
        return Path("")

    def load_raw_games(self, split: str = "all") -> list[dict]:
        """Load all raw game dicts from the cached JSON files."""
        games: list[dict] = []
        if not self.data_dir.exists():
            return games

        for subset in ["Ego4D", "Youtube"]:
            subset_dir = self.data_dir / subset / "split"
            if not subset_dir.exists():
                continue

            if split == "all":
                json_files = list(subset_dir.glob("*.json"))
            else:
                json_files = [subset_dir / f"{split}.json"]

            for jf in json_files:
                if not jf.exists():
                    continue
                try:
                    with open(jf, encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, list):
                        games.extend(data)
                except (json.JSONDecodeError, OSError):
                    continue

        return games

    def build_open_game_logs(self, split: str = "all") -> list[OpenGameLog]:
        """Convert raw games into canonical OpenGameLogs."""
        raw_games = self.load_raw_games(split)
        logs: list[OpenGameLog] = []

        for raw in raw_games:
            game_id = raw.get("Game_ID", "unknown")
            players = raw.get("playerNames", [])
            start_roles = raw.get("startRoles", [])
            dialogues = raw.get("Dialogue", [])
            voting_outcome = raw.get("votingOutcome", [])

            # Build role map: player_name -> role
            role_map: dict[str, str] = {}
            for i, name in enumerate(players):
                if i < len(start_roles):
                    role_map[name] = _normalize_role(start_roles[i])
                else:
                    role_map[name] = "Unknown"

            # Build canonical events from dialogue
            events: list[CanonicalGameEvent] = []
            for d in dialogues:
                if not isinstance(d, dict):
                    continue
                speaker = d.get("speaker", "")
                utterance = d.get("utterance", "")
                annotations = d.get("annotation", [])
                rec_id = d.get("Rec_Id", 0)
                timestamp = d.get("timestamp", "00:00")

                event = CanonicalGameEvent(
                    event_id=f"{game_id}_rec{rec_id}",
                    source=self.source,
                    game_id=game_id,
                    timestamp_or_turn=_parse_timestamp(timestamp),
                    phase="DAY_DISCUSSION",
                    actor=speaker,
                    role_if_visible=role_map.get(speaker, "Unknown"),
                    event_type="speech",
                    payload={
                        "utterance": utterance,
                        "annotations": annotations if isinstance(annotations, list) else [],
                        "rec_id": rec_id,
                        "timestamp": timestamp,
                    },
                    visibility={"public": True, "private_to": []},
                )
                events.append(event)

            # Determine winner if possible
            winner = "unknown"
            alive_count = sum(1 for v in voting_outcome if str(v).lower() not in ("dead", "killed", "eliminated"))
            if alive_count > 0:
                # Check if werewolf survived
                for i, name in enumerate(players):
                    if i < len(voting_outcome) and i < len(start_roles):
                        if start_roles[i] == "Werewolf" and str(voting_outcome[i]).lower() not in (
                            "dead",
                            "killed",
                            "eliminated",
                        ):
                            winner = "wolf"
                            break
                if winner == "unknown":
                    winner = "village"

            log = OpenGameLog(
                source=self.source,
                license=self.license,
                rule_variant=self.rule_variant,
                game_id=game_id,
                events=events,
                players=[{"name": name, "role": role_map.get(name, "Unknown")} for name in players],
                roles=role_map,
                winner=winner,
                metadata={
                    "start_roles": start_roles,
                    "end_roles": raw.get("endRoles", []),
                    "voting_outcome": voting_outcome,
                    "subset": raw.get("EG_ID", "unknown"),
                },
            )
            logs.append(log)

        return logs

    def extract_speech_samples(self, logs: list[OpenGameLog]) -> list[SpeechQualitySample]:
        """Extract SpeechQualitySamples from OpenGameLogs."""
        samples: list[SpeechQualitySample] = []
        idx = 0

        for log in logs:
            # Build visible context: all prior events in this game
            prior_utterances: list[dict] = []

            for event in log.events:
                speaker = event.actor
                role = event.role_if_visible
                utterance = event.payload.get("utterance", "")
                annotations = event.payload.get("annotations", [])

                # Build weak labels from annotations
                weak_labels: dict[str, WeakLabel] = {}
                for ann in annotations:
                    if ann in PERSUASION_TO_WEAK_LABEL:
                        label_name = PERSUASION_TO_WEAK_LABEL[ann]
                        weak_labels[label_name] = WeakLabel(
                            label_name=label_name,
                            label_value=1.0,
                            source=WeakLabelSource.OPEN_DATASET_ANNOTATION,
                            confidence=0.7,
                            reason=f"annotated as {ann}",
                            used_future_info=False,
                        )

                # Also add a communication_quality proxy from annotation count
                n_annotations = len(annotations)
                if n_annotations > 0:
                    weak_labels["communication_richness"] = WeakLabel(
                        label_name="communication_richness",
                        label_value=min(1.0, n_annotations * 0.25),
                        source=WeakLabelSource.HEURISTIC,
                        confidence=0.5,
                        reason=f"proxy: {n_annotations} persuasion strategy annotations",
                        used_future_info=False,
                    )

                idx += 1
                sample = SpeechQualitySample(
                    sample_id=f"speech_{idx:06d}",
                    source=self.source,
                    license=self.license,
                    rule_variant=self.rule_variant,
                    game_id=log.game_id,
                    turn_id=str(event.timestamp_or_turn),
                    phase="DAY_DISCUSSION",
                    player_id=speaker,
                    role=role,
                    utterance=utterance,
                    visible_public_context={
                        "prior_utterances": list(prior_utterances),
                        "game_id": log.game_id,
                        "players": log.players,
                    },
                    visible_private_context={
                        "own_role": role,
                    },
                    weak_labels=weak_labels,
                    weak_label_source="open_dataset_annotation",
                    do_not_train_final_q_directly=True,
                )
                samples.append(sample)

                # Add current utterance to prior context for next events
                prior_utterances.append(
                    {
                        "speaker": speaker,
                        "role_visible": role,
                        "utterance": utterance[:200],
                    }
                )

        return samples

    def run(self, split: str = "all") -> tuple[list[OpenGameLog], list[SpeechQualitySample]]:
        """Full adapter pipeline: raw → logs → samples."""
        logs = self.build_open_game_logs(split)
        samples = self.extract_speech_samples(logs)
        return logs, samples
