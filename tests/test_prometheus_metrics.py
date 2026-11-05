from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app import app
from backend.db.database import init_db
from backend.ops.worker_health import record_heartbeat


def test_metrics_endpoint_exposes_prometheus_text():
    init_db()
    record_heartbeat("prom-test-worker", "match_worker")
    with TestClient(app) as client:
        response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    for name in (
        "aiwerewolf_workers_alive",
        "aiwerewolf_workers_stale",
        "aiwerewolf_match_jobs",
        "aiwerewolf_analysis_jobs",
        "aiwerewolf_analysis_failed_jobs",
        "aiwerewolf_outbox_events",
        "aiwerewolf_games",
    ):
        assert f"# TYPE {name} gauge" in body
    assert 'aiwerewolf_workers_alive{worker_type="match_worker"}' in body
    assert "prom-test-worker" not in body  # no IDs as labels
