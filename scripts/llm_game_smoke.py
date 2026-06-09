from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.agents.factory import create_agents
from backend.engine.game import WerewolfGame
from backend.engine.models import EventType
from backend.engine.rules import build_players


def _decision_is_fallback(record) -> bool:
    parsed = record.parsed_action or {}
    metadata = parsed.get("metadata") or {}
    return (
        bool(record.fallback_used)
        or bool(metadata.get("fallback"))
        or bool(metadata.get("fallback_used"))
        or str(metadata.get("source", "")).lower() == "fallback"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a strict LLM-only full-game smoke.")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--max-seed", type=int, default=12)
    parser.add_argument("--max-days", type=int, default=4)
    args = parser.parse_args()

    last_error: Exception | None = None
    for seed in range(args.seed, args.max_seed + 1):
        try:
            state = _run_one(seed, args.max_days)
            print("accepted_seed=", seed)
            return _assert_strict_full_game(state)
        except RuntimeError as exc:
            last_error = exc
            print(f"seed {seed} rejected: {exc}")
    raise RuntimeError(
        f"No strict full-game LLM smoke passed in seed range {args.seed}..{args.max_seed}"
    ) from last_error


def _run_one(seed: int, max_days: int):
    players = build_players(seed=seed)
    agents = create_agents(players, {"type": "llm", "seed": seed})
    game = WerewolfGame(players=players, agents=agents, seed=seed, max_days=max_days)
    return game.play()


def _assert_strict_full_game(state) -> int:

    talk_events = [event for event in state.events if event.type == EventType.CHAT_MESSAGE]
    vote_events = [event for event in state.events if event.type == EventType.VOTE_CAST]
    llm_talks = [event for event in talk_events if event.payload.get("agent_source") == "llm"]
    llm_votes = [event for event in vote_events if event.payload.get("agent_source") == "llm"]
    fallback_talks = [event for event in talk_events if event.payload.get("agent_fallback")]
    fallback_votes = [event for event in vote_events if event.payload.get("agent_fallback")]
    empty_talks = [event for event in talk_events if not str(event.payload.get("speech") or "").strip()]
    fallback_decisions = [record for record in state.decision_records if _decision_is_fallback(record)]
    llm_decisions = [
        record
        for record in state.decision_records
        if str(((record.parsed_action or {}).get("metadata") or {}).get("source", "")).lower() == "llm"
    ]
    invalid_decisions = [record for record in state.decision_records if not record.is_valid]
    empty_speech_decisions = [
        record
        for record in state.decision_records
        if (record.parsed_action or {}).get("action_type") == "talk"
        and not str((record.parsed_action or {}).get("speech") or "").strip()
    ]

    print("winner=", state.winner.value if state.winner else None)
    print("day=", state.day)
    print("talk_events=", len(talk_events))
    print("vote_events=", len(vote_events))
    print("llm_talk_events=", len(llm_talks))
    print("llm_vote_events=", len(llm_votes))
    print("llm_decisions=", len(llm_decisions))
    print("fallback_talk_events=", len(fallback_talks))
    print("fallback_vote_events=", len(fallback_votes))
    print("fallback_decisions=", len(fallback_decisions))
    print("invalid_decisions=", len(invalid_decisions))
    print("empty_talk_events=", len(empty_talks))
    print("empty_speech_decisions=", len(empty_speech_decisions))

    if not talk_events or not vote_events:
        raise RuntimeError("LLM game smoke did not reach both talk and vote phases")
    if not llm_talks:
        raise RuntimeError("No talk events came from llm source")
    if not llm_votes:
        raise RuntimeError("No vote events came from llm source")
    if not llm_decisions:
        raise RuntimeError("No decision audit records came from llm source")
    if fallback_talks or fallback_votes or fallback_decisions:
        raise RuntimeError("LLM game smoke observed fallback decisions")
    if invalid_decisions:
        raise RuntimeError("LLM game smoke observed invalid decision records")
    if empty_talks or empty_speech_decisions:
        raise RuntimeError("LLM game smoke observed empty speech")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
