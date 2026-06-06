"""Persist game state to database during gameplay."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import datetime
from datetime import timezone
from typing import Any

from sqlalchemy import func as sa_func

from backend.db.database import SessionLocal
from backend.db.database import init_db
from backend.db.models import AgentDecision
from backend.db.models import AgentVersion
from backend.db.models import Evaluation
from backend.db.models import EvolutionRound
from backend.db.models import EvolutionTournament
from backend.db.models import Game
from backend.db.models import GameEvent
from backend.db.models import GameSnapshot
from backend.db.models import KnowledgeUsageFeedback
from backend.db.models import LeaderboardEntry
from backend.db.models import Player
from backend.db.models import PublishedReview
from backend.db.models import ReviewReport
from backend.db.models import RoleStrategyCard
from backend.db.models import StrategyKnowledgeDoc
from backend.db.models import StrategyPatch
from backend.db.models import Vote
from backend.engine.models import GameState
from backend.eval.evolution import DreamJob
from backend.eval.evolution import KnowledgeDocValidator
from backend.eval.evolution import StrategyKnowledgeDoc as StrategyKnowledgeDocData
from backend.eval.evolution import StrategyKnowledgeStore
from backend.eval.evolution import StrategyPatch as StrategyPatchData
from backend.eval.evolution import StrategyRetrievalQuery
from backend.eval.evolution import build_acceptance_step_metric
from backend.eval.evolution import build_bc_acceptance_audit
from backend.eval.review import LeaderboardAggregator
from backend.eval.track_b import generate_published_review_document
from backend.eval.track_b import reconstruct_review_report

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clean(value: Any) -> Any:
    """Strip illegal control chars from strings recursively so JSON stays valid."""
    if isinstance(value, str):
        return _CONTROL_RE.sub(" ", value)
    if isinstance(value, dict):
        return {key: _clean(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_clean(item) for item in value]
    return value


def _ensure_agent_version(
    db,
    version: str,
    *,
    parent_id: str | None = None,
    notes: str = "",
) -> AgentVersion:
    """Create a Track C agent version row when strategy versions are first used."""
    normalized = str(version or "v1").strip() or "v1"
    row = db.query(AgentVersion).filter(AgentVersion.name == normalized).first()
    if row is None:
        row = AgentVersion(
            name=normalized,
            agent_type="llm",
            model_name="",
            prompt_version=normalized,
            config={"track": "C", "strategy_version": normalized},
            parent_version_id=parent_id,
            notes=notes,
        )
        db.add(row)
        db.flush()
    elif parent_id and not row.parent_version_id and row.id != parent_id:
        row.parent_version_id = parent_id
        db.flush()
    return row


def _seat_of(players, player_id: str | None) -> int | None:
    if not player_id:
        return None
    for p in players:
        if getattr(p, "id", None) == player_id:
            return getattr(p, "seat_no", None)
    return None


def _speech_tag(content: dict) -> str:
    if content.get("last_words"):
        return "LAST"
    if content.get("badge_campaign"):
        return "BADGE"
    if content.get("pk_speech"):
        return "PK"
    return ""


def save_game_start(state: GameState, model_name: str = "", prompt_version: str = "v1") -> Game:
    db = SessionLocal()
    try:
        game = Game(
            id=state.id,
            status="running",
            current_day=0,
            current_phase="SETUP",
            seed=str(getattr(state, "seed", "")),
            started_at=_now(),
        )
        db.add(game)
        for p in state.players:
            db.add(
                Player(
                    id=p.id,
                    game_id=state.id,
                    seat_no=p.seat,
                    name=p.name,
                    role=p.role.value,
                    is_ai=p.is_ai,
                    agent_type=p.agent_type,
                    model_name=p.model_name or model_name,
                    prompt_version=p.prompt_version or prompt_version,
                    is_alive=p.alive,
                )
            )
        db.commit()
        return game
    finally:
        db.close()


def save_event(game_id: str, event: GameEvent) -> None:
    db = SessionLocal()
    try:
        db.add(
            GameEvent(
                id=event.id,
                game_id=game_id,
                day=event.day,
                phase=event.phase.value if hasattr(event.phase, "value") else str(event.phase),
                event_type=event.type.value if hasattr(event.type, "value") else str(event.type),
                actor_id=event.payload.get("actor_id"),
                target_id=event.payload.get("target_id"),
                visibility=event.visibility,
                content=event.payload,
            )
        )
        db.commit()
    finally:
        db.close()


def save_decision(
    game_id: str,
    player_id: str,
    day: int,
    phase: str,
    observation: dict,
    action: dict,
    raw: str,
    latency_ms: int | None = None,
    *,
    candidate_actions: list | None = None,
    visible_facts: list | None = None,
    confidence: float | None = None,
    prompt_hash: str | None = None,
    cost_usd: float | None = None,
    model_name: str | None = None,
    provider: str | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
) -> None:
    db = SessionLocal()
    try:
        db.add(
            AgentDecision(
                game_id=game_id,
                player_id=player_id,
                day=day,
                phase=phase,
                observation=observation,
                legal_actions=[],
                parsed_action=action,
                raw_output=raw,
                latency_ms=latency_ms,
                # v2 DecisionTrace fields
                candidate_actions=candidate_actions or [],
                visible_facts=visible_facts or [],
                confidence=confidence,
                prompt_hash=prompt_hash,
                cost_usd=cost_usd,
                model_name=model_name,
                provider=provider,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
        )
        db.commit()
    finally:
        db.close()


def save_vote(game_id: str, day: int, voter_id: str, target_id: str) -> None:
    db = SessionLocal()
    try:
        db.add(Vote(game_id=game_id, day=day, voter_id=voter_id, target_id=target_id))
        db.commit()
    finally:
        db.close()


def save_snapshot(game_id: str, day: int, phase: str, truth: dict, public: dict) -> None:
    db = SessionLocal()
    try:
        db.add(GameSnapshot(game_id=game_id, day=day, phase=phase, truth_state=truth, public_state=public))
        db.commit()
    finally:
        db.close()


def save_game_end(state: GameState) -> None:
    """Persist final game state plus all events/decisions/votes in one transaction."""
    db = SessionLocal()
    try:
        game = db.query(Game).filter(Game.id == state.id).first()
        if game is None:
            return
        game.status = "finished"
        game.winner = state.winner.value if state.winner else None
        game.current_day = state.day
        game.current_phase = state.phase.value
        game.finished_at = _now()

        for p in state.players:
            player = db.query(Player).filter(Player.id == p.id).first()
            if player:
                player.is_alive = p.alive
                player.death_day = p.death_day
                player.death_reason = p.death_reason

        # Idempotent bulk-save of events: clear and re-insert (run once at game_end).
        db.query(GameEvent).filter(GameEvent.game_id == state.id).delete()
        for seq, event in enumerate(state.events):
            payload = _clean(event.payload) if isinstance(event.payload, dict) else {}
            phase = event.phase.value if hasattr(event.phase, "value") else str(event.phase)
            event_type = event.type.value if hasattr(event.type, "value") else str(event.type)
            db.add(
                GameEvent(
                    id=event.id,
                    game_id=state.id,
                    seq=seq,
                    ts=float(event.ts or 0.0),
                    day=event.day,
                    phase=phase,
                    event_type=event_type,
                    actor_id=payload.get("actor_id") or payload.get("voter_id") or payload.get("hunter_id"),
                    target_id=payload.get("target_id") or (payload.get("target") or {}).get("id")
                    if isinstance(payload.get("target"), dict)
                    else payload.get("target_id"),
                    visibility=event.visibility,
                    content=payload,
                )
            )

        # Bulk-save decisions
        db.query(AgentDecision).filter(AgentDecision.game_id == state.id).delete()
        for record in state.decision_records:
            db.add(
                AgentDecision(
                    id=record.id,
                    game_id=state.id,
                    player_id=record.player_id,
                    day=record.day,
                    phase=str(record.phase),
                    observation=_clean(record.observation) if isinstance(record.observation, dict) else {},
                    legal_actions=list(record.legal_actions or []),
                    prompt_version=record.prompt_version or "v1",
                    raw_output=_clean(record.raw_output or ""),
                    parsed_action=_clean(record.parsed_action) if isinstance(record.parsed_action, dict) else {},
                    is_valid=bool(record.is_valid),
                    error_type=record.error_type,
                    latency_ms=record.latency_ms,
                    prompt_tokens=record.prompt_tokens,
                    completion_tokens=record.completion_tokens,
                    # v2 DecisionTrace fields
                    candidate_actions=_clean(getattr(record, "candidate_actions", None) or []),
                    visible_facts=_clean(getattr(record, "visible_facts", None) or []),
                    confidence=getattr(record, "confidence", None),
                    prompt_hash=getattr(record, "prompt_hash", None),
                    cost_usd=getattr(record, "cost_usd", None),
                    model_name=getattr(record, "model_name", None),
                    provider=getattr(record, "provider", None),
                    decision_metadata=_clean(getattr(record, "metadata", None) or {}),
                )
            )

        # Bulk-save votes from history
        db.query(Vote).filter(Vote.game_id == state.id).delete()
        for day, voted in state.vote_history.items():
            for voter_id, target_id in voted.items():
                db.add(
                    Vote(
                        game_id=state.id,
                        day=int(day),
                        voter_id=voter_id,
                        target_id=target_id,
                    )
                )

        # Final snapshot for replay
        db.query(GameSnapshot).filter(GameSnapshot.game_id == state.id).delete()
        try:
            truth = _clean(state.moderator_dict())
            public = _clean(state.public_dict())
            db.add(
                GameSnapshot(
                    game_id=state.id,
                    day=state.day,
                    phase=state.phase.value,
                    truth_state=truth,
                    public_state=public,
                )
            )
        except Exception:
            pass

        # Per-player evaluation metrics (Track B baseline) — computed here so the
        # downstream leaderboard / replay UI has data without a separate worker.
        db.query(Evaluation).filter(Evaluation.game_id == state.id).delete()
        for metric in _compute_player_metrics(state):
            db.add(Evaluation(**metric))

        # Update aggregated leaderboard entries (Track B leaderboard).
        winner = state.winner.value if state.winner else None
        for p in state.players:
            agent_label = f"{p.agent_type or 'ai'}+{p.role.value}"
            entry = (
                db.query(LeaderboardEntry)
                .filter(LeaderboardEntry.name == agent_label, LeaderboardEntry.role == p.role.value)
                .first()
            )
            if entry is None:
                entry = LeaderboardEntry(name=agent_label, role=p.role.value)
                db.add(entry)
                db.flush()
            entry.games_played = (entry.games_played or 0) + 1
            won = (winner == "village" and p.alignment.value == "village") or (
                winner == "wolf" and p.alignment.value == "wolf"
            )
            if won:
                entry.wins = (entry.wins or 0) + 1
            else:
                entry.losses = (entry.losses or 0) + 1
            entry.win_rate = float(entry.wins) / max(1, entry.games_played)

        db.commit()
    finally:
        db.close()
    try:
        save_published_review(state)
    except Exception:
        pass


def _compute_player_metrics(state: GameState) -> list[dict]:
    """Compute simple per-player KPIs the leaderboard / review surface uses.

    Kept intentionally simple here — Track B's reviewer agent can later add
    deeper qualitative metrics by writing extra `Evaluation` rows.
    """
    metrics: list[dict] = []
    winner = state.winner.value if state.winner else None

    chat_by_actor: dict[str, int] = {}
    for event in state.events:
        if event.type.value == "CHAT_MESSAGE":
            actor = event.payload.get("actor_id")
            if actor:
                chat_by_actor[actor] = chat_by_actor.get(actor, 0) + 1

    for p in state.players:
        survived = p.alive
        won = winner is not None and p.alignment.value == winner
        metrics.append(
            {
                "game_id": state.id,
                "player_id": p.id,
                "metric_name": "win",
                "metric_value": 1.0 if won else 0.0,
                "comment": f"role={p.role.value} alignment={p.alignment.value}",
            }
        )
        metrics.append(
            {
                "game_id": state.id,
                "player_id": p.id,
                "metric_name": "survived",
                "metric_value": 1.0 if survived else 0.0,
                "comment": p.death_reason or "",
            }
        )
        metrics.append(
            {
                "game_id": state.id,
                "player_id": p.id,
                "metric_name": "speech_count",
                "metric_value": float(chat_by_actor.get(p.id, 0)),
                "comment": "",
            }
        )
    return metrics


def save_evaluation(game_id: str, player_id: str, metric_name: str, value: float, comment: str = "") -> None:
    db = SessionLocal()
    try:
        db.add(
            Evaluation(
                game_id=game_id, player_id=player_id, metric_name=metric_name, metric_value=value, comment=comment
            )
        )
        db.commit()
    finally:
        db.close()


def get_game(game_id: str) -> dict | None:
    db = SessionLocal()
    try:
        game = db.query(Game).filter(Game.id == game_id).first()
        if not game:
            return None
        return {
            "id": game.id,
            "status": game.status,
            "current_day": game.current_day,
            "current_phase": game.current_phase,
            "winner": game.winner,
            "seed": game.seed,
            "created_at": game.created_at.isoformat() if game.created_at else None,
            "players": [
                {
                    "id": p.id,
                    "seat_no": p.seat_no,
                    "name": p.name,
                    "role": p.role,
                    "is_alive": p.is_alive,
                    "agent_type": p.agent_type,
                }
                for p in game.players
            ],
            "events": [
                {
                    "id": e.id,
                    "day": e.day,
                    "phase": e.phase,
                    "event_type": e.event_type,
                    "actor_id": e.actor_id,
                    "visibility": e.visibility,
                    "content": e.content,
                }
                for e in game.events
            ],
        }
    finally:
        db.close()


def list_games(limit: int = 20) -> list[dict]:
    db = SessionLocal()
    try:
        games = db.query(Game).order_by(Game.created_at.desc()).limit(limit).all()
        results = []
        for g in games:
            players = [
                {"name": p.name, "role": p.role, "is_alive": p.is_alive, "seat_no": p.seat_no} for p in g.players
            ]
            results.append(
                {
                    "id": g.id,
                    "status": g.status,
                    "winner": g.winner,
                    "current_day": g.current_day,
                    "seed": g.seed,
                    "created_at": g.created_at.isoformat() if g.created_at else None,
                    "player_count": len(players),
                    "players": players,
                }
            )
        return results
    finally:
        db.close()


def get_game_summary(game_id: str) -> dict | None:
    """Lightweight summary for frontend display."""
    db = SessionLocal()
    try:
        game = db.query(Game).filter(Game.id == game_id).first()
        if not game:
            return None
        speeches = [
            {
                "day": e.day,
                "phase": e.phase,
                "ts": float(e.ts or 0.0),
                "speaker": (e.content or {}).get("actor_name", ""),
                "speaker_seat": _seat_of(game.players, (e.content or {}).get("actor_id")),
                "text": _clean(str((e.content or {}).get("speech", "")))[:400],
                "tag": _speech_tag(e.content or {}),
            }
            for e in sorted(game.events, key=lambda x: (x.seq or 0, x.created_at))
            if e.event_type == "CHAT_MESSAGE"
        ]
        votes = [
            {
                "day": e.day,
                "ts": float(e.ts or 0.0),
                "voter": (e.content or {}).get("voter_name", ""),
                "voter_seat": _seat_of(game.players, (e.content or {}).get("voter_id")),
                "target": (e.content or {}).get("target_name", ""),
                "target_seat": _seat_of(game.players, (e.content or {}).get("target_id")),
            }
            for e in sorted(game.events, key=lambda x: (x.seq or 0, x.created_at))
            if e.event_type == "VOTE_CAST"
        ]
        deaths = [
            {
                "day": e.day,
                "ts": float(e.ts or 0.0),
                "player": (e.content or {}).get("player_name", ""),
                "player_seat": _seat_of(game.players, (e.content or {}).get("player_id")),
                "reason": (e.content or {}).get("reason", ""),
            }
            for e in sorted(game.events, key=lambda x: (x.seq or 0, x.created_at))
            if e.event_type == "PLAYER_DIED"
        ]
        decision_count = db.query(AgentDecision).filter(AgentDecision.game_id == game_id).count()
        return _clean(
            {
                "id": game.id,
                "status": game.status,
                "winner": game.winner,
                "day": game.current_day,
                "seed": game.seed,
                "players": [
                    {
                        "name": p.name,
                        "role": p.role,
                        "alive": p.is_alive,
                        "seat": p.seat_no,
                        "is_ai": p.is_ai,
                        "death_day": p.death_day,
                        "death_reason": p.death_reason,
                    }
                    for p in sorted(game.players, key=lambda x: x.seat_no)
                ],
                "speeches": speeches,
                "votes": votes,
                "deaths": deaths,
                "decision_count": decision_count,
                "event_count": len(game.events),
                "created_at": game.created_at.isoformat() if game.created_at else None,
                "finished_at": game.finished_at.isoformat() if game.finished_at else None,
            }
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Track B / C accessors — used by the reserved endpoints in backend/app.py.
# Implementations are intentionally lightweight; the heavy reviewer/evolution
# logic will live in dedicated modules under backend/eval/ once those tracks
# are picked up.
# ---------------------------------------------------------------------------


def get_replay(game_id: str, *, show_private: bool = False) -> dict | None:
    """Return the data the frontend replay UI needs to walk a finished game."""
    db = SessionLocal()
    try:
        game = db.query(Game).filter(Game.id == game_id).first()
        if game is None:
            return None
        snapshot = (
            db.query(GameSnapshot).filter(GameSnapshot.game_id == game_id).order_by(GameSnapshot.day.desc()).first()
        )
        events = [
            {
                "id": e.id,
                "seq": e.seq,
                "ts": e.ts,
                "day": e.day,
                "phase": e.phase,
                "type": e.event_type,
                "actor_id": e.actor_id,
                "target_id": e.target_id,
                "visibility": e.visibility,
                "content": e.content,
            }
            for e in sorted(game.events, key=lambda x: (x.seq or 0, x.created_at))
            if show_private or e.visibility == "public"
        ]
        decisions = (
            db.query(AgentDecision)
            .filter(AgentDecision.game_id == game_id)
            .order_by(AgentDecision.day, AgentDecision.created_at)
            .all()
        )
        return _clean(
            {
                "id": game.id,
                "winner": game.winner,
                "day": game.current_day,
                "phase": game.current_phase,
                "players": [
                    {
                        "id": p.id,
                        "name": p.name,
                        "seat": p.seat_no,
                        "role": p.role,
                        "is_alive": p.is_alive,
                        "is_ai": p.is_ai,
                        "agent_type": p.agent_type,
                        "death_day": p.death_day,
                        "death_reason": p.death_reason,
                    }
                    for p in sorted(game.players, key=lambda x: x.seat_no)
                ],
                "snapshot": (snapshot.truth_state if show_private else snapshot.public_state) if snapshot else None,
                "events": events,
                "decisions": [
                    {
                        "id": d.id,
                        "player_id": d.player_id,
                        "day": d.day,
                        "phase": d.phase,
                        "parsed_action": d.parsed_action,
                        "raw_output": d.raw_output[:400] if d.raw_output else "",
                        "is_valid": d.is_valid,
                        "latency_ms": d.latency_ms,
                    }
                    for d in decisions
                ],
            }
        )
    finally:
        db.close()


def get_game_metrics(game_id: str) -> dict | None:
    """Return Track B metrics for one game.

    Prefer the rich published review artifact when available; otherwise fall
    back to the lightweight Evaluation rows used by the earlier MVP.
    """
    db = SessionLocal()
    try:
        init_db()
        game = db.query(Game).filter(Game.id == game_id).first()
        if game is None:
            return None
        review = db.query(PublishedReview).filter(PublishedReview.game_id == game_id).first()
        if review is not None:
            payload = review.report_json or {}
            return _clean(
                {
                    "game_id": game_id,
                    "winner": game.winner,
                    "scoreboard": payload.get("scoreboard", []),
                    "player_scores": payload.get("metadata", {}).get("player_scores", []),
                    "speech_acts": review.speech_acts or [],
                    "suspicion_matrix": review.suspicion_matrix or [],
                    "validation": review.validation_result or {},
                }
            )
        rows = db.query(Evaluation).filter(Evaluation.game_id == game_id).all()
        grouped: dict[str, list[dict]] = {}
        for row in rows:
            grouped.setdefault(row.player_id or "_global", []).append(
                {
                    "metric": row.metric_name,
                    "value": row.metric_value,
                    "comment": row.comment,
                }
            )
        return {"game_id": game_id, "winner": game.winner, "metrics": grouped}
    finally:
        db.close()


def get_leaderboard(*, role: str | None = None, limit: int = 20) -> list[dict]:
    db = SessionLocal()
    try:
        init_db()
        review_sample_limit = max(100, min(max(1, limit) * 5, 1000))
        approved = (
            db.query(PublishedReview)
            .filter(PublishedReview.publish_allowed.is_(True))
            .order_by(PublishedReview.published_at.desc(), PublishedReview.created_at.desc())
            .limit(review_sample_limit)
            .all()
        )
        if approved:
            reports = [reconstruct_review_report(row.report_json or {}) for row in approved if row.report_json]
            aggregated = LeaderboardAggregator().aggregate_all(reports)
            payload = {key: value.to_dict() for key, value in aggregated.items()}
            if role:
                payload["role"]["entries"] = [
                    entry
                    for entry in payload["role"]["entries"]
                    if entry["display_name"] == role or entry["key"] == role
                ][:limit]
            else:
                for key in payload:
                    payload[key]["entries"] = payload[key]["entries"][:limit]
            return _clean(payload)

        query = db.query(LeaderboardEntry)
        if role:
            query = query.filter(LeaderboardEntry.role == role)
        rows = query.order_by(LeaderboardEntry.win_rate.desc(), LeaderboardEntry.games_played.desc()).limit(limit).all()
        return _clean(
            {
                "legacy": [
                    {
                        "id": r.id,
                        "agent_version_id": r.agent_version_id,
                        "name": r.name,
                        "role": r.role,
                        "games_played": r.games_played,
                        "wins": r.wins,
                        "losses": r.losses,
                        "win_rate": round(r.win_rate or 0.0, 4),
                        "kpi": {
                            "speech_quality": r.kpi_speech_quality,
                            "vote_accuracy": r.kpi_vote_accuracy,
                            "skill_efficiency": r.kpi_skill_efficiency,
                            "survival_value": r.kpi_survival_value,
                        },
                        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                    }
                    for r in rows
                ]
            }
        )
    finally:
        db.close()


def get_review_reports(game_id: str) -> dict | None:
    db = SessionLocal()
    try:
        init_db()
        published = db.query(PublishedReview).filter(PublishedReview.game_id == game_id).first()
        if published is not None:
            return _clean(
                {
                    "report_id": published.id,
                    "game_id": published.game_id,
                    "status": published.status,
                    "view_scope": published.view_scope,
                    "grade": published.grade,
                    "score": published.score,
                    "publish_allowed": published.publish_allowed,
                    "review_report": published.report_json or {},
                    "markdown": published.markdown,
                    "validation_result": published.validation_result or {},
                    "replay_bundle": published.replay_bundle or {},
                    "speech_acts": published.speech_acts or [],
                    "suspicion_matrix": published.suspicion_matrix or [],
                    "repair_history": published.repair_history or [],
                    "metadata": published.extra_metadata or {},
                    "html_report": (published.extra_metadata or {}).get("html_report"),
                    "created_at": published.created_at.isoformat() if published.created_at else None,
                    "published_at": published.published_at.isoformat() if published.published_at else None,
                }
            )
        rows = (
            db.query(ReviewReport)
            .filter(ReviewReport.game_id == game_id)
            .order_by(ReviewReport.day, ReviewReport.created_at)
            .all()
        )
        return {
            "status": "approved" if rows else "missing",
            "game_id": game_id,
            "publish_allowed": bool(rows),
            "legacy": [
                {
                    "id": r.id,
                    "player_id": r.player_id,
                    "severity": r.severity,
                    "day": r.day,
                    "phase": r.phase,
                    "title": r.title,
                    "summary": r.summary,
                    "counterfactual": r.counterfactual,
                    "suggestion": r.suggestion,
                    "metrics": r.metrics,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ],
        }
    finally:
        db.close()


def get_review_html(game_id: str) -> str | None:
    payload = get_review_reports(game_id)
    if not payload:
        return None
    html_report = payload.get("html_report")
    if isinstance(html_report, str) and html_report:
        return html_report
    return None


def get_review_markdown(game_id: str) -> str | None:
    """Return the published markdown report for a game, or None when only the
    legacy per-bad-case rows exist (no PublishedReview)."""
    payload = get_review_reports(game_id)
    if not payload:
        return None
    markdown = payload.get("markdown")
    if isinstance(markdown, str) and markdown.strip():
        return markdown
    return None


def save_published_review(state: GameState) -> dict[str, Any]:
    document = generate_published_review_document(state)
    init_db()
    db = SessionLocal()
    try:
        row = db.query(PublishedReview).filter(PublishedReview.game_id == state.id).first()
        if row is None:
            row = PublishedReview(game_id=state.id)
            db.add(row)
        row.status = document.status
        row.view_scope = document.view_scope
        row.grade = str(document.validation_result.get("grade") or document.status)
        row.score = float(document.validation_result.get("score") or 0.0)
        row.publish_allowed = bool(document.validation_result.get("publish_allowed"))
        row.report_json = document.review_report
        row.markdown = document.markdown
        row.validation_result = document.validation_result
        row.replay_bundle = document.replay_bundle
        row.speech_acts = document.speech_acts
        row.suspicion_matrix = document.suspicion_matrix
        row.repair_history = document.repair_history
        row.extra_metadata = document.metadata
        row.published_at = _now() if row.publish_allowed else None
        db.commit()
        return document.to_dict()
    finally:
        db.close()


def _knowledge_row_to_dict(row: StrategyKnowledgeDoc) -> dict[str, Any]:
    return {
        "doc_id": row.id,
        "doc_type": row.doc_type,
        "role": row.role,
        "phase": row.phase,
        "source_game_id": (row.source_report_ids[0] if row.source_report_ids else None),
        "persona_scope": row.persona_scope,
        "situation_pattern": row.situation_pattern,
        "trigger_conditions": row.trigger_conditions or [],
        "recommended_action": row.recommended_action,
        "avoid_action": row.avoid_action,
        "rationale": row.rationale,
        "evidence_summary": row.evidence_summary,
        "source_report_ids": row.source_report_ids or [],
        "source_item_ids": row.source_item_ids or [],
        "source_event_ids": row.source_event_ids or [],
        "counterfactual_ids": row.counterfactual_ids or [],
        "expected_metric_effects": row.expected_metric_effects or [],
        "quality_score": row.quality_score or 0.0,
        "confidence": row.confidence or 0.0,
        "usage_count": row.usage_count or 0,
        "success_count": row.success_count or 0,
        "failure_count": row.failure_count or 0,
        "status": row.status,
        "tags": row.tags or [],
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        # L0-L4 Confidence Tier
        "confidence_tier": row.confidence_tier or "L3_strategic",
        "judge_agreement": row.judge_agreement,
        "times_upvoted": row.times_upvoted or 0,
        "contradiction_count": row.contradiction_count or 0,
        "games_since_creation": row.games_since_creation or 0,
        "human_verdict": row.human_verdict,
        # Access Control
        "visibility_scope": row.visibility_scope or "public",
        "allowed_roles": row.allowed_roles,
        "deidentified": bool(row.deidentified),
        "contains_current_game_private_info": bool(row.contains_current_game_private_info),
        # Applicability
        "applicability_role": row.applicability_role,
        "applicability_phase": row.applicability_phase,
        "min_players": row.min_players,
        "max_players": row.max_players,
        "required_public_facts": row.required_public_facts or [],
        "forbidden_public_facts": row.forbidden_public_facts or [],
        "required_private_state": row.required_private_state or [],
    }


def _upsert_strategy_knowledge_rows(db, docs: list[StrategyKnowledgeDocData]) -> list[dict[str, Any]]:
    saved: list[dict[str, Any]] = []
    seen: set[str] = set()
    for doc in docs:
        if doc.doc_id in seen:
            continue
        seen.add(doc.doc_id)
        row = db.query(StrategyKnowledgeDoc).filter(StrategyKnowledgeDoc.id == doc.doc_id).first()
        if row is None:
            row = StrategyKnowledgeDoc(id=doc.doc_id)
            db.add(row)
        row.doc_type = doc.doc_type
        row.role = doc.role
        row.phase = doc.phase
        row.persona_scope = doc.persona_scope
        row.situation_pattern = doc.situation_pattern
        row.trigger_conditions = doc.trigger_conditions
        row.recommended_action = doc.recommended_action
        row.avoid_action = doc.avoid_action
        row.rationale = doc.rationale
        row.evidence_summary = doc.evidence_summary
        row.source_report_ids = doc.source_report_ids
        row.source_item_ids = doc.source_item_ids
        row.source_event_ids = doc.source_event_ids
        row.counterfactual_ids = doc.counterfactual_ids
        row.expected_metric_effects = doc.expected_metric_effects
        row.quality_score = doc.quality_score
        row.confidence = doc.confidence
        row.usage_count = doc.usage_count
        row.success_count = doc.success_count
        row.failure_count = doc.failure_count
        row.status = doc.status
        row.tags = doc.tags

        # L0-L4 Confidence Tier
        row.confidence_tier = getattr(doc, "confidence_tier", None) or "L3_strategic"
        row.judge_agreement = getattr(doc, "judge_agreement", None)
        row.times_upvoted = getattr(doc, "times_upvoted", 0)
        row.contradiction_count = getattr(doc, "contradiction_count", 0)
        row.games_since_creation = getattr(doc, "games_since_creation", 0)
        row.human_verdict = getattr(doc, "human_verdict", None)

        # Access Control
        row.visibility_scope = getattr(doc, "visibility_scope", None) or "public"
        row.allowed_roles = getattr(doc, "allowed_roles", None)
        row.deidentified = bool(getattr(doc, "deidentified", False))
        row.contains_current_game_private_info = bool(getattr(doc, "contains_current_game_private_info", False))

        # Applicability
        row.applicability_role = getattr(doc, "applicability_role", None)
        row.applicability_phase = getattr(doc, "applicability_phase", None)
        row.min_players = getattr(doc, "min_players", None)
        row.max_players = getattr(doc, "max_players", None)
        row.required_public_facts = getattr(doc, "required_public_facts", None) or []
        row.forbidden_public_facts = getattr(doc, "forbidden_public_facts", None) or []
        row.required_private_state = getattr(doc, "required_private_state", None) or []

        saved.append(doc.to_dict())
    return saved


def extract_strategy_knowledge_from_game(game_id: str) -> list[dict[str, Any]]:
    init_db()
    payload = get_review_reports(game_id)
    if not payload or payload.get("status") != "approved":
        return []
    from backend.eval.review import StrategyKnowledgeExtractor

    docs = StrategyKnowledgeExtractor().extract(payload)
    db = SessionLocal()
    try:
        saved = _upsert_strategy_knowledge_rows(db, docs)
        db.commit()
        return _clean(saved)
    finally:
        db.close()


def list_strategy_knowledge(
    *,
    role: str | None = None,
    phase: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    init_db()
    db = SessionLocal()
    try:
        query = db.query(StrategyKnowledgeDoc)
        if role:
            query = query.filter(StrategyKnowledgeDoc.role == role)
        if phase:
            query = query.filter(StrategyKnowledgeDoc.phase == phase)
        if status:
            query = query.filter(StrategyKnowledgeDoc.status == status)
        rows = (
            query.order_by(StrategyKnowledgeDoc.quality_score.desc(), StrategyKnowledgeDoc.updated_at.desc())
            .limit(limit)
            .all()
        )
        return _clean([_knowledge_row_to_dict(row) for row in rows])
    finally:
        db.close()


def retrieve_strategy_knowledge(query: StrategyRetrievalQuery) -> list[dict[str, Any]]:
    """Retrieve strategy knowledge with the 4-filter safety pipeline.

    Filters (all must pass):
      1. confidence_allowed — L0-L3 only, no rejected, L3 with high agreement
      2. visibility_allowed — agent role/wolf status can see this
      3. leaks_current_game_private_info — no current-game info leak
      4. applicability_matches — knowledge applies to current situation
    """
    init_db()
    db = SessionLocal()
    try:
        rows = db.query(StrategyKnowledgeDoc).filter(StrategyKnowledgeDoc.status.in_(["active", "candidate"])).all()
        store = StrategyKnowledgeStore()
        docs = [StrategyKnowledgeDocData(**_knowledge_row_to_dict(row)) for row in rows]
        store.upsert_many(docs)

        # Get raw candidates from BM25 + embedding hybrid search
        candidates_raw = store.retrieve(query)
        candidates = [asdict(item) for item in candidates_raw]

        # Apply 4-filter pipeline from knowledge_confidence
        from backend.eval.knowledge_confidence import applicability_matches
        from backend.eval.knowledge_confidence import confidence_allowed
        from backend.eval.knowledge_confidence import leaks_current_game_private_info
        from backend.eval.knowledge_confidence import visibility_allowed

        public_facts = set(query.situation_tags or [])
        private_state = set()

        filtered: list[dict[str, Any]] = []
        for doc in candidates:
            if not confidence_allowed(doc):
                continue
            is_wolf = query.role in {"Werewolf", "WhiteWolfKing", "BigBadWolf", "WolfCub", "AlphaWolf"}
            if not visibility_allowed(doc, query.role, is_wolf):
                continue
            if leaks_current_game_private_info(doc, getattr(query, "game_id", "") or ""):
                continue
            if not applicability_matches(
                doc,
                query.role,
                query.phase or "",
                getattr(query, "rule_variant", "standard_competition_v1") or "standard_competition_v1",
                getattr(query, "player_count", 0) or 0,
                public_facts,
                private_state,
            ):
                continue
            if doc.get("status") in ("disputed", "deprecated"):
                continue
            filtered.append(doc)

        filtered.sort(key=lambda d: d.get("quality_score", 0.0), reverse=True)
        return _clean(filtered[: query.top_k])
    finally:
        db.close()


def deprecate_strategy_knowledge(doc_id: str, reason: str = "") -> dict[str, Any]:
    init_db()
    db = SessionLocal()
    try:
        row = db.query(StrategyKnowledgeDoc).filter(StrategyKnowledgeDoc.id == doc_id).first()
        if row is None:
            raise KeyError(doc_id)
        row.status = "deprecated"
        tags = set(row.tags or [])
        if reason:
            tags.add(f"deprecated:{reason}")
        row.tags = sorted(tags)
        db.commit()
        return _clean(_knowledge_row_to_dict(row))
    finally:
        db.close()


def record_knowledge_usage(payload: dict[str, Any]) -> dict[str, Any]:
    init_db()
    db = SessionLocal()
    try:
        row = KnowledgeUsageFeedback(
            game_id=str(payload.get("game_id") or ""),
            decision_id=payload.get("decision_id"),
            player_id=str(payload.get("player_id") or ""),
            knowledge_doc_id=str(payload.get("knowledge_doc_id") or ""),
            retrieved=bool(payload.get("retrieved", True)),
            used=bool(payload.get("used", False)),
            decision_outcome=str(payload.get("decision_outcome") or ""),
            score_delta=float(payload.get("score_delta") or 0.0),
            helpful=bool(payload.get("helpful", False)),
            extra_metadata=payload.get("metadata") or {},
        )
        db.add(row)
        doc = db.query(StrategyKnowledgeDoc).filter(StrategyKnowledgeDoc.id == row.knowledge_doc_id).first()
        if doc is not None:
            doc.usage_count = int(doc.usage_count or 0) + 1
            if row.helpful:
                doc.success_count = int(doc.success_count or 0) + 1
            else:
                doc.failure_count = int(doc.failure_count or 0) + 1
            if doc.failure_count >= 3 and doc.success_count == 0:
                doc.status = "deprecated"
        db.commit()
        return {"id": row.id, "knowledge_doc_id": row.knowledge_doc_id, "helpful": row.helpful}
    finally:
        db.close()


def run_dream_job(report_ids: list[str] | None = None, *, from_version: str = "v1") -> dict[str, Any]:
    init_db()
    db = SessionLocal()
    try:
        query = db.query(PublishedReview).filter(PublishedReview.publish_allowed.is_(True))
        if report_ids:
            query = query.filter(PublishedReview.id.in_(report_ids) | PublishedReview.game_id.in_(report_ids))
        rows = query.order_by(PublishedReview.published_at.desc(), PublishedReview.created_at.desc()).limit(30).all()
        reports = []
        for row in rows:
            if not row.report_json:
                continue
            report = reconstruct_review_report(row.report_json)
            report.metadata["validation_result"] = row.validation_result or {
                "passed": bool(row.publish_allowed),
                "publish_allowed": bool(row.publish_allowed),
                "score": row.score,
            }
            report.metadata["quality_passed"] = bool(row.publish_allowed)
            reports.append(report)
        job = DreamJob()
        result = job.run(reports)
        saved_docs = _upsert_strategy_knowledge_rows(db, result.knowledge_docs)
        saved_patches: list[dict[str, Any]] = []
        for patch in result.candidate_patches:
            row = StrategyPatch(id=patch.patch_id)
            row.patch_type = patch.patch_type
            row.target_role = patch.target_role
            row.target_persona_scope = patch.target_persona_scope
            row.from_version = patch.from_version
            row.to_version = patch.to_version
            row.source_report_ids = patch.source_report_ids
            row.source_knowledge_doc_ids = patch.source_knowledge_doc_ids
            row.source_evidence_ids = patch.source_evidence_ids
            row.operations = [asdict(operation) for operation in patch.operations]
            row.expected_effects = patch.expected_effects
            row.safety_checks = patch.safety_checks
            row.validation_result = patch.safety_checks.get("validation") or {}
            row.status = patch.status
            db.merge(row)
            saved_patches.append(asdict(patch))
        db.commit()
        payload = {
            "knowledge_docs": saved_docs,
            "candidate_patches": saved_patches,
            "summary": asdict(result.summary),
        }
        return _clean(payload)
    finally:
        db.close()


def _role_card_to_dict(row: RoleStrategyCard) -> dict[str, Any]:
    return {
        "card_id": row.id,
        "role": row.role,
        "version": row.version,
        "parent_version": row.parent_version,
        "goal": row.goal,
        "speech_policy": row.speech_policy or [],
        "vote_policy": row.vote_policy or [],
        "skill_policy": row.skill_policy or [],
        "risk_rules": row.risk_rules or [],
        "retrieval_policy": row.retrieval_policy or {},
        "status": row.status,
        "created_from_patch_id": row.created_from_patch_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def list_role_strategy_cards(role: str | None = None) -> list[dict[str, Any]]:
    init_db()
    db = SessionLocal()
    try:
        query = db.query(RoleStrategyCard)
        if role:
            query = query.filter(RoleStrategyCard.role == role)
        rows = query.order_by(RoleStrategyCard.role, RoleStrategyCard.created_at.desc()).all()
        return _clean([_role_card_to_dict(row) for row in rows])
    finally:
        db.close()


def apply_strategy_patch(patch_id: str) -> dict[str, Any]:
    init_db()
    db = SessionLocal()
    try:
        patch = db.query(StrategyPatch).filter(StrategyPatch.id == patch_id).first()
        if patch is None:
            raise KeyError(patch_id)
        role = patch.target_role or "global"
        baseline = (
            db.query(RoleStrategyCard)
            .filter(RoleStrategyCard.role == role, RoleStrategyCard.version == patch.from_version)
            .first()
        )
        if baseline is None:
            baseline = RoleStrategyCard(
                role=role,
                version=patch.from_version,
                parent_version=None,
                goal=f"{role} baseline strategy",
                speech_policy=["基于当前可见事实发言，给出明确但不过度绝对的判断。"],
                vote_policy=["投票前核对公开发言、票型和已确认信息。"],
                skill_policy=["技能使用优先服务角色任务和阵营收益。"],
                risk_rules=["不得引用隐藏身份或历史局具体玩家。"],
                retrieval_policy={"top_k": 3, "min_quality": 0.4},
                status="active",
            )
            db.add(baseline)
        card = RoleStrategyCard(
            role=role,
            version=patch.to_version,
            parent_version=baseline.version,
            goal=baseline.goal,
            speech_policy=list(baseline.speech_policy or []),
            vote_policy=list(baseline.vote_policy or []),
            skill_policy=list(baseline.skill_policy or []),
            risk_rules=list(baseline.risk_rules or []),
            retrieval_policy=dict(baseline.retrieval_policy or {}),
            status="candidate",
            created_from_patch_id=patch.id,
        )
        for operation in patch.operations or []:
            section = operation.get("section")
            if section in {"speech_policy", "vote_policy", "skill_policy", "risk_rules"}:
                values = list(getattr(card, section) or [])
                values.append(str(operation.get("new_value") or ""))
                setattr(card, section, values)
        patch.status = "applied"
        db.add(card)
        db.commit()
        return _clean(_role_card_to_dict(card))
    finally:
        db.close()


def run_evolution_cycle(report_ids: list[str] | None = None, *, seeds: list[int] | None = None) -> dict[str, Any]:
    init_db()
    dream = run_dream_job(report_ids, from_version="v1")
    from backend.eval.evolution import TournamentRunner
    from backend.eval.evolution import VersionManager

    manager = VersionManager()
    runner = TournamentRunner()
    patch_results: list[dict[str, Any]] = []
    db = SessionLocal()
    try:
        for patch_payload in dream.get("candidate_patches", []):
            patch = StrategyPatchData(
                patch_id=patch_payload["patch_id"],
                patch_type=patch_payload["patch_type"],
                target_role=patch_payload.get("target_role"),
                target_persona_scope=patch_payload.get("target_persona_scope"),
                from_version=patch_payload.get("from_version", "v1"),
                to_version=patch_payload.get("to_version", ""),
                source_report_ids=list(patch_payload.get("source_report_ids", [])),
                source_knowledge_doc_ids=list(patch_payload.get("source_knowledge_doc_ids", [])),
                source_evidence_ids=list(patch_payload.get("source_evidence_ids", [])),
                operations=[],
                expected_effects=list(patch_payload.get("expected_effects", [])),
                safety_checks=dict(patch_payload.get("safety_checks", {})),
                status=patch_payload.get("status", "validated"),
            )
            # Use DB payload for operations in persistence; VersionManager only needs new values.
            patch.operations = []
            for item in patch_payload.get("operations", []):
                from backend.eval.evolution import PatchOperation

                patch.operations.append(PatchOperation(**item))
            candidate_version = manager.create_candidate(patch)
            candidate_card = candidate_version.card
            tournament = runner.run_ab_tournament(
                baseline_version=patch.from_version,
                candidate_version=candidate_version.version,
                target_role=patch.target_role,
                seeds=seeds or list(range(1, 21)),
            )
            if tournament.decision.get("accepted"):
                final_version = manager.promote(candidate_version.version)
                patch_status = "promoted"
            else:
                final_version = manager.rollback(candidate_version.version)
                patch_status = "rolled_back"
            baseline_version = _ensure_agent_version(
                db,
                patch.from_version,
                notes="Track C baseline strategy version",
            )
            challenger_version = _ensure_agent_version(
                db,
                candidate_version.version,
                parent_id=baseline_version.id,
                notes=f"Track C candidate generated from patch {patch.patch_id}",
            )
            db.add(
                EvolutionTournament(
                    id=tournament.tournament_id,
                    baseline_version=tournament.baseline_version,
                    candidate_version=tournament.candidate_version,
                    target_role=tournament.target_role,
                    seeds=tournament.seeds,
                    baseline_results=tournament.baseline_results,
                    candidate_results=tournament.candidate_results,
                    comparison=tournament.comparison,
                    decision=tournament.decision,
                    status=tournament.status,
                )
            )
            db.add(
                EvolutionRound(
                    round_no=(db.query(EvolutionRound).count() + 1),
                    baseline_version_id=baseline_version.id,
                    challenger_version_id=challenger_version.id,
                    games_per_round=len(tournament.seeds),
                    baseline_wins=int(tournament.comparison.get("baseline_wins", 0)),
                    challenger_wins=int(tournament.comparison.get("candidate_wins", 0)),
                    delta_win_rate=(
                        float(tournament.comparison.get("candidate_wins", 0)) / max(len(tournament.seeds), 1)
                        - float(tournament.comparison.get("baseline_wins", 0)) / max(len(tournament.seeds), 1)
                    ),
                    accepted=bool(tournament.decision.get("accepted")),
                    change_log=json.dumps(patch_payload, ensure_ascii=False),
                    finished_at=_now(),
                )
            )
            patch_results.append(
                {
                    "patch": {**patch_payload, "status": patch_status},
                    "candidate_card": candidate_card.to_dict(),
                    "final_version": asdict(final_version),
                    "tournament": tournament.to_dict(),
                }
            )
        db.commit()
        acceptance_audit = _build_bc_acceptance_audit_from_db(db, limit_games=200)
        leaderboard = [
            {
                "version": item["tournament"]["candidate_version"],
                "baseline_version": item["tournament"]["baseline_version"],
                "target_role": item["tournament"].get("target_role"),
                "games": item["tournament"]["comparison"].get("total_games"),
                "win_rate": (
                    item["tournament"]["comparison"].get("candidate_wins", 0)
                    / max(item["tournament"]["comparison"].get("total_games", 1), 1)
                ),
                "avg_score": item["tournament"]["comparison"].get("candidate_avg_score"),
                "role_task_delta": item["tournament"]["comparison"].get("role_task_score_delta"),
                "critical_mistakes_delta": item["tournament"]["comparison"].get("critical_mistakes_delta"),
                "info_leak_count": item["tournament"]["comparison"].get("info_leak_count"),
                "invalid_action_rate": item["tournament"]["comparison"].get("invalid_action_rate"),
                "fallback_count": item["tournament"]["comparison"].get("candidate_fallback_count"),
                "decision": "promote" if item["tournament"]["decision"].get("accepted") else "rollback",
            }
            for item in patch_results
        ]
        return _clean(
            {
                "dream": dream,
                "patch_results": patch_results,
                "leaderboard": leaderboard,
                "summary": {
                    "knowledge_docs": len(dream.get("knowledge_docs", [])),
                    "validated_patches": len(dream.get("candidate_patches", [])),
                    "promoted": sum(1 for item in patch_results if item["patch"]["status"] == "promoted"),
                    "rolled_back": sum(1 for item in patch_results if item["patch"]["status"] == "rolled_back"),
                    "acceptance_pass_rate": acceptance_audit.get("overall_success_rate", 0.0),
                    "acceptance_passed": acceptance_audit.get("passed", False),
                },
                "acceptance_audit": acceptance_audit,
                "acceptance_metrics": acceptance_audit.get("metrics", []),
            }
        )
    finally:
        db.close()


def get_evolution_dashboard() -> dict[str, Any]:
    init_db()
    db = SessionLocal()
    try:
        patches = db.query(StrategyPatch).order_by(StrategyPatch.created_at.desc()).limit(20).all()
        tournaments = db.query(EvolutionTournament).order_by(EvolutionTournament.created_at.desc()).limit(20).all()
        acceptance_audit = _build_bc_acceptance_audit_from_db(db, limit_games=200)
        return _clean(
            {
                "active_versions": list_role_strategy_cards(),
                "knowledge": list_strategy_knowledge(limit=50),
                "patches": [
                    {
                        "patch_id": row.id,
                        "patch_type": row.patch_type,
                        "target_role": row.target_role,
                        "from_version": row.from_version,
                        "to_version": row.to_version,
                        "operations": row.operations or [],
                        "validation_result": row.validation_result or {},
                        "status": row.status,
                        "source_report_ids": row.source_report_ids or [],
                        "source_knowledge_doc_ids": row.source_knowledge_doc_ids or [],
                    }
                    for row in patches
                ],
                "tournaments": [
                    {
                        "tournament_id": row.id,
                        "baseline_version": row.baseline_version,
                        "candidate_version": row.candidate_version,
                        "target_role": row.target_role,
                        "comparison": row.comparison or {},
                        "decision": row.decision or {},
                        "status": row.status,
                    }
                    for row in tournaments
                ],
                "acceptance_audit": acceptance_audit,
                "acceptance_metrics": acceptance_audit.get("metrics", []),
            }
        )
    finally:
        db.close()


def list_agent_versions() -> list[dict]:
    db = SessionLocal()
    try:
        rows = db.query(AgentVersion).order_by(AgentVersion.created_at.desc()).all()
        return [
            {
                "id": r.id,
                "name": r.name,
                "agent_type": r.agent_type,
                "model_name": r.model_name,
                "prompt_version": r.prompt_version,
                "config": r.config,
                "parent_version_id": r.parent_version_id,
                "notes": r.notes,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    finally:
        db.close()


def register_agent_version(payload: dict) -> dict:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("name is required")
    db = SessionLocal()
    try:
        row = AgentVersion(
            name=name,
            agent_type=str(payload.get("agent_type") or "llm"),
            model_name=str(payload.get("model_name") or ""),
            prompt_version=str(payload.get("prompt_version") or "v1"),
            config=payload.get("config") or {},
            parent_version_id=payload.get("parent_version_id"),
            notes=str(payload.get("notes") or ""),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return {
            "id": row.id,
            "name": row.name,
            "agent_type": row.agent_type,
            "model_name": row.model_name,
            "prompt_version": row.prompt_version,
            "config": row.config,
            "parent_version_id": row.parent_version_id,
            "notes": row.notes,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
    finally:
        db.close()


def list_evolution_rounds(*, limit: int = 20) -> list[dict]:
    db = SessionLocal()
    try:
        rows = db.query(EvolutionRound).order_by(EvolutionRound.round_no.desc()).limit(limit).all()
        return [
            {
                "id": r.id,
                "round_no": r.round_no,
                "baseline_version_id": r.baseline_version_id,
                "challenger_version_id": r.challenger_version_id,
                "games_per_round": r.games_per_round,
                "baseline_wins": r.baseline_wins,
                "challenger_wins": r.challenger_wins,
                "delta_win_rate": r.delta_win_rate,
                "accepted": r.accepted,
                "change_log": r.change_log,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            }
            for r in rows
        ]
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Runtime + aggregate metrics for Track B/C dashboards
# ---------------------------------------------------------------------------

_WOLF_ROLES = {"Werewolf", "WhiteWolfKing", "BigBadWolf", "WolfCub", "AlphaWolf"}


def _stats_summary(values: list[float | int]) -> dict[str, float | int]:
    """Min/max/mean/p50/p95/sum summary for a numeric list.

    Returns a stable schema with zero defaults when input is empty so dashboard
    clients can render without null-checks.
    """
    if not values:
        return {"count": 0, "min": 0, "max": 0, "avg": 0.0, "p50": 0.0, "p95": 0.0, "sum": 0}
    ordered = sorted(values)
    n = len(ordered)

    def _quantile(q: float) -> float:
        idx = min(n - 1, max(0, int(round(q * (n - 1)))))
        return float(ordered[idx])

    total = sum(ordered)
    return {
        "count": n,
        "min": ordered[0],
        "max": ordered[-1],
        "avg": round(total / n, 3),
        "p50": _quantile(0.5),
        "p95": _quantile(0.95),
        "sum": total,
    }


def _new_runtime_bucket(
    *, seat_no: int | None = None, name: str | None = None, role: str | None = None
) -> dict[str, Any]:
    bucket: dict[str, Any] = {
        "decision_count": 0,
        "valid_count": 0,
        "invalid_count": 0,
        "llm_call_count": 0,
        "latency_values": [],
        "prompt_tokens_sum": 0,
        "completion_tokens_sum": 0,
        "speech_lengths": [],
    }
    if seat_no is not None:
        bucket["seat_no"] = seat_no
    if name is not None:
        bucket["name"] = name
    if role is not None:
        bucket["role"] = role
    return bucket


def _accumulate_bucket(bucket: dict[str, Any], decision: AgentDecision) -> None:
    bucket["decision_count"] += 1
    if decision.is_valid:
        bucket["valid_count"] += 1
    else:
        bucket["invalid_count"] += 1
    if decision.latency_ms is not None:
        bucket["llm_call_count"] += 1
        bucket["latency_values"].append(int(decision.latency_ms))
    if decision.prompt_tokens:
        bucket["prompt_tokens_sum"] += int(decision.prompt_tokens)
    if decision.completion_tokens:
        bucket["completion_tokens_sum"] += int(decision.completion_tokens)
    speech = (decision.parsed_action or {}).get("speech") if isinstance(decision.parsed_action, dict) else None
    if isinstance(speech, str) and speech.strip():
        bucket["speech_lengths"].append(len(speech))


def _finalize_bucket(bucket: dict[str, Any]) -> None:
    latencies = bucket.pop("latency_values", [])
    speech_lengths = bucket.pop("speech_lengths", [])
    bucket["latency_ms"] = _stats_summary(latencies)
    bucket["speech_char_len"] = _stats_summary(speech_lengths)
    bucket["validity_rate"] = (
        round(bucket["valid_count"] / bucket["decision_count"], 4) if bucket["decision_count"] else 0.0
    )


_REVIEW_SIGNAL_SECTIONS = (
    "bad_cases",
    "turning_points",
    "counterfactuals",
    "strategy_suggestions",
    "mvp_results",
)


def _iter_review_items(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    items: list[dict[str, Any]] = []
    for section in _REVIEW_SIGNAL_SECTIONS:
        for item in payload.get(section, []) or []:
            if isinstance(item, dict):
                items.append(item)
    return items


def _decision_is_fallback(decision: AgentDecision) -> bool:
    parsed = decision.parsed_action if isinstance(decision.parsed_action, dict) else {}
    metadata = parsed.get("metadata") if isinstance(parsed.get("metadata"), dict) else {}
    return (
        bool(metadata.get("fallback"))
        or bool(parsed.get("agent_fallback"))
        or str(metadata.get("source", "")) == "fallback"
    )


def _decision_is_llm(decision: AgentDecision) -> bool:
    parsed = decision.parsed_action if isinstance(decision.parsed_action, dict) else {}
    metadata = parsed.get("metadata") if isinstance(parsed.get("metadata"), dict) else {}
    source = str(metadata.get("source", "")).lower()
    if source == "llm" and not _decision_is_fallback(decision):
        return True
    if bool(metadata.get("fallback")) or source == "fallback":
        return False
    return bool(decision.prompt_tokens or decision.completion_tokens) and not _decision_is_fallback(decision)


def _knowledge_doc_has_embedding(doc: StrategyKnowledgeDocData) -> bool:
    return bool(doc.embedding) and any(abs(float(value)) > 0 for value in doc.embedding)


def _tournament_result_is_llm(result: dict[str, Any]) -> bool:
    if not isinstance(result, dict):
        return False
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    runner_mode = str(metadata.get("runner_mode", "")).lower()
    if runner_mode != "llm":
        return False
    total = int(metadata.get("total_decisions") or metadata.get("decision_count") or 0)
    llm_count = int(metadata.get("llm_decision_count") or 0)
    fallback_count = int(metadata.get("fallback_count") or metadata.get("fallback_decision_count") or 0)
    if total <= 0 or fallback_count != 0:
        return False
    return llm_count / max(total, 1) >= 0.95


def _tournament_is_llm(item: EvolutionTournament) -> bool:
    results = list(item.baseline_results or []) + list(item.candidate_results or [])
    return bool(results) and all(_tournament_result_is_llm(result) for result in results)


def _build_bc_acceptance_audit_from_db(db, *, limit_games: int = 200) -> dict[str, Any]:
    """Quantify each documented B/C stage from persisted artifacts.

    This intentionally reports red/low rates when no data exists. Missing data
    is not a pass; operators should run the LLM pipeline and watch these rates
    move instead of treating an empty table as success.
    """
    finished_games = (
        db.query(Game)
        .filter(Game.status == "finished")
        .order_by(Game.finished_at.desc().nullslast(), Game.created_at.desc())
        .limit(limit_games)
        .all()
    )
    game_ids = [game.id for game in finished_games]
    event_counts: dict[str, int] = {}
    snapshot_counts: dict[str, int] = {}
    decisions: list[AgentDecision] = []
    if game_ids:
        event_counts = {
            str(game_id): int(count)
            for game_id, count in (
                db.query(GameEvent.game_id, sa_func.count(GameEvent.id))
                .filter(GameEvent.game_id.in_(game_ids))
                .group_by(GameEvent.game_id)
                .all()
            )
        }
        snapshot_counts = {
            str(game_id): int(count)
            for game_id, count in (
                db.query(GameSnapshot.game_id, sa_func.count(GameSnapshot.id))
                .filter(GameSnapshot.game_id.in_(game_ids))
                .group_by(GameSnapshot.game_id)
                .all()
            )
        }
        decisions = db.query(AgentDecision).filter(AgentDecision.game_id.in_(game_ids)).all()

    reviews = (
        db.query(PublishedReview)
        .order_by(PublishedReview.published_at.desc().nullslast(), PublishedReview.created_at.desc())
        .limit(limit_games)
        .all()
    )
    review_payloads = [row.report_json or {} for row in reviews]
    review_items = [item for payload in review_payloads for item in _iter_review_items(payload)]
    evidence_items = [item for item in review_items if item.get("evidence_event_ids") or item.get("source_event_ids")]
    approved_reviews = [row for row in reviews if row.publish_allowed]

    knowledge_rows = db.query(StrategyKnowledgeDoc).all()
    knowledge_docs = [StrategyKnowledgeDocData(**_knowledge_row_to_dict(row)) for row in knowledge_rows]
    validator = KnowledgeDocValidator()
    sanitized_docs = [doc for doc in knowledge_docs if not validator.validate(doc)]
    store = StrategyKnowledgeStore(knowledge_docs)
    indexed_docs = store.all(include_deprecated=True)
    embedded_docs = [doc for doc in indexed_docs if _knowledge_doc_has_embedding(doc)]
    active_docs = store.all(include_deprecated=False)[: min(20, len(store.all(include_deprecated=False)))]
    retrieval_hits = 0
    for doc in active_docs:
        lessons = store.retrieve(
            StrategyRetrievalQuery(
                role=doc.role,
                phase=doc.phase,
                observation_summary=doc.situation_pattern,
                situation_tags=list(doc.tags[:3]),
                top_k=3,
            )
        )
        if any(item.doc_id == doc.doc_id for item in lessons):
            retrieval_hits += 1
    graph_edge_types = {key.rsplit(":", 1)[-1] for key in store.edges}

    patches = db.query(StrategyPatch).all()
    validated_patches = [
        patch
        for patch in patches
        if (isinstance(patch.validation_result, dict) and patch.validation_result.get("passed") is True)
        or patch.status in {"validated", "applied", "promoted", "rolled_back"}
    ]

    tournaments = db.query(EvolutionTournament).all()
    fixed_seed_tournaments = [
        item
        for item in tournaments
        if len(item.seeds or []) == 20
        and len(item.baseline_results or []) == 20
        and len(item.candidate_results or []) == 20
        and int((item.comparison or {}).get("total_games") or 0) == 20
    ]
    fallback_free_tournaments = [
        item for item in tournaments if int((item.comparison or {}).get("candidate_fallback_count") or 0) == 0
    ]
    llm_tournaments = [item for item in tournaments if _tournament_is_llm(item)]
    decided_tournaments = [
        item
        for item in tournaments
        if item.status in {"promoted", "rolled_back"}
        and isinstance(item.decision, dict)
        and "accepted" in item.decision
    ]
    separated_tournaments = [
        item
        for item in tournaments
        if abs(float((item.comparison or {}).get("target_role_avg_score_delta") or 0.0)) > 0.001
        or abs(
            float((item.comparison or {}).get("candidate_avg_score") or 0.0)
            - float((item.comparison or {}).get("baseline_avg_score") or 0.0)
        )
        > 0.001
    ]

    decision_total = len(decisions)
    fallback_count = sum(1 for decision in decisions if _decision_is_fallback(decision))
    llm_count = sum(1 for decision in decisions if _decision_is_llm(decision))
    valid_count = sum(1 for decision in decisions if decision.is_valid)
    finished_total = len(finished_games)
    review_total = len(reviews)
    item_total = len(review_items)
    docs_total = len(knowledge_docs)
    patch_total = len(patches)
    tournament_total = len(tournaments)

    metrics = [
        build_acceptance_step_metric(
            track="B",
            step_id="B1",
            name="Replay persisted with events and snapshots",
            numerator=sum(
                1 for game in finished_games if event_counts.get(game.id, 0) > 0 and snapshot_counts.get(game.id, 0) > 0
            ),
            denominator=finished_total,
            threshold=1.0,
            evidence="finished games with GameEvent + GameSnapshot rows",
        ),
        build_acceptance_step_metric(
            track="B",
            step_id="B2",
            name="Player scoreboard generated",
            numerator=sum(1 for payload in review_payloads if payload.get("scoreboard")),
            denominator=review_total,
            threshold=0.95,
            evidence="PublishedReview.report_json.scoreboard",
        ),
        build_acceptance_step_metric(
            track="B",
            step_id="B3",
            name="SpeechAct analysis produced",
            numerator=sum(1 for row in reviews if row.speech_acts),
            denominator=review_total,
            threshold=0.90,
            evidence="PublishedReview.speech_acts",
        ),
        build_acceptance_step_metric(
            track="B",
            step_id="B4",
            name="Suspicion matrix produced",
            numerator=sum(1 for row in reviews if row.suspicion_matrix),
            denominator=review_total,
            threshold=0.90,
            evidence="PublishedReview.suspicion_matrix",
        ),
        build_acceptance_step_metric(
            track="B",
            step_id="B5",
            name="BadCase or Highlight detected",
            numerator=sum(
                1 for payload in review_payloads if payload.get("bad_cases") or payload.get("turning_points")
            ),
            denominator=review_total,
            threshold=0.70,
            evidence="bad_cases / turning_points sections",
        ),
        build_acceptance_step_metric(
            track="B",
            step_id="B6",
            name="Evidence coverage on review conclusions",
            numerator=len(evidence_items),
            denominator=item_total,
            threshold=0.90,
            evidence="evidence_event_ids on BadCase/Highlight/Counterfactual/StrategySuggestion/MVP",
        ),
        build_acceptance_step_metric(
            track="B",
            step_id="B7",
            name="Counterfactual coverage",
            numerator=sum(1 for payload in review_payloads if payload.get("counterfactuals")),
            denominator=review_total,
            threshold=0.60,
            evidence="counterfactuals section",
        ),
        build_acceptance_step_metric(
            track="B",
            step_id="B8",
            name="ValidAgent publish gate pass rate",
            numerator=len(approved_reviews),
            denominator=review_total,
            threshold=0.85,
            evidence="PublishedReview.publish_allowed",
        ),
        build_acceptance_step_metric(
            track="B",
            step_id="B9",
            name="Runtime fallback-free decisions",
            numerator=max(decision_total - fallback_count, 0),
            denominator=decision_total,
            threshold=1.0,
            evidence="AgentDecision.parsed_action.metadata.fallback",
            details={"fallback_count": fallback_count},
        ),
        build_acceptance_step_metric(
            track="B",
            step_id="B10",
            name="Runtime valid decisions",
            numerator=valid_count,
            denominator=decision_total,
            threshold=1.0,
            evidence="AgentDecision.is_valid",
        ),
        build_acceptance_step_metric(
            track="B",
            step_id="B11",
            name="Runtime LLM decision source rate",
            numerator=llm_count,
            denominator=decision_total,
            threshold=0.95,
            evidence="AgentDecision.parsed_action.metadata.source == llm / token usage",
            details={"llm_count": llm_count, "non_llm_count": max(decision_total - llm_count, 0)},
        ),
        build_acceptance_step_metric(
            track="B",
            step_id="B12",
            name="Leaderboard data available",
            numerator=1 if review_total > 0 or db.query(LeaderboardEntry).count() > 0 else 0,
            denominator=1,
            threshold=1.0,
            evidence="PublishedReview / LeaderboardEntry rows",
        ),
        build_acceptance_step_metric(
            track="C",
            step_id="C1",
            name="Approved reports converted to knowledge",
            numerator=sum(1 for doc in knowledge_docs if doc.source_report_ids),
            denominator=docs_total,
            threshold=1.0,
            evidence="StrategyKnowledgeDoc.source_report_ids",
        ),
        build_acceptance_step_metric(
            track="C",
            step_id="C2",
            name="Knowledge docs sanitized",
            numerator=len(sanitized_docs),
            denominator=docs_total,
            threshold=1.0,
            evidence="KnowledgeDocValidator",
        ),
        build_acceptance_step_metric(
            track="C",
            step_id="C3",
            name="Vector index coverage",
            numerator=len(embedded_docs),
            denominator=docs_total,
            threshold=1.0,
            evidence="StrategyKnowledgeStore hybrid vector embeddings",
            details={"retrieval_mode": StrategyKnowledgeStore.retrieval_mode},
        ),
        build_acceptance_step_metric(
            track="C",
            step_id="C4",
            name="Role/phase/situation retrieval hit rate",
            numerator=retrieval_hits,
            denominator=len(active_docs),
            threshold=0.90,
            evidence="StrategyKnowledgeStore.retrieve() top-k contains the source doc",
        ),
        build_acceptance_step_metric(
            track="C",
            step_id="C5",
            name="GraphRAG-lite edge coverage",
            numerator=min(len(graph_edge_types), 5),
            denominator=5,
            threshold=0.80,
            evidence="in-memory StrategyKnowledgeStore.edges relation families",
            details={"edge_types": sorted(graph_edge_types)},
        ),
        build_acceptance_step_metric(
            track="C",
            step_id="C6",
            name="StrategyPatch validation pass rate",
            numerator=len(validated_patches),
            denominator=patch_total,
            threshold=0.85,
            evidence="StrategyPatch.validation_result / status",
        ),
        build_acceptance_step_metric(
            track="C",
            step_id="C7",
            name="Fixed 20-seed A/B completion",
            numerator=len(fixed_seed_tournaments),
            denominator=tournament_total,
            threshold=1.0,
            evidence="EvolutionTournament seeds/results/comparison.total_games",
        ),
        build_acceptance_step_metric(
            track="C",
            step_id="C8",
            name="A/B fallback-free candidates",
            numerator=len(fallback_free_tournaments),
            denominator=tournament_total,
            threshold=1.0,
            evidence="EvolutionTournament.comparison.candidate_fallback_count",
        ),
        build_acceptance_step_metric(
            track="C",
            step_id="C9",
            name="A/B LLM runner evidence",
            numerator=len(llm_tournaments),
            denominator=tournament_total,
            threshold=1.0,
            evidence="EvolutionTournament result metadata.runner_mode == llm and llm_decision_count/total_decisions >= 95%",
        ),
        build_acceptance_step_metric(
            track="C",
            step_id="C10",
            name="Promote/Rollback decision recorded",
            numerator=len(decided_tournaments),
            denominator=tournament_total,
            threshold=1.0,
            evidence="EvolutionTournament.status + decision.accepted",
        ),
        build_acceptance_step_metric(
            track="C",
            step_id="C11",
            name="Leaderboard separates candidate from baseline",
            numerator=len(separated_tournaments),
            denominator=tournament_total,
            threshold=0.75,
            evidence="score delta or target-role delta is non-zero",
        ),
    ]
    return build_bc_acceptance_audit(metrics).to_dict()


def get_runtime_metrics(game_id: str) -> dict | None:
    """Per-game runtime metrics derived from AgentDecision rows.

    Stable response shape (always present even if zero):
        game_id, status, winner, duration_s, decision_count, valid_decision_count,
        invalid_decision_count, validity_rate, llm_call_count,
        latency_ms{count,min,max,avg,p50,p95,sum},
        tokens{prompt_sum,completion_sum,total_sum},
        speech{count,char_len{...}},
        by_role{role -> bucket},
        by_player{player_id -> bucket}
    """
    init_db()
    db = SessionLocal()
    try:
        game = db.query(Game).filter(Game.id == game_id).first()
        if game is None:
            return None
        players = db.query(Player).filter(Player.game_id == game_id).all()
        decisions = db.query(AgentDecision).filter(AgentDecision.game_id == game_id).all()

        player_by_id = {p.id: p for p in players}
        global_bucket = _new_runtime_bucket()
        by_role: dict[str, dict[str, Any]] = {}
        by_player: dict[str, dict[str, Any]] = {}
        for d in decisions:
            _accumulate_bucket(global_bucket, d)
            player = player_by_id.get(d.player_id)
            role = player.role if player else "Unknown"
            role_bucket = by_role.setdefault(role, _new_runtime_bucket(role=role))
            _accumulate_bucket(role_bucket, d)
            player_bucket = by_player.setdefault(
                d.player_id,
                _new_runtime_bucket(
                    seat_no=player.seat_no if player else None,
                    name=player.name if player else None,
                    role=role,
                ),
            )
            _accumulate_bucket(player_bucket, d)

        for bucket in [global_bucket, *by_role.values(), *by_player.values()]:
            _finalize_bucket(bucket)

        duration_s: float | None = None
        if game.started_at and game.finished_at:
            duration_s = round((game.finished_at - game.started_at).total_seconds(), 3)

        payload = {
            "game_id": game_id,
            "status": game.status,
            "winner": game.winner,
            "duration_s": duration_s,
            "decision_count": global_bucket["decision_count"],
            "valid_decision_count": global_bucket["valid_count"],
            "invalid_decision_count": global_bucket["invalid_count"],
            "validity_rate": global_bucket["validity_rate"],
            "llm_call_count": global_bucket["llm_call_count"],
            "latency_ms": global_bucket["latency_ms"],
            "tokens": {
                "prompt_sum": global_bucket["prompt_tokens_sum"],
                "completion_sum": global_bucket["completion_tokens_sum"],
                "total_sum": global_bucket["prompt_tokens_sum"] + global_bucket["completion_tokens_sum"],
            },
            "speech": {
                "count": global_bucket["speech_char_len"]["count"],
                "char_len": global_bucket["speech_char_len"],
            },
            "by_role": by_role,
            "by_player": by_player,
        }
        return _clean(payload)
    finally:
        db.close()


def get_aggregate_metrics(limit_games: int = 200) -> dict[str, Any]:
    """Cross-game aggregate metrics for Track B/C visualization.

    Schema:
        games: {total, finished, winners{wolf,villager,unknown}, avg_duration_s, avg_day_count}
        runtime: {decision_count, llm_call_count, fallback_count, fallback_ratio,
                  retrieval_used_count, retrieval_used_rate,
                  latency_ms{...}, tokens{...}, speech_char_len{...}}
        win_rate_by_role: {role -> {games, wins, win_rate}}
        win_rate_by_agent_type: {agent_type -> {games, wins, win_rate}}
        track_b: {published_total, approved, needs_revision, rejected, avg_score}
        track_c: {strategy_docs_total, by_status, by_doc_type, patches_total, by_patch_status,
                  tournaments_total, accepted, rejected}
    """
    init_db()
    db = SessionLocal()
    try:
        games_query = (
            db.query(Game)
            .filter(Game.status == "finished")
            .order_by(Game.finished_at.desc().nullslast(), Game.created_at.desc())
            .limit(limit_games)
        )
        games = games_query.all()
        total_games = db.query(Game).count()
        finished_total = db.query(Game).filter(Game.status == "finished").count()

        winners = {"wolf": 0, "village": 0, "unknown": 0}
        duration_values: list[float] = []
        day_counts: list[int] = []
        for g in games:
            key = g.winner if g.winner in ("wolf", "village") else "unknown"
            winners[key] = winners.get(key, 0) + 1
            if g.started_at and g.finished_at:
                duration_values.append((g.finished_at - g.started_at).total_seconds())
            day_counts.append(int(g.current_day or 0))

        avg_duration = round(sum(duration_values) / len(duration_values), 3) if duration_values else 0.0
        avg_day = round(sum(day_counts) / len(day_counts), 3) if day_counts else 0.0

        game_ids = [g.id for g in games]
        winners_by_game = {g.id: g.winner for g in games}

        win_rate_role: dict[str, dict[str, Any]] = {}
        win_rate_agent: dict[str, dict[str, Any]] = {}
        if game_ids:
            players = db.query(Player).filter(Player.game_id.in_(game_ids)).all()
            for p in players:
                winner = winners_by_game.get(p.game_id)
                player_won = (winner == "wolf" and p.role in _WOLF_ROLES) or (
                    winner == "village" and p.role not in _WOLF_ROLES
                )
                role_bucket = win_rate_role.setdefault(p.role, {"games": 0, "wins": 0})
                role_bucket["games"] += 1
                role_bucket["wins"] += 1 if player_won else 0
                agent_bucket = win_rate_agent.setdefault(p.agent_type or "unknown", {"games": 0, "wins": 0})
                agent_bucket["games"] += 1
                agent_bucket["wins"] += 1 if player_won else 0
            for bucket in win_rate_role.values():
                bucket["win_rate"] = round(bucket["wins"] / bucket["games"], 4) if bucket["games"] else 0.0
            for bucket in win_rate_agent.values():
                bucket["win_rate"] = round(bucket["wins"] / bucket["games"], 4) if bucket["games"] else 0.0

        runtime_bucket = _new_runtime_bucket()
        fallback_count = 0
        retrieval_used_count = 0
        if game_ids:
            decisions = db.query(AgentDecision).filter(AgentDecision.game_id.in_(game_ids)).all()
            for d in decisions:
                _accumulate_bucket(runtime_bucket, d)
                meta = (d.parsed_action or {}).get("metadata") if isinstance(d.parsed_action, dict) else None
                if isinstance(meta, dict):
                    if meta.get("fallback"):
                        fallback_count += 1
                    if meta.get("retrieval_used") or (d.parsed_action or {}).get("retrieval_used"):
                        retrieval_used_count += 1
        _finalize_bucket(runtime_bucket)

        decision_total = runtime_bucket["decision_count"]
        fallback_ratio = round(fallback_count / decision_total, 4) if decision_total else 0.0
        retrieval_rate = round(retrieval_used_count / decision_total, 4) if decision_total else 0.0

        published_total = db.query(PublishedReview).count()
        approved = db.query(PublishedReview).filter(PublishedReview.publish_allowed.is_(True)).count()
        review_status_counts: dict[str, int] = {}
        for status_value, count in (
            db.query(PublishedReview.status, sa_func.count(PublishedReview.id)).group_by(PublishedReview.status).all()
        ):
            review_status_counts[status_value or "unknown"] = int(count)
        review_score_values = [float(s) for (s,) in db.query(PublishedReview.score).all() if s is not None]
        avg_review_score = round(sum(review_score_values) / len(review_score_values), 4) if review_score_values else 0.0

        doc_status_counts: dict[str, int] = {}
        doc_type_counts: dict[str, int] = {}
        for status_value, count in (
            db.query(StrategyKnowledgeDoc.status, sa_func.count(StrategyKnowledgeDoc.id))
            .group_by(StrategyKnowledgeDoc.status)
            .all()
        ):
            doc_status_counts[status_value or "unknown"] = int(count)
        for type_value, count in (
            db.query(StrategyKnowledgeDoc.doc_type, sa_func.count(StrategyKnowledgeDoc.id))
            .group_by(StrategyKnowledgeDoc.doc_type)
            .all()
        ):
            doc_type_counts[type_value or "unknown"] = int(count)
        docs_total = db.query(StrategyKnowledgeDoc).count()

        patch_status_counts: dict[str, int] = {}
        for status_value, count in (
            db.query(StrategyPatch.status, sa_func.count(StrategyPatch.id)).group_by(StrategyPatch.status).all()
        ):
            patch_status_counts[status_value or "unknown"] = int(count)
        patches_total = db.query(StrategyPatch).count()

        tournaments_total = db.query(EvolutionTournament).count()
        tournament_accepted = sum(
            1
            for t in db.query(EvolutionTournament).all()
            if isinstance(t.decision, dict) and t.decision.get("accepted") is True
        )
        tournament_rejected = tournaments_total - tournament_accepted
        acceptance_audit = _build_bc_acceptance_audit_from_db(db, limit_games=limit_games)

        payload = {
            "games": {
                "total": total_games,
                "finished_total": finished_total,
                "sampled": len(games),
                "winners": winners,
                "avg_duration_s": avg_duration,
                "avg_day_count": avg_day,
            },
            "runtime": {
                "decision_count": decision_total,
                "valid_decision_count": runtime_bucket["valid_count"],
                "invalid_decision_count": runtime_bucket["invalid_count"],
                "validity_rate": runtime_bucket["validity_rate"],
                "llm_call_count": runtime_bucket["llm_call_count"],
                "fallback_count": fallback_count,
                "fallback_ratio": fallback_ratio,
                "retrieval_used_count": retrieval_used_count,
                "retrieval_used_rate": retrieval_rate,
                "latency_ms": runtime_bucket["latency_ms"],
                "tokens": {
                    "prompt_sum": runtime_bucket["prompt_tokens_sum"],
                    "completion_sum": runtime_bucket["completion_tokens_sum"],
                    "total_sum": runtime_bucket["prompt_tokens_sum"] + runtime_bucket["completion_tokens_sum"],
                },
                "speech_char_len": runtime_bucket["speech_char_len"],
            },
            "win_rate_by_role": win_rate_role,
            "win_rate_by_agent_type": win_rate_agent,
            "track_b": {
                "published_total": published_total,
                "approved": approved,
                "by_status": review_status_counts,
                "avg_score": avg_review_score,
            },
            "track_c": {
                "strategy_docs_total": docs_total,
                "by_status": doc_status_counts,
                "by_doc_type": doc_type_counts,
                "patches_total": patches_total,
                "by_patch_status": patch_status_counts,
                "tournaments_total": tournaments_total,
                "tournaments_accepted": tournament_accepted,
                "tournaments_rejected": tournament_rejected,
            },
            "acceptance": acceptance_audit,
        }
        return _clean(payload)
    finally:
        db.close()


def _wins_for_player(role: str, alignment_or_winner_guess: str, winner: str | None) -> bool:
    """Decide whether a single player won given the game winner and their role.

    Track-C tournament rows store winner as 'wolf' / 'village' / None; we infer
    alignment from _WOLF_ROLES rather than the absent alignment column.
    """
    if winner == "wolf" and role in _WOLF_ROLES:
        return True
    if winner == "village" and role not in _WOLF_ROLES:
        return True
    return False


def get_role_model_leaderboard(
    *,
    limit_games: int = 500,
    llm_only: bool = True,
    since_iso: str | None = None,
    game_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Cross-matrix leaderboard: (agent_label, role) -> {games, wins, win_rate}.

    agent_label is the joint of (agent_type, model_name) so heuristic vs. LLM
    and individual model contributions stay separable. Designed so the answer
    survives multi-tenant DB contention: pass either `llm_only=True` (keeps only
    games where every seat ran an LLM agent) or an explicit `game_ids` set to
    pin the analysis to a specific batch — both are safer than time-based
    cutoffs alone.

    Returns:
      {
        "sample": {"games": N, "since_iso": ..., "llm_only": bool},
        "agents": [
          {
            "agent_label": "llm/deepseek-v4-pro[1m]",
            "agent_type": "llm",
            "model_name": "deepseek-v4-pro[1m]",
            "games": N, "wins": K, "win_rate": K/N,
            "by_role": {
                "Werewolf": {"games": n, "wins": k, "win_rate": ...},
                ...
            },
          }, ...
        ],
        "matrix": {
          "<agent_label>": {
              "<role>": {"games": n, "wins": k, "win_rate": ...},
              ...
          }, ...
        },
      }
    """
    init_db()
    db = SessionLocal()
    try:
        query = db.query(Game).filter(Game.status == "finished")
        if since_iso:
            query = query.filter(Game.finished_at >= since_iso)
        if game_ids:
            query = query.filter(Game.id.in_(game_ids))
        games = query.order_by(Game.finished_at.desc().nullslast(), Game.created_at.desc()).limit(limit_games).all()
        winner_by_game = {g.id: g.winner for g in games}

        if not games:
            return {
                "sample": {"games": 0, "since_iso": since_iso, "llm_only": llm_only},
                "agents": [],
                "matrix": {},
            }

        all_players = db.query(Player).filter(Player.game_id.in_([g.id for g in games])).all()
        # llm_only filter: drop any game that has at least one non-LLM seat.
        if llm_only:
            non_llm_game_ids: set[str] = set()
            for p in all_players:
                if (p.agent_type or "").lower() != "llm":
                    non_llm_game_ids.add(p.game_id)
            kept_games = [g for g in games if g.id not in non_llm_game_ids]
            kept_game_id_set = {g.id for g in kept_games}
            all_players = [p for p in all_players if p.game_id in kept_game_id_set]
            games = kept_games

        matrix: dict[str, dict[str, dict[str, int | float]]] = {}
        for p in all_players:
            model = p.model_name or ""
            agent_type = (p.agent_type or "unknown").lower()
            agent_label = f"{agent_type}/{model}" if model else agent_type
            role = p.role or "Unknown"
            winner = winner_by_game.get(p.game_id)
            won = _wins_for_player(role, "", winner)
            label_buckets = matrix.setdefault(agent_label, {})
            bucket = label_buckets.setdefault(role, {"games": 0, "wins": 0})
            bucket["games"] = int(bucket["games"]) + 1
            bucket["wins"] = int(bucket["wins"]) + (1 if won else 0)

        agents_summary: list[dict[str, Any]] = []
        for agent_label, role_buckets in matrix.items():
            total_games = sum(int(b["games"]) for b in role_buckets.values())
            total_wins = sum(int(b["wins"]) for b in role_buckets.values())
            for _role, bucket in role_buckets.items():
                games_n = int(bucket["games"])
                bucket["win_rate"] = round(int(bucket["wins"]) / games_n, 4) if games_n else 0.0
            parts = agent_label.split("/", 1)
            agent_type_only = parts[0]
            model_only = parts[1] if len(parts) > 1 else ""
            agents_summary.append(
                {
                    "agent_label": agent_label,
                    "agent_type": agent_type_only,
                    "model_name": model_only,
                    "games": total_games,
                    "wins": total_wins,
                    "win_rate": round(total_wins / total_games, 4) if total_games else 0.0,
                    "by_role": role_buckets,
                }
            )
        agents_summary.sort(key=lambda a: (-a["games"], -a["win_rate"]))

        return _clean(
            {
                "sample": {
                    "games": len(games),
                    "since_iso": since_iso,
                    "llm_only": llm_only,
                },
                "agents": agents_summary,
                "matrix": matrix,
            }
        )
    finally:
        db.close()


