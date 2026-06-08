from __future__ import annotations

from dataclasses import dataclass

from backend.db import database
from backend.db import persist
from backend.eval import knowledge_abstractor
from backend.eval.evolution import StrategyKnowledgeDoc


@dataclass
class _FakeKnowledgeRow:
    id: str
    doc_type: str
    role: str
    quality_score: float
    status: str = "candidate"


class _FakeQuery:
    def __init__(self, rows: list[_FakeKnowledgeRow], query_number: int):
        self._rows = rows
        self._query_number = query_number

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def all(self) -> list[_FakeKnowledgeRow]:
        if self._query_number == 1:
            return [
                row
                for row in self._rows
                if row.status == "candidate" and row.quality_score >= 0.85 and not row.doc_type.startswith("reflection")
            ]
        if self._query_number == 2:
            return [
                row
                for row in self._rows
                if row.status == "candidate" and row.quality_score >= 0.75 and not row.doc_type.startswith("reflection")
            ]
        return [row for row in self._rows if row.status == "active"]


class _FakeSession:
    def __init__(self, rows: list[_FakeKnowledgeRow]):
        self._rows = rows
        self._query_count = 0
        self.committed = False

    def query(self, *_args, **_kwargs) -> _FakeQuery:
        self._query_count += 1
        return _FakeQuery(self._rows, self._query_count)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass


def test_promote_after_store_does_not_auto_promote_reflections(monkeypatch) -> None:
    rows = [
        _FakeKnowledgeRow("reflection-high", "reflection", "Seer", 0.99),
        _FakeKnowledgeRow("lesson-high", "per_step_lesson", "Seer", 0.91),
    ]
    session = _FakeSession(rows)
    monkeypatch.setattr(database, "SessionLocal", lambda: session)

    promoted = knowledge_abstractor.promote_after_store()

    by_id = {row.id: row for row in rows}
    assert promoted == 1
    assert by_id["reflection-high"].status == "candidate"
    assert by_id["lesson-high"].status == "active"
    assert session.committed


class _UpsertQuery:
    def __init__(self, session):
        self._session = session

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self._session.row


class _UpsertSession:
    def __init__(self, row=None):
        self.row = row
        self.added = []

    def query(self, *_args, **_kwargs):
        return _UpsertQuery(self)

    def add(self, row):
        self.row = row
        self.added.append(row)


def _strategy_doc(doc_id: str, report_id: str, item_id: str, event_id: str) -> StrategyKnowledgeDoc:
    return StrategyKnowledgeDoc(
        doc_id=doc_id,
        doc_type="per_step_lesson",
        role="Seer",
        phase="DAY_SPEECH",
        persona_scope=None,
        situation_pattern="公开票型压力下的预言家发言",
        trigger_conditions=["公开票型压力"],
        recommended_action="白天基于公开票型明确归票。",
        avoid_action=None,
        rationale="复盘证据显示公开归票提高协同。",
        evidence_summary="approved evidence",
        source_report_ids=[report_id],
        source_item_ids=[item_id],
        source_event_ids=[event_id],
        counterfactual_ids=[],
        expected_metric_effects=[],
        quality_score=0.8,
        confidence=0.8,
        status="candidate",
        source_game_id=report_id,
        source_decision_id=item_id,
    )


def test_upsert_strategy_knowledge_preserves_report_item_event_ids() -> None:
    session = _UpsertSession()

    persist._upsert_strategy_knowledge_rows(session, [_strategy_doc("doc-1", "game-1", "item-1", "event-1")])
    persist._upsert_strategy_knowledge_rows(session, [_strategy_doc("doc-2", "game-2", "item-2", "event-2")])

    assert sorted(session.row.source_report_ids) == ["game-1", "game-2"]
    assert sorted(session.row.source_item_ids) == ["item-1", "item-2"]
    assert sorted(session.row.source_event_ids) == ["event-1", "event-2"]
    assert session.row.source_game_id == "game-1"
    assert session.row.source_decision_id == "item-1"


class _UsageQuery:
    def __init__(self, doc):
        self._doc = doc

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self._doc


class _UsageSession:
    def __init__(self, doc):
        self.doc = doc
        self.rows = []
        self.committed = False

    def add(self, row):
        row.id = "usage-row"
        self.rows.append(row)

    def query(self, *_args, **_kwargs):
        return _UsageQuery(self.doc)

    def commit(self):
        self.committed = True

    def close(self):
        pass


def test_record_knowledge_usage_retrieval_trace_is_neutral(monkeypatch) -> None:
    doc = type(
        "Doc",
        (),
        {
            "id": "doc-1",
            "usage_count": 0,
            "success_count": 0,
            "failure_count": 0,
            "status": "active",
            "quality_score": 0.9,
        },
    )()
    session = _UsageSession(doc)
    monkeypatch.setattr(persist, "init_db", lambda: None)
    monkeypatch.setattr(persist, "SessionLocal", lambda: session)

    result = persist.record_knowledge_usage(
        {
            "game_id": "game-1",
            "player_id": "player-1",
            "knowledge_doc_id": "doc-1",
            "retrieved": True,
            "used": False,
            "metadata": {"feedback_stage": "retrieval_trace"},
        }
    )

    assert result["knowledge_doc_id"] == "doc-1"
    assert doc.usage_count == 0
    assert doc.success_count == 0
    assert doc.failure_count == 0
    assert doc.status == "active"
    assert session.committed
