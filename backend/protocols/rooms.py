from __future__ import annotations

from time import time

from backend.engine.game import WerewolfGame
from backend.engine.models import GameState
from backend.protocols.schemas import RoomCreateRequest, RoomRecord


class RoomManager:
    def __init__(self) -> None:
        self.rooms: dict[str, RoomRecord] = {}
        self.games: dict[str, GameState] = {}
        self.active_games: dict[str, WerewolfGame] = {}
        # Live snapshot streams keyed by room id. We append every snapshot the
        # engine emits so that a reconnecting WebSocket can catch up on the
        # entire game so far before subscribing to fresh frames. Cleared in
        # record_game() once the game finishes.
        self.snapshot_buffers: dict[str, list[dict]] = {}

    def create_room(self, request: RoomCreateRequest) -> RoomRecord:
        room = RoomRecord.create(
            request.name,
            request.seed,
            request.player_count,
            request.agent_type,
            request.human_seat,
            request.rule_pack_id,
        )
        self.rooms[room.id] = room
        return room

    def get_room(self, room_id: str) -> RoomRecord:
        room = self.rooms.get(room_id)
        if room is None:
            raise KeyError(room_id)
        return room

    def list_rooms(self) -> list[dict]:
        return [room.to_dict() for room in self.rooms.values()]

    def list_room_games(self, room_id: str) -> list[dict]:
        room = self.get_room(room_id)
        games: list[dict] = []
        for game_id in room.game_history:
            state = self.get_game(game_id)
            games.append(
                {
                    "id": state.id,
                    "day": state.day,
                    "phase": state.phase.value,
                    "winner": state.winner.value if state.winner else None,
                }
            )
        return games

    def get_latest_snapshot(self, room_id: str) -> dict | None:
        room = self.get_room(room_id)
        return room.latest_snapshot

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
        # Idempotent: if a reconnecting WebSocket also calls record_game with
        # the same finished state, we don't want game_history to grow twice.
        if state.id not in room.game_history:
            room.game_history.append(state.id)
        room.latest_snapshot = snapshot
        room.status = "completed"
        room.updated_at = time()
        self.active_games.pop(room_id, None)
        # Game over — drop the live stream buffer so the next game starts fresh.
        self.snapshot_buffers.pop(room_id, None)
        return room

    def append_snapshot(self, room_id: str, snapshot: dict) -> None:
        """Append a live snapshot to the room's reconnect buffer."""
        self.snapshot_buffers.setdefault(room_id, []).append(snapshot)

    def get_snapshot_buffer(self, room_id: str) -> list[dict]:
        """Return the live snapshot buffer (empty list if none)."""
        return list(self.snapshot_buffers.get(room_id, []))

    def reset_snapshot_buffer(self, room_id: str) -> None:
        self.snapshot_buffers[room_id] = []

    def set_active_game(self, room_id: str, game: WerewolfGame) -> None:
        self.active_games[room_id] = game
        room = self.get_room(room_id)
        room.status = "running"
        room.current_game_id = game.state.id
        room.updated_at = time()

    def get_active_game(self, room_id: str) -> WerewolfGame | None:
        self.get_room(room_id)
        return self.active_games.get(room_id)

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