def get_strategy_attribution(
    *,
    limit_games: int = 500,
    llm_only: bool = True,
    since_iso: str | None = None,
    game_ids: list[str] | None = None,
    top_k: int = 20,
) -> dict[str, Any]:
    """Strategy attribution: which knowledge docs got retrieved during games,
    and what their hit/helpful/unhelpful counts look like from the
    knowledge_usage_feedback table joined with the same game subset used by
    the role/model leaderboard.

    Returns:
      {
        "sample": {"games": N},
        "docs_used_total": int,
        "by_doc": [
          {"doc_id": ..., "role": ..., "phase": ...,
           "usage_count": int, "helpful": int, "unhelpful": int,
           "helpful_ratio": float, "quality_score": float, "status": ...}
        ],
        "by_role_phase": {"<role>:<phase>": int},
      }
    """
    init_db()
    db = SessionLocal()
    try:
        query = db.query(Game).filter(Game.status == "finished")
        if since_iso:
            query = query.filter(Game.finished_at >= since_iso)
        if game_ids:
            query = query.filter(Game.id.in_(game_ids))
        games = query.order_by(Game.finished_at.desc().nullslast(), Game.created_at.desc()).limit(limit_games).all()
        if not games:
            return {
                "sample": {"games": 0},
                "docs_used_total": 0,
                "by_doc": [],
                "by_role_phase": {},
            }
        game_id_set = {g.id for g in games}

        if llm_only:
            all_players = db.query(Player).filter(Player.game_id.in_(list(game_id_set))).all()
            non_llm = {p.game_id for p in all_players if (p.agent_type or "").lower() != "llm"}
            game_id_set -= non_llm

        if not game_id_set:
            return {
                "sample": {"games": 0},
                "docs_used_total": 0,
                "by_doc": [],
                "by_role_phase": {},
            }

        feedback_rows = (
            db.query(KnowledgeUsageFeedback).filter(KnowledgeUsageFeedback.game_id.in_(list(game_id_set))).all()
        )

        # Player.role lookup for the by_role_phase histogram (player_role isn't
        # a column on KnowledgeUsageFeedback, so we join via player_id).
        player_role_map: dict[str, str] = {}
        if feedback_rows:
            player_ids = {row.player_id for row in feedback_rows if row.player_id}
            if player_ids:
                for pid, role in db.query(Player.id, Player.role).filter(Player.id.in_(list(player_ids))).all():
                    player_role_map[pid] = role or "unknown"

        usage_by_doc: dict[str, dict[str, Any]] = {}
        by_role_phase: dict[str, int] = {}
        for row in feedback_rows:
            entry = usage_by_doc.setdefault(
                row.knowledge_doc_id,
                {
                    "doc_id": row.knowledge_doc_id,
                    "usage_count": 0,
                    "helpful": 0,
                    "unhelpful": 0,
                },
            )
            entry["usage_count"] += 1
            if row.helpful is True:
                entry["helpful"] += 1
            elif row.helpful is False:
                entry["unhelpful"] += 1
            role_key = player_role_map.get(row.player_id, "unknown")
            phase_key = (row.extra_metadata or {}).get("phase") if isinstance(row.extra_metadata, dict) else "unknown"
            role_phase_key = f"{role_key}:{phase_key or 'unknown'}"
            by_role_phase[role_phase_key] = by_role_phase.get(role_phase_key, 0) + 1

        if usage_by_doc:
            doc_rows = (
                db.query(StrategyKnowledgeDoc).filter(StrategyKnowledgeDoc.id.in_(list(usage_by_doc.keys()))).all()
            )
            doc_meta = {d.id: d for d in doc_rows}
        else:
            doc_meta = {}

        by_doc: list[dict[str, Any]] = []
        for doc_id, entry in usage_by_doc.items():
            doc_row = doc_meta.get(doc_id)
            usage = int(entry["usage_count"])
            helpful = int(entry["helpful"])
            unhelpful = int(entry["unhelpful"])
            helpful_ratio = round(helpful / usage, 4) if usage else 0.0
            by_doc.append(
                {
                    "doc_id": doc_id,
                    "role": doc_row.role if doc_row else None,
                    "phase": doc_row.phase if doc_row else None,
                    "doc_type": doc_row.doc_type if doc_row else None,
                    "status": doc_row.status if doc_row else None,
                    "quality_score": float(doc_row.quality_score or 0.0) if doc_row else 0.0,
                    "usage_count": usage,
                    "helpful": helpful,
                    "unhelpful": unhelpful,
                    "helpful_ratio": helpful_ratio,
                }
            )
        by_doc.sort(key=lambda r: (-r["usage_count"], -r["helpful_ratio"]))
        by_doc = by_doc[:top_k]

        return _clean(
            {
                "sample": {"games": len(game_id_set)},
                "docs_used_total": len(usage_by_doc),
                "by_doc": by_doc,
                "by_role_phase": by_role_phase,
            }
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# DecisionTrace coverage tracking (v2 §G2 / §G10)
# ---------------------------------------------------------------------------

_DECISION_TRACE_FIELDS = (
    "candidate_actions",
    "visible_facts",
    "confidence",
    "prompt_hash",
    "cost_usd",
    "model_name",
)


def get_decision_trace_coverage(game_ids: list[str] | None = None) -> dict[str, Any]:
    """Compute DecisionTrace field coverage across finished games.

    Returns fraction of decisions that have each field populated,
    plus an overall scorecard suitable for the GameHealthReport.
    """
    init_db()
    db = SessionLocal()
    try:
        query = db.query(AgentDecision)
        if game_ids:
            query = query.filter(AgentDecision.game_id.in_(game_ids))
        decisions = query.all()
        total = len(decisions)
        if total == 0:
            return {"total": 0, "coverage_rate": 0.0, "fields": {}}

        field_counts: dict[str, int] = {}
        for field in _DECISION_TRACE_FIELDS:
            count = 0
            for d in decisions:
                val = getattr(d, field, None)
                if val is not None and val != [] and val != "":
                    count += 1
            field_counts[field] = count

        full_count = sum(
            1
            for d in decisions
            if all(
                getattr(d, f, None) is not None and getattr(d, f, None) != [] and getattr(d, f, None) != ""
                for f in _DECISION_TRACE_FIELDS
            )
        )

        return {
            "total": total,
            "full_trace_count": full_count,
            "coverage_rate": round(full_count / total, 4),
            "fields": {
                field: {
                    "count": cnt,
                    "rate": round(cnt / total, 4),
                }
                for field, cnt in field_counts.items()
            },
        }
    finally:
        db.close()
