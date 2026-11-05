"""Prometheus text exposition built from existing durable state.

Only aggregate counts by fixed status/type labels are exported: no IDs,
player data, prompts or secrets.
"""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST
from prometheus_client import CollectorRegistry
from prometheus_client import Gauge
from prometheus_client import generate_latest
from sqlalchemy import func

from backend.core.observability import metrics_snapshot
from backend.db.database import SessionLocal
from backend.db.models import Game
from backend.db.models import MatchJob
from backend.db.models import OutboxEvent
from backend.db.models import TrackCPostGameJob
from backend.ops.worker_health import worker_health

_GAME_STATUSES = ("waiting", "running", "finished")


def _metric_name(counter: str) -> str:
    return "aiwerewolf_process_" + "".join(c if c.isalnum() else "_" for c in counter) + "_total"


def render_metrics() -> tuple[bytes, str]:
    registry = CollectorRegistry()
    workers_alive = Gauge("aiwerewolf_workers_alive", "Workers with a fresh heartbeat", ["worker_type"], registry=registry)
    workers_stale = Gauge("aiwerewolf_workers_stale", "Workers with a stale heartbeat", ["worker_type"], registry=registry)
    match_jobs = Gauge("aiwerewolf_match_jobs", "Match jobs by status", ["status"], registry=registry)
    analysis_jobs = Gauge("aiwerewolf_analysis_jobs", "Post-game analysis jobs by status", ["status"], registry=registry)
    outbox = Gauge("aiwerewolf_outbox_events", "Outbox events by status", ["status"], registry=registry)
    games = Gauge("aiwerewolf_games", "Games by status (started = running + finished)", ["status"], registry=registry)
    analysis_failed = Gauge(
        "aiwerewolf_analysis_failed_jobs", "Analysis jobs in failed or dead_letter state", registry=registry
    )

    health = worker_health()
    alive: dict[str, int] = {}
    stale: dict[str, int] = {}
    for worker in health["workers"]:
        bucket = stale if worker["status"] in {"stale", "stopped"} else alive
        bucket[worker["worker_type"]] = bucket.get(worker["worker_type"], 0) + 1
    for worker_type in set(alive) | set(stale):
        workers_alive.labels(worker_type=worker_type).set(alive.get(worker_type, 0))
        workers_stale.labels(worker_type=worker_type).set(stale.get(worker_type, 0))

    with SessionLocal() as db:
        for status, n in db.query(MatchJob.status, func.count()).group_by(MatchJob.status).all():
            match_jobs.labels(status=str(status)).set(n)
        analysis_counts = dict(db.query(TrackCPostGameJob.status, func.count()).group_by(TrackCPostGameJob.status).all())
        for status, n in db.query(OutboxEvent.status, func.count()).group_by(OutboxEvent.status).all():
            outbox.labels(status=str(status)).set(n)
        game_counts = dict(db.query(Game.status, func.count()).group_by(Game.status).all())
    for status, n in analysis_counts.items():
        analysis_jobs.labels(status=str(status)).set(n)
    analysis_failed.set(sum(n for s, n in analysis_counts.items() if s in {"failed", "dead_letter"}))
    for status in _GAME_STATUSES:
        games.labels(status=status).set(game_counts.get(status, 0))

    # In-process counters (API process only; workers keep their own).
    for name, value in metrics_snapshot()["counters"].items():
        Gauge(_metric_name(name), f"Process counter {name}", registry=registry).set(value)

    return generate_latest(registry), CONTENT_TYPE_LATEST
