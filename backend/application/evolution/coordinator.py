"""Durable, fenced Track C DAG built on the existing Track B/C contracts."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from concurrent.futures import FIRST_COMPLETED
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import wait
from dataclasses import asdict
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from backend.application.evolution.tournament import TournamentTask
from backend.application.evolution.tournament import TournamentWorker
from backend.application.evolution.tournament import card_with_patch
from backend.application.evolution.tournament import metric_from_artifact
from backend.core.observability import count
from backend.core.observability import log_event
from backend.db.database import SessionLocal
from backend.db.database import init_db
from backend.db.evolution_jobs import EvolutionArtifact
from backend.db.evolution_jobs import EvolutionRoleHead
from backend.db.evolution_jobs import EvolutionRun
from backend.db.judge_calibration import latest_approved_calibration
from backend.db.models import EvolutionTournament
from backend.db.models import PublishedReview
from backend.db.models import RoleStrategyCard as CardRow
from backend.db.models import StrategyKnowledgeDoc as KnowledgeRow
from backend.db.models import StrategyPatch as PatchRow
from backend.engine.rules import WOLFCHA_ROLE_CONFIGS
from backend.eval.evolution import AcceptancePolicy
from backend.eval.evolution import KnowledgeDocValidator
from backend.eval.evolution import PatchOperation
from backend.eval.evolution import PatchValidator
from backend.eval.evolution import RoleStrategyCard
from backend.eval.evolution import StrategyKnowledgeDoc
from backend.eval.evolution import StrategyKnowledgeDocExtractor
from backend.eval.evolution import StrategyPatch
from backend.eval.evolution import StrategyPatchGenerator
from backend.eval.evolution import TournamentRunner
from backend.eval.evolution import extract_from_review_reports
from backend.eval.evolution import sanitize_knowledge_doc
from backend.eval.judge_rubric import RUBRIC_HASH
from backend.eval.knowledge_confidence import confidence_allowed
from backend.eval.track_b import reconstruct_review_report

logger = logging.getLogger(__name__)
_TERMINAL = {"completed", "pending_review"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _patch(payload: dict[str, Any]) -> StrategyPatch:
    payload = dict(payload)
    payload["operations"] = [PatchOperation(**operation) for operation in payload["operations"]]
    return StrategyPatch(**payload)


class CoordinatorLeaseLost(RuntimeError):
    pass


class TrackCCoordinator:
    """Only writer of DAG state and active strategy versions.

    Successful nodes are immutable artifacts and are reused after failure.
    An owner token fences stale coordinators; a role head CAS serializes final
    promotion even when different games propose a patch for the same role.
    """

    def __init__(
        self,
        *,
        session_factory=None,
        tournament_worker: TournamentWorker | None = None,
        concurrency: int | None = None,
        seeds: list[int] | None = None,
        judge_model: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        lease_seconds: int = 1800,
    ) -> None:
        self.sessions = session_factory or SessionLocal
        self.worker = tournament_worker or TournamentWorker()
        self.concurrency = max(1, min(32, int(concurrency or os.getenv("TRACK_C_CONCURRENCY", "2"))))
        self.provider = provider or os.getenv("LLM_PROVIDER", "") or None
        self.player_count = int(os.getenv("TRACK_C_PLAYER_COUNT", "0")) or None
        self.max_days = max(1, int(os.getenv("TRACK_C_MAX_DAYS", "20")))
        self.scoring_mode = os.getenv("TRACK_B_JUDGE_SCORING_MODE", "single_step")
        if self.scoring_mode not in {"single_step", "panel_step"}:
            raise ValueError("Unsupported Track B Judge scoring mode")
        raw_seeds = os.getenv("TRACK_C_SEEDS", "")
        self.seeds = (
            list(seeds)
            if seeds is not None
            else (
                [int(seed.strip()) for seed in raw_seeds.split(",") if seed.strip()]
                if raw_seeds
                else list(range(1, 4 if self.provider == "fake" else 21))
            )
        )
        if not self.seeds or len(self.seeds) != len(set(self.seeds)):
            raise ValueError("Track C seeds must be nonempty and unique")
        self.judge_model = judge_model or os.getenv("TRACK_B_JUDGE_MODEL", "")
        self.model = model
        self.lease_seconds = max(30, lease_seconds)

    def execute(self, game_id: str, *, reports=None, request_id: str | None = None) -> dict[str, Any]:
        init_db()
        run_id = f"track-c:{game_id}:{request_id or 'v1'}"
        config = {
            "seeds": self.seeds,
            "provider": self.provider,
            "model": self.model,
            "judge_model": self.judge_model,
            "rubric_hash": RUBRIC_HASH,
            "scoring_mode": self.scoring_mode,
            "player_count": self.player_count,
            "max_days": self.max_days,
            "model_pool_hash": _hash(os.getenv("MODEL_POOL", "") or os.getenv("DOUBAO_MODEL_POOL", "")),
        }
        token, cached = self._claim(run_id, game_id, _hash(config))
        if token is None:
            return cached
        try:
            approved = self._approved_reports(game_id, reports)
            evidence = self._cached(run_id, "evidence")
            if evidence is None:
                evidence = self._mine(approved)
                self._put(run_id, token, "evidence", "evidence", evidence)
            proposal = self._cached(run_id, "proposal")
            if proposal is None:
                docs = [StrategyKnowledgeDoc(**doc) for doc in evidence["documents"]]
                cards = self._cards({doc.role for doc in docs})
                candidates = StrategyPatchGenerator().generate(docs, cards)
                for index, patch in enumerate(candidates):
                    patch.patch_id = f"{run_id}:patch:{index}"
                    patch.to_version = f"{patch.target_role.lower()}_{_hash(patch.patch_id)[:12]}_candidate"
                proposal = {
                    "patches": [patch.to_dict() for patch in candidates],
                    "baselines": {role: asdict(card) for role, card in cards.items()},
                }
                self._put(run_id, token, "proposal", "proposal", proposal)
            patch_results = []
            # Finalization stays serial; tournament seed tasks run in parallel.
            for payload in proposal["patches"]:
                patch = _patch(payload)
                base = RoleStrategyCard(**proposal["baselines"][patch.target_role])
                critic_key = f"critic:{patch.patch_id}"
                critic = self._cached(run_id, critic_key)
                if critic is None:
                    critic = asdict(PatchValidator().validate(patch))
                    self._put(run_id, token, critic_key, "red_team", critic)
                if not critic["passed"]:
                    patch_results.append({"patch_id": patch.patch_id, "status": "rejected", "critic": critic})
                    continue
                candidate = card_with_patch(base, patch)
                design_key = f"design:{patch.patch_id}"
                if self._cached(run_id, design_key) is None:
                    self._put(
                        run_id,
                        token,
                        design_key,
                        "experiment_design",
                        {
                            "seeds": self.seeds,
                            "target_role": patch.target_role,
                            "player_count": self._player_count(patch.target_role),
                            "max_days": self.max_days,
                            "pairing": "same_seed_seat_role_persona_model",
                            "baseline_version": base.version,
                            "candidate_version": candidate.version,
                            "provider": self.provider,
                            "model": self.model,
                        },
                    )
                pairs = self._tournament(run_id, token, patch, base, candidate)
                gate_key = f"gate:{patch.patch_id}"
                gate = self._cached(run_id, gate_key)
                if gate is None:
                    gate = self._gate(pairs, patch.target_role)
                    # Artifacts + role CAS + strategy writes commit atomically.
                    gate = self._finalize(run_id, token, patch, candidate, evidence["documents"], pairs, gate)
                patch_results.append({"patch_id": patch.patch_id, **gate})
            pending = any(item["status"] == "pending_review" for item in patch_results)
            result = {
                "run_id": run_id,
                "game_id": game_id,
                "status": "pending_review" if pending or not approved else "completed",
                "promoted_count": sum(item["status"] == "promoted" for item in patch_results),
                "patches": patch_results,
                "evidence_count": len(evidence["documents"]),
                "artifacts": self._artifact_summary(run_id),
            }
            self._finish(run_id, token, result)
            count("track_c.run.pending_review" if result["status"] == "pending_review" else "track_c.run.completed")
            log_event(
                logger,
                "track_c_finished",
                match_id=game_id,
                request_id=run_id,
                status=result["status"],
                promoted_count=result["promoted_count"],
            )
            return result
        except Exception as exc:
            with self.sessions.begin() as db:
                db.query(EvolutionRun).filter(EvolutionRun.id == run_id, EvolutionRun.owner_token == token).update(
                    {
                        "status": "failed",
                        "last_error": type(exc).__name__,
                        "owner_token": None,
                        "lease_until": None,
                        "updated_at": _now(),
                    },
                    synchronize_session=False,
                )
            count("track_c.run.failed")
            log_event(
                logger,
                "track_c_failed",
                level=logging.WARNING,
                match_id=game_id,
                request_id=run_id,
                error_type=type(exc).__name__,
            )
            raise

    def _claim(self, run_id, game_id, input_hash):
        with self.sessions() as db:
            row = db.get(EvolutionRun, run_id)
            if row is None:
                db.add(EvolutionRun(id=run_id, game_id=game_id, input_hash=input_hash, status="pending"))
                try:
                    db.commit()
                except IntegrityError:
                    db.rollback()
                row = db.get(EvolutionRun, run_id)
            if row.input_hash != input_hash:
                raise ValueError("Coordinator idempotency key was reused with a different experiment configuration")
            if row.status in _TERMINAL:
                return None, dict(row.result)
            token = uuid4().hex
            claimed = (
                db.query(EvolutionRun)
                .filter(
                    EvolutionRun.id == run_id,
                    or_(
                        EvolutionRun.status.in_(["pending", "failed"]),
                        (EvolutionRun.status == "running") & (EvolutionRun.lease_until < _now()),
                    ),
                )
                .update(
                    {
                        "status": "running",
                        "owner_token": token,
                        "attempts": EvolutionRun.attempts + 1,
                        "lease_until": _now() + timedelta(seconds=self.lease_seconds),
                        "last_error": "",
                        "updated_at": _now(),
                    },
                    synchronize_session=False,
                )
            )
            db.commit()
            return (
                (token, None)
                if claimed
                else (None, {"run_id": run_id, "game_id": game_id, "status": "running", "promoted_count": 0})
            )

    def _fence(self, db, run_id, token, stage):
        changed = (
            db.query(EvolutionRun)
            .filter(
                EvolutionRun.id == run_id,
                EvolutionRun.owner_token == token,
                EvolutionRun.status == "running",
                EvolutionRun.lease_until >= _now(),
            )
            .update(
                {"stage": stage, "lease_until": _now() + timedelta(seconds=self.lease_seconds), "updated_at": _now()},
                synchronize_session=False,
            )
        )
        if not changed:
            raise CoordinatorLeaseLost("Track C coordinator no longer owns its lease")

    def _cached(self, run_id, node):
        with self.sessions() as db:
            row = db.query(EvolutionArtifact).filter_by(run_id=run_id, node_key=node).first()
            return dict(row.payload) if row else None

    def _put(self, run_id, token, node, kind, payload):
        with self.sessions.begin() as db:
            self._fence(db, run_id, token, node)
            db.add(
                EvolutionArtifact(
                    id=f"{run_id}:{node}", run_id=run_id, node_key=node, artifact_type=kind, payload=payload
                )
            )

    def _approved_reports(self, game_id, reports):
        if reports is not None:
            return [
                r
                for r in reports
                if (r.metadata.get("validation_result") or {}).get("passed") is True
                and (r.metadata.get("validation_result") or {}).get("publish_allowed") is True
            ]
        with self.sessions() as db:
            rows = db.query(PublishedReview).filter_by(game_id=game_id, publish_allowed=True).all()
            result = []
            for row in rows:
                report = reconstruct_review_report(row.report_json)
                report.metadata["validation_result"] = row.validation_result
                if (row.validation_result or {}).get("passed") is True:
                    result.append(report)
            return result

    def _mine(self, reports):
        documents = []
        rejected = 0
        for report in reports:
            candidates = getattr(report, "evolution_candidates", [])
            if candidates:
                # Private postgame evidence must never become a public lesson.
                safe = [
                    c
                    for c in candidates
                    if c.visibility_scope == "public"
                    and all(
                        ref.visibility_scope == "public" and ref.public_or_private == "public"
                        for ref in c.evidence_refs
                    )
                ]
                from copy import copy

                clean = copy(report)
                clean.evolution_candidates = safe
                docs = extract_from_review_reports([clean])
                rejected += len(candidates) - len(safe)
            else:
                docs = StrategyKnowledgeDocExtractor().extract([report])
            for doc in docs:
                sanitized = sanitize_knowledge_doc(doc)
                doc = sanitized.doc
                checks = {**doc.to_dict(), "confidence_score": doc.confidence}
                if (
                    not sanitized.safe_for_track_c_learning
                    or not sanitized.safe_for_in_game_retrieval
                    or KnowledgeDocValidator().validate(doc)
                    or not confidence_allowed(checks)
                ):
                    rejected += 1
                    continue
                doc.doc_id = (
                    f"track-c-doc:{_hash([doc.source_report_ids, doc.role, doc.phase, doc.recommended_action])[:24]}"
                )
                doc.status = "candidate"
                documents.append(doc.to_dict())
        # Evidence retries and duplicate reports have one immutable document.
        return {"documents": list({doc["doc_id"]: doc for doc in documents}.values()), "rejected_count": rejected}

    def _cards(self, roles):
        result = {}
        with self.sessions() as db:
            for role in sorted(roles):
                rows = db.query(CardRow).filter_by(role=role, status="active").order_by(CardRow.created_at.desc()).all()
                if len({row.version for row in rows}) > 1:
                    raise ValueError("Multiple active strategy versions require explicit reconciliation")
                row = rows[0] if rows else None
                result[role] = RoleStrategyCard(
                    role=role,
                    version=row.version if row else f"{role.lower()}_v1",
                    goal=row.goal if row else f"Play the {role} role toward its camp win condition.",
                    **(
                        {
                            key: getattr(row, key)
                            for key in (
                                "speech_policy",
                                "vote_policy",
                                "skill_policy",
                                "risk_rules",
                                "retrieval_policy",
                            )
                        }
                        if row
                        else {}
                    ),
                )
        return result

    def _player_count(self, role):
        if self.player_count is not None:
            if not any(item.value == role for item in WOLFCHA_ROLE_CONFIGS.get(self.player_count, ())):
                raise ValueError("Configured tournament lineup does not contain the target role")
            return self.player_count
        for player_count, roles in sorted(WOLFCHA_ROLE_CONFIGS.items()):
            if any(item.value == role for item in roles):
                return player_count
        raise ValueError("No playable tournament lineup for target role")

    def _tournament(self, run_id, token, patch, baseline, candidate):
        results = {}
        pending = []
        for seed in self.seeds:
            node = f"tournament:{patch.patch_id}:{seed}"
            cached = self._cached(run_id, node)
            if cached is not None:
                self._validate_pair(
                    cached, node, seed, patch.target_role, self.provider, baseline.version, candidate.version
                )
                results[seed] = cached
            else:
                pending.append((seed, node))
        queue = iter(pending)
        with ThreadPoolExecutor(max_workers=self.concurrency, thread_name_prefix="track-c-tournament") as executor:
            futures = {}

            def submit_next():
                item = next(queue, None)
                if item is None:
                    return
                seed, node = item
                task = TournamentTask(
                    task_id=node,
                    seed=seed,
                    baseline=baseline,
                    candidate=candidate,
                    provider=self.provider,
                    model=self.model,
                    player_count=self._player_count(patch.target_role),
                    max_days=self.max_days,
                )
                futures[executor.submit(self.worker.execute, task)] = item

            for _ in range(self.concurrency):
                submit_next()
            try:
                while futures:
                    completed, _ = wait(futures, timeout=min(10, self.lease_seconds / 3), return_when=FIRST_COMPLETED)
                    with self.sessions.begin() as db:
                        self._fence(db, run_id, token, "tournament")
                    for future in completed:
                        seed, node = futures.pop(future)
                        artifact = future.result()
                        self._validate_pair(
                            artifact, node, seed, patch.target_role, self.provider, baseline.version, candidate.version
                        )
                        self._put(run_id, token, node, "tournament_pair", artifact)
                        results[seed] = artifact
                        submit_next()
            except Exception:
                for future in futures:
                    future.cancel()
                raise
        return [results[seed] for seed in self.seeds]

    @staticmethod
    def _validate_pair(
        artifact, node, seed, target_role, expected_provider=None, baseline_version=None, candidate_version=None
    ):
        import math

        if (
            artifact.get("schema_version") != "paired-tournament-v1"
            or artifact.get("task_id") != node
            or artifact.get("seed") != seed
        ):
            raise ValueError("Tournament worker returned an invalid task artifact")
        for side in ("baseline", "candidate"):
            metric = metric_from_artifact(artifact[side])
            if metric.metadata.get("tournament_seed") != seed or metric.metadata.get("phase") != "GAME_END":
                raise ValueError("Tournament artifact is not a completed paired seed")
            if not artifact.get("lineup_hash") or metric.metadata.get("lineup_hash") != artifact["lineup_hash"]:
                raise ValueError("Tournament artifact has mismatched lineup provenance")
            for key in (
                "info_leak_count",
                "invalid_action_count",
                "fallback_count",
                "patch_caused_fallback_count",
                "rule_violation_count",
            ):
                value = metric.metadata.get(key)
                if type(value) is not int or value < 0:
                    raise ValueError("Tournament artifact requires explicit nonnegative safety counts")
            infra = metric.metadata.get("infra_fallback_count", 0)
            if (
                type(infra) is not int
                or infra < 0
                or metric.metadata["patch_caused_fallback_count"] + infra != metric.metadata["fallback_count"]
            ):
                raise ValueError("Tournament artifact fallback attribution is incomplete")
            invalid_rate = metric.metadata.get("invalid_action_rate")
            if (
                not isinstance(invalid_rate, (int, float))
                or not math.isfinite(invalid_rate)
                or not 0 <= invalid_rate <= 1
            ):
                raise ValueError("Tournament artifact requires a valid invalid-action rate")
            if bool(metric.metadata["invalid_action_count"]) != bool(invalid_rate):
                raise ValueError("Tournament artifact invalid-action count/rate disagree")
            expected_version = baseline_version if side == "baseline" else candidate_version
            if expected_version and metric.metadata.get("strategy_version") != expected_version:
                raise ValueError("Tournament artifact strategy version does not match its task")
            assignments = metric.metadata.get("model_assignments") or []
            if not assignments or any(not item.get("model") or not item.get("provider") for item in assignments):
                raise ValueError("Tournament artifact is missing model provenance")
            if expected_provider and any(item["provider"] != expected_provider for item in assignments):
                raise ValueError("Tournament artifact provider does not match its task")
            if side == "candidate" and assignments != artifact["baseline"]["metadata"].get("model_assignments"):
                raise ValueError("Tournament pair model assignments differ")
            synthetic = any(item["provider"] == "fake" or "fake" in item["model"].lower() for item in assignments)
            if metric.metadata.get("synthetic") is not synthetic or artifact.get("synthetic") is not synthetic:
                raise ValueError("Tournament artifact mislabels synthetic evidence")
            target = [score for score in metric.player_scores if score.role.lower() == target_role.lower()]
            if not target:
                raise ValueError("Tournament artifact is missing the target role")
            if not all(
                math.isfinite(float(value))
                for score in metric.player_scores
                for value in (
                    score.final_score,
                    score.role_task_score,
                    score.adjusted_final_score if score.adjusted_final_score is not None else score.final_score,
                )
            ):
                raise ValueError("Tournament artifact contains non-finite scores")

    def _gate(self, pairs, target_role):
        baseline = [metric_from_artifact(pair["baseline"]) for pair in pairs]
        candidate = [metric_from_artifact(pair["candidate"]) for pair in pairs]
        comparison = TournamentRunner().compare_paired_seed_results(baseline, candidate, target_role=target_role)
        decision = AcceptancePolicy().decide(evolution_comparison=comparison).to_dict()
        with self.sessions() as db:
            calibration = (
                latest_approved_calibration(
                    db, judge_model=self.judge_model, rubric_hash=RUBRIC_HASH, scoring_mode=self.scoring_mode
                )
                if self.judge_model
                else None
            )
        calibrated = bool(calibration and calibration.get("human_verified") and not calibration.get("synthetic"))
        real_pairs = self.provider != "fake" and not any(pair.get("synthetic", True) for pair in pairs)
        sufficient_trials = len(pairs) >= 20
        decision["hard_gate_results"]["human_judge_calibration"] = calibrated
        decision["hard_gate_results"]["non_synthetic_tournament"] = real_pairs
        decision["hard_gate_results"]["minimum_20_paired_seeds"] = sufficient_trials
        status = decision["status"]
        if decision["passed_hard_gates"]:
            if not calibrated or not real_pairs:
                status = "pending_review"
            elif not sufficient_trials:
                status = "needs_more_trials"
        return {
            "status": status,
            "decision": decision,
            "comparison": comparison.to_dict(),
            "calibration_id": calibration["calibration_id"] if calibration else None,
        }

    def _finalize(self, run_id, token, patch, candidate, documents, pairs, gate):
        with self.sessions.begin() as db:
            self._fence(db, run_id, token, "promotion")
            # Lock the row for PG; UPDATE CAS also protects SQLite/other backends.
            head = db.query(EvolutionRoleHead).filter_by(role=patch.target_role).with_for_update().first()
            if head is None:
                current = db.query(CardRow).filter_by(role=patch.target_role, status="active").first()
                head = EvolutionRoleHead(
                    role=patch.target_role, version=current.version if current else patch.from_version
                )
                db.add(head)
                db.flush()
            if gate["status"] == "promoted":
                rejected_sources = (
                    db.query(KnowledgeRow)
                    .filter(
                        KnowledgeRow.id.in_(patch.source_knowledge_doc_ids),
                        or_(
                            KnowledgeRow.human_verdict == "rejected",
                            KnowledgeRow.status.in_(["deprecated", "disputed"]),
                        ),
                    )
                    .count()
                )
                if rejected_sources:
                    gate["status"] = "rolled_back"
                    gate["decision"]["hard_gate_results"]["knowledge_sources_not_rejected"] = False
                    gate["decision"]["reason"] = "Source knowledge was rejected or deprecated before promotion"
            if gate["status"] == "promoted":
                active_versions = {
                    row.version for row in db.query(CardRow).filter_by(role=patch.target_role, status="active")
                }
                if active_versions and active_versions != {patch.from_version}:
                    gate["status"] = "pending_review"
                    gate["decision"]["reason"] = "Active baseline changed outside the coordinator; rebase required"
            if gate["status"] == "promoted":
                changed = (
                    db.query(EvolutionRoleHead)
                    .filter_by(role=patch.target_role, version=patch.from_version)
                    .update(
                        {"version": candidate.version, "revision": EvolutionRoleHead.revision + 1},
                        synchronize_session=False,
                    )
                )
                if not changed:
                    gate["status"] = "pending_review"
                    gate["decision"]["reason"] = "Active baseline changed; rebase and rerun the paired experiment"
                else:
                    db.query(CardRow).filter_by(role=patch.target_role, status="active").update(
                        {"status": "deprecated"}
                    )
            active = gate["status"] == "promoted"
            gate["decision"]["accepted"] = active
            gate["decision"]["status"] = gate["status"]
            gate["decision"]["passed_hard_gates"] = all(gate["decision"]["hard_gate_results"].values())
            card = asdict(candidate)
            card["status"] = "active" if active else "candidate"
            db.merge(CardRow(id=f"track-c-card:{candidate.version}", **card))
            patch_data = patch.to_dict()
            patch_data.pop("patch_id")
            # Non-column provenance stays in the immutable proposal artifact.
            for key in ("created_at", "experimental", "generation_reason", "trust_level", "validated_on"):
                patch_data.pop(key, None)
            patch_data["status"] = gate["status"]
            db.merge(PatchRow(id=patch.patch_id, **patch_data))
            for payload in documents:
                if payload["doc_id"] not in patch.source_knowledge_doc_ids:
                    continue
                data = {
                    column.name: payload[column.name]
                    for column in KnowledgeRow.__table__.columns
                    if column.name in payload and column.name not in {"id", "created_at", "updated_at", "validated_at"}
                }
                existing = db.get(KnowledgeRow, payload["doc_id"])
                # A new pending run cannot demote validated knowledge or revive
                # a human-rejected/harmful lesson through an evidence upsert.
                if existing is not None and (
                    existing.status in {"active", "deprecated", "disputed"} or existing.human_verdict == "rejected"
                ):
                    continue
                data["status"] = "active" if active else "pending_review"
                db.merge(KnowledgeRow(id=payload["doc_id"], **data))
            db.merge(
                EvolutionTournament(
                    id=f"{patch.patch_id}:tournament",
                    baseline_version=patch.from_version,
                    candidate_version=candidate.version,
                    target_role=patch.target_role,
                    seeds=self.seeds,
                    baseline_results=[pair["baseline"] for pair in pairs],
                    candidate_results=[pair["candidate"] for pair in pairs],
                    comparison=gate["comparison"],
                    decision=gate["decision"],
                    status=gate["status"],
                )
            )
            db.add(
                EvolutionArtifact(
                    id=f"{run_id}:gate:{patch.patch_id}",
                    run_id=run_id,
                    node_key=f"gate:{patch.patch_id}",
                    artifact_type="promotion_gate",
                    payload=gate,
                )
            )
        return gate

    def _artifact_summary(self, run_id):
        with self.sessions() as db:
            return [
                {"node_key": row.node_key, "artifact_type": row.artifact_type}
                for row in db.query(EvolutionArtifact).filter_by(run_id=run_id).order_by(EvolutionArtifact.node_key)
            ]

    def _finish(self, run_id, token, result):
        with self.sessions.begin() as db:
            self._fence(db, run_id, token, "complete")
            db.query(EvolutionRun).filter_by(id=run_id, owner_token=token).update(
                {
                    "status": result["status"],
                    "stage": "complete",
                    "result": result,
                    "owner_token": None,
                    "lease_until": None,
                },
                synchronize_session=False,
            )
