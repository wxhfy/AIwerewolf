"""Persist game state to database during gameplay."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from backend.db.database import SessionLocal
from backend.db.database import init_db
from backend.db.models import (
    AgentDecision,
    AgentVersion,
    Evaluation,
    EvolutionRound,
    Game,
    GameEvent,
    GameSnapshot,
    LeaderboardEntry,
    Player,
    PublishedReview,
    ReviewReport,
    Vote,
)
from backend.engine.models import GameState
from backend.eval.review import LeaderboardAggregator
from backend.eval.track_b import generate_published_review_document, reconstruct_review_report


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
            db.add(Player(
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
            ))
        db.commit()
        return game
    finally:
        db.close()


def save_event(game_id: str, event: GameEvent) -> None:
    db = SessionLocal()
    try:
        db.add(GameEvent(
            id=event.id,
            game_id=game_id,
            day=event.day,
            phase=event.phase.value if hasattr(event.phase, 'value') else str(event.phase),
            event_type=event.type.value if hasattr(event.type, 'value') else str(event.type),
            actor_id=event.payload.get("actor_id"),
            target_id=event.payload.get("target_id"),
            visibility=event.visibility,
            content=event.payload,
        ))
        db.commit()
    finally:
        db.close()


def save_decision(game_id: str, player_id: str, day: int, phase: str,
                  observation: dict, action: dict, raw: str,
                  latency_ms: int | None = None) -> None:
    db = SessionLocal()
    try:
        db.add(AgentDecision(
            game_id=game_id,
            player_id=player_id,
            day=day,
            phase=phase,
            observation=observation,
            legal_actions=[],
            parsed_action=action,
            raw_output=raw,
            latency_ms=latency_ms,
        ))
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
            db.add(GameEvent(
                id=event.id,
                game_id=state.id,
                seq=seq,
                ts=float(event.ts or 0.0),
                day=event.day,
                phase=phase,
                event_type=event_type,
                actor_id=payload.get("actor_id") or payload.get("voter_id") or payload.get("hunter_id"),
                target_id=payload.get("target_id") or (payload.get("target") or {}).get("id") if isinstance(payload.get("target"), dict) else payload.get("target_id"),
                visibility=event.visibility,
                content=payload,
            ))

        # Bulk-save decisions
        db.query(AgentDecision).filter(AgentDecision.game_id == state.id).delete()
        for record in state.decision_records:
            db.add(AgentDecision(
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
            ))

        # Bulk-save votes from history
        db.query(Vote).filter(Vote.game_id == state.id).delete()
        for day, voted in state.vote_history.items():
            for voter_id, target_id in voted.items():
                db.add(Vote(
                    game_id=state.id,
                    day=int(day),
                    voter_id=voter_id,
                    target_id=target_id,
                ))

        # Final snapshot for replay
        db.query(GameSnapshot).filter(GameSnapshot.game_id == state.id).delete()
        try:
            truth = _clean(state.moderator_dict())
            public = _clean(state.public_dict())
            db.add(GameSnapshot(
                game_id=state.id,
                day=state.day,
                phase=state.phase.value,
                truth_state=truth,
                public_state=public,
            ))
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
        metrics.append({
            "game_id": state.id,
            "player_id": p.id,
            "metric_name": "win",
            "metric_value": 1.0 if won else 0.0,
            "comment": f"role={p.role.value} alignment={p.alignment.value}",
        })
        metrics.append({
            "game_id": state.id,
            "player_id": p.id,
            "metric_name": "survived",
            "metric_value": 1.0 if survived else 0.0,
            "comment": p.death_reason or "",
        })
        metrics.append({
            "game_id": state.id,
            "player_id": p.id,
            "metric_name": "speech_count",
            "metric_value": float(chat_by_actor.get(p.id, 0)),
            "comment": "",
        })
    return metrics


def save_evaluation(game_id: str, player_id: str, metric_name: str, value: float, comment: str = "") -> None:
    db = SessionLocal()
    try:
        db.add(Evaluation(game_id=game_id, player_id=player_id, metric_name=metric_name, metric_value=value, comment=comment))
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
                {"id": p.id, "seat_no": p.seat_no, "name": p.name, "role": p.role,
                 "is_alive": p.is_alive, "agent_type": p.agent_type}
                for p in game.players
            ],
            "events": [
                {"id": e.id, "day": e.day, "phase": e.phase, "event_type": e.event_type,
                 "actor_id": e.actor_id, "visibility": e.visibility, "content": e.content}
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
                {"name": p.name, "role": p.role, "is_alive": p.is_alive, "seat_no": p.seat_no}
                for p in g.players
            ]
            results.append({
                "id": g.id,
                "status": g.status,
                "winner": g.winner,
                "current_day": g.current_day,
                "seed": g.seed,
                "created_at": g.created_at.isoformat() if g.created_at else None,
                "player_count": len(players),
                "players": players,
            })
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
        return _clean({
            "id": game.id,
            "status": game.status,
            "winner": game.winner,
            "day": game.current_day,
            "seed": game.seed,
            "players": [{"name": p.name, "role": p.role, "alive": p.is_alive, "seat": p.seat_no,
                         "is_ai": p.is_ai, "death_day": p.death_day, "death_reason": p.death_reason}
                        for p in sorted(game.players, key=lambda x: x.seat_no)],
            "speeches": speeches,
            "votes": votes,
            "deaths": deaths,
            "decision_count": decision_count,
            "event_count": len(game.events),
            "created_at": game.created_at.isoformat() if game.created_at else None,
            "finished_at": game.finished_at.isoformat() if game.finished_at else None,
        })
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
            db.query(GameSnapshot)
            .filter(GameSnapshot.game_id == game_id)
            .order_by(GameSnapshot.day.desc())
            .first()
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
        return _clean({
            "id": game.id,
            "winner": game.winner,
            "day": game.current_day,
            "phase": game.current_phase,
            "players": [
                {"id": p.id, "name": p.name, "seat": p.seat_no, "role": p.role,
                 "is_alive": p.is_alive, "is_ai": p.is_ai, "agent_type": p.agent_type,
                 "death_day": p.death_day, "death_reason": p.death_reason}
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
        })
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
            return _clean({
                "game_id": game_id,
                "winner": game.winner,
                "scoreboard": payload.get("scoreboard", []),
                "player_scores": payload.get("metadata", {}).get("player_scores", []),
                "speech_acts": review.speech_acts or [],
                "suspicion_matrix": review.suspicion_matrix or [],
                "validation": review.validation_result or {},
            })
        rows = db.query(Evaluation).filter(Evaluation.game_id == game_id).all()
        grouped: dict[str, list[dict]] = {}
        for row in rows:
            grouped.setdefault(row.player_id or "_global", []).append({
                "metric": row.metric_name,
                "value": row.metric_value,
                "comment": row.comment,
            })
        return {"game_id": game_id, "winner": game.winner, "metrics": grouped}
    finally:
        db.close()


def get_leaderboard(*, role: str | None = None, limit: int = 20) -> list[dict]:
    db = SessionLocal()
    try:
        init_db()
        approved = (
            db.query(PublishedReview)
            .filter(PublishedReview.publish_allowed.is_(True))
            .order_by(PublishedReview.published_at.desc(), PublishedReview.created_at.desc())
            .all()
        )
        if approved:
            reports = [reconstruct_review_report(row.report_json or {}) for row in approved if row.report_json]
            aggregated = LeaderboardAggregator().aggregate_all(reports)
            payload = {key: value.to_dict() for key, value in aggregated.items()}
            if role:
                payload["role"]["entries"] = [
                    entry for entry in payload["role"]["entries"]
                    if entry["display_name"] == role or entry["key"] == role
                ][:limit]
            else:
                for key in payload:
                    payload[key]["entries"] = payload[key]["entries"][:limit]
            return _clean(payload)

        query = db.query(LeaderboardEntry)
        if role:
            query = query.filter(LeaderboardEntry.role == role)
        rows = (
            query.order_by(LeaderboardEntry.win_rate.desc(), LeaderboardEntry.games_played.desc())
            .limit(limit)
            .all()
        )
        return _clean({
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
        })
    finally:
        db.close()


def get_review_reports(game_id: str) -> dict | None:
    db = SessionLocal()
    try:
        init_db()
        published = db.query(PublishedReview).filter(PublishedReview.game_id == game_id).first()
        if published is not None:
            return _clean({
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
            })
        rows = (
            db.query(ReviewReport)
            .filter(ReviewReport.game_id == game_id)
            .order_by(ReviewReport.day, ReviewReport.created_at)
            .all()
        )
        return {
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
            ]
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
        rows = (
            db.query(EvolutionRound)
            .order_by(EvolutionRound.round_no.desc())
            .limit(limit)
            .all()
        )
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
