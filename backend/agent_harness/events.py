from __future__ import annotations

import json
import time
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any
from typing import Protocol


@dataclass(frozen=True)
class HarnessEvent:
    seq: int
    event_type: str
    step: int
    timestamp_ms: int
    payload: Mapping[str, Any]

    def to_record(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "event_type": self.event_type,
            "step": self.step,
            "timestamp_ms": self.timestamp_ms,
            "payload": _thaw_json(self.payload),
        }


class EventWriter(Protocol):
    """Durability seam implemented later by the Agent Service event store."""

    def write(self, event: HarnessEvent) -> None: ...


class HarnessSession:
    """Append-only source of truth for one decision run."""

    def __init__(self, writer: EventWriter | None = None) -> None:
        self._events: list[HarnessEvent] = []
        self._writer = writer

    @property
    def events(self) -> tuple[HarnessEvent, ...]:
        return tuple(self._events)

    def append(self, event_type: str, *, step: int, payload: dict[str, Any] | None = None) -> HarnessEvent:
        copied = deepcopy(payload or {})
        json.dumps(copied)
        event = HarnessEvent(
            seq=len(self._events),
            event_type=event_type,
            step=step,
            timestamp_ms=int(time.time() * 1000),
            payload=_freeze_json(copied),
        )
        if self._writer is not None:
            self._writer.write(event)
        self._events.append(event)
        return event


def _freeze_json(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value
