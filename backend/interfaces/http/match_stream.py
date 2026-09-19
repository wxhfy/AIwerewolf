from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter
from fastapi import Header
from fastapi import HTTPException
from fastapi import Query
from fastapi import Request
from fastapi.responses import StreamingResponse

from backend.infrastructure.messaging.match_notifications import match_notifications
from backend.infrastructure.persistence.match_feed import MatchFeedRepository

router = APIRouter(prefix="/api/matches", tags=["match-stream"])
repository = MatchFeedRepository()


@router.get("/{match_id}/events")
def list_match_events(
    match_id: str,
    after_seq: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict:
    status = repository.match_status(match_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Match not found")
    events = repository.list_events(match_id, after_seq=after_seq, limit=limit)
    return {
        "match_id": match_id,
        "after_seq": after_seq,
        "last_seq": events[-1]["seq"] if events else after_seq,
        "events": events,
    }


@router.get("/{match_id}/stream")
async def stream_match(
    request: Request,
    match_id: str,
    after_seq: int = Query(default=0, ge=0),
    moderator: bool = Query(default=False),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    if repository.match_status(match_id) is None:
        raise HTTPException(status_code=404, detail="Match not found")

    try:
        header_seq = int(last_event_id or 0)
    except ValueError:
        header_seq = 0
    initial_seq = max(after_seq, header_seq)

    async def generate():
        cursor = initial_seq
        last_heartbeat = time.monotonic()
        subscription = await match_notifications.subscribe(match_id)
        try:
            while True:
                if await request.is_disconnected():
                    return
                snapshots = await asyncio.to_thread(
                    repository.list_snapshots,
                    match_id,
                    after_seq=cursor,
                    moderator=moderator,
                )
                for snapshot in snapshots:
                    seq = int(snapshot.get("seq") or 0)
                    if seq <= cursor:
                        continue
                    cursor = seq
                    payload = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
                    yield f"id: {seq}\nevent: snapshot\ndata: {payload}\n\n"
                    last_heartbeat = time.monotonic()

                status = await asyncio.to_thread(repository.match_status, match_id)
                if status == "finished" and not snapshots:
                    yield f'event: complete\ndata: {{"match_id":"{match_id}","seq":{cursor}}}\n\n'
                    return

                if subscription is not None:
                    await subscription.wait(timeout=15)
                else:
                    await asyncio.sleep(1)

                now = time.monotonic()
                if now - last_heartbeat >= 15:
                    yield f": heartbeat {cursor}\n\n"
                    last_heartbeat = now
        finally:
            if subscription is not None:
                await subscription.close()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
