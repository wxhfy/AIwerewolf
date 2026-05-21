"""Persist game state to database during gameplay."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from backend.db.database import SessionLocal
from backend.db.models import AgentDecision, Evaluation, Game, GameEvent, GameSnapshot, Player, Vote
from backend.engine.models import GameState


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
        for event in state.events:
            payload = _clean(event.payload) if isinstance(event.payload, dict) else {}
            phase = event.phase.value if hasattr(event.phase, "value") else str(event.phase)
            event_type = event.type.value if hasattr(event.type, "value") else str(event.type)
            db.add(GameEvent(
                id=event.id,
                game_id=state.id,
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

        db.commit()
    finally:
        db.close()


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
            {"day": e.day, "phase": e.phase, "speaker": (e.content or {}).get("actor_name", ""),
             "text": _clean(str((e.content or {}).get("speech", "")))[:400]}
            for e in game.events
            if e.event_type == "CHAT_MESSAGE"
        ]
        votes = [
            {"day": e.day, "voter": (e.content or {}).get("voter_name", ""),
             "target": (e.content or {}).get("target_name", "")}
            for e in game.events
            if e.event_type == "VOTE_CAST"
        ]
        deaths = [
            {"day": e.day, "player": (e.content or {}).get("player_name", ""),
             "reason": (e.content or {}).get("reason", "")}
            for e in game.events
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
