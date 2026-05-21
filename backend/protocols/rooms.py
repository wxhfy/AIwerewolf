from __future__ import annotations

from time import time

from backend.engine.models import GameState
from backend.protocols.schemas import RoomCreateRequest, RoomRecord


class RoomManager:
    def __init__(self) -> None:
        self.rooms: dict[str, RoomRecord] = {}
        self.games: dict[str, GameState] = {}

    def create_room(self, request: RoomCreateRequest) -> RoomRecord:
        room = RoomRecord.create(request.name, request.seed, request.player_count, request.agent_type)
        self.rooms[room.id] = room
        return room

    def get_room(self, room_id: str) -> RoomRecord:
        room = self.rooms.get(room_id)
        if room is None:
            raise KeyError(room_id)
        return room

    def list_rooms(self) -> list[dict]:
        return [room.to_dict() for room in self.rooms.values()]

    def set_room_status(self, room_id: str, status: str) -> RoomRecord:
        room = self.get_room(room_id)
        room.status = status
        room.updated_at = time()
        return room

    def record_snapshot(self, room_id: str, snapshot: dict) -> None:
        room = self.get_room(room_id)
        room.latest_snapshot = snapshot
        room.updated_at = time()

    def record_game(self, room_id: str, state: GameState, snapshot: dict | None) -> RoomRecord:
        room = self.get_room(room_id)
        self.games[state.id] = state
        room.current_game_id = state.id
        room.game_history.append(state.id)
        room.latest_snapshot = snapshot
        room.status = "completed"
        room.updated_at = time()
        return room

    def get_game(self, game_id: str) -> GameState:
        state = self.games.get(game_id)
        if state is None:
            raise KeyError(game_id)
        return state

    def list_games(self) -> list[dict]:
        return [
            {
                "id": state.id,
                "day": state.day,
                "phase": state.phase.value,
                "winner": state.winner.value if state.winner else None,
            }
            for state in self.games.values()
        ]
