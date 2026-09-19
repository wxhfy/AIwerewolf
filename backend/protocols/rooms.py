from __future__ import annotations

from time import time

from backend.db.database import SessionLocal
from backend.db.database import init_db
from backend.db.models import Game
from backend.db.models import GameRoom
from backend.engine.game import WerewolfGame
from backend.engine.models import GameState
from backend.protocols.schemas import RoomCreateRequest
from backend.protocols.schemas import RoomRecord


class RoomManager:
    """PostgreSQL-backed room catalog plus process-local prepared game cache."""

    def __init__(self) -> None:
        self.games: dict[str, GameState] = {}
        self.active_games: dict[str, WerewolfGame] = {}

    def create_room(self, request: RoomCreateRequest) -> RoomRecord:
        init_db()
        room = RoomRecord.create(
            request.name,
            request.seed,
            request.player_count,
            request.agent_type,
            request.human_seat,
            request.rule_pack_id,
            request.llm_config,
        )
        with SessionLocal.begin() as db:
            db.add(
                GameRoom(
                    id=room.id,
                    name=room.name,
                    seed=room.seed,
                    player_count=room.player_count,
                    agent_type=room.agent_type,
                    human_seat=room.human_seat,
                    rule_pack_id=room.rule_pack_id,
                    llm_config=room.llm_config or {},
                    status=room.status,
                    current_game_id=room.current_game_id,
                    game_history=room.game_history,
                    latest_snapshot=room.latest_snapshot,
                    created_at=room.created_at,
                    updated_at=room.updated_at,
                )
            )
        return room

    def get_room(self, room_id: str) -> RoomRecord:
        init_db()
        with SessionLocal() as db:
            row = db.query(GameRoom).filter(GameRoom.id == room_id).first()
            if row is None:
                raise KeyError(room_id)
            return self._to_record(row)

    def list_rooms(self) -> list[dict]:
        init_db()
        with SessionLocal() as db:
            rows = db.query(GameRoom).order_by(GameRoom.updated_at.desc()).all()
            return [self._to_record(row).to_dict() for row in rows]

    def list_room_games(self, room_id: str) -> list[dict]:
        room = self.get_room(room_id)
        if not room.game_history:
            return []
        with SessionLocal() as db:
            rows = db.query(Game).filter(Game.id.in_(room.game_history)).all()
            by_id = {row.id: row for row in rows}
            return [
                {
                    "id": game_id,
                    "day": by_id[game_id].current_day,
                    "phase": by_id[game_id].current_phase,
                    "winner": by_id[game_id].winner,
                }
                for game_id in room.game_history
                if game_id in by_id
            ]

    def get_latest_snapshot(self, room_id: str) -> dict | None:
        return self.get_room(room_id).latest_snapshot

    def set_room_status(self, room_id: str, status: str) -> RoomRecord:
        with SessionLocal.begin() as db:
            row = self._get_row(db, room_id)
            row.status = status
            row.updated_at = time()
            db.flush()
            return self._to_record(row)

    def record_snapshot(self, room_id: str, snapshot: dict) -> None:
        with SessionLocal.begin() as db:
            row = self._get_row(db, room_id)
            row.latest_snapshot = snapshot
            row.updated_at = time()

    def record_game(self, room_id: str, state: GameState, snapshot: dict | None) -> RoomRecord:
        self.games[state.id] = state
        with SessionLocal.begin() as db:
            row = self._get_row(db, room_id)
            history = list(row.game_history or [])
            if state.id not in history:
                history.append(state.id)
            row.game_history = history
            row.current_game_id = state.id
            row.latest_snapshot = snapshot
            row.status = "completed"
            row.updated_at = time()
            db.flush()
            self.active_games.pop(room_id, None)
            return self._to_record(row)

    def set_active_game(self, room_id: str, game: WerewolfGame) -> None:
        self.active_games[room_id] = game
        with SessionLocal.begin() as db:
            row = self._get_row(db, room_id)
            row.status = "prepared"
            row.current_game_id = game.state.id
            row.updated_at = time()

    def get_active_game(self, room_id: str) -> WerewolfGame | None:
        self.get_room(room_id)
        return self.active_games.get(room_id)

    def get_game(self, game_id: str) -> GameState:
        state = self.games.get(game_id)
        if state is None:
            raise KeyError(game_id)
        return state

    def list_games(self) -> list[dict]:
        with SessionLocal() as db:
            rows = db.query(Game).order_by(Game.created_at.desc()).all()
            return [
                {
                    "id": row.id,
                    "day": row.current_day,
                    "phase": row.current_phase,
                    "winner": row.winner,
                }
                for row in rows
            ]

    @staticmethod
    def _get_row(db, room_id: str) -> GameRoom:
        row = db.query(GameRoom).filter(GameRoom.id == room_id).first()
        if row is None:
            raise KeyError(room_id)
        return row

    @staticmethod
    def _to_record(row: GameRoom) -> RoomRecord:
        return RoomRecord(
            id=row.id,
            name=row.name,
            seed=row.seed,
            player_count=row.player_count,
            agent_type=row.agent_type,
            human_seat=row.human_seat,
            rule_pack_id=row.rule_pack_id,
            llm_config=dict(row.llm_config or {}),
            status=row.status,
            created_at=float(row.created_at or 0),
            updated_at=float(row.updated_at or 0),
            current_game_id=row.current_game_id,
            game_history=list(row.game_history or []),
            latest_snapshot=dict(row.latest_snapshot) if row.latest_snapshot else None,
        )
