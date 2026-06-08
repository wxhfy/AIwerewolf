from __future__ import annotations

from dataclasses import dataclass

from backend.db import database
from backend.eval import knowledge_abstractor


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
                if row.status == "candidate"
                and row.quality_score >= 0.85
                and not row.doc_type.startswith("reflection")
            ]
        if self._query_number == 2:
            return [
                row
                for row in self._rows
                if row.status == "candidate"
                and row.quality_score >= 0.75
                and not row.doc_type.startswith("reflection")
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
