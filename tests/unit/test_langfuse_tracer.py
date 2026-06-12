# Langfuse 콜백 헬퍼 — 키 없으면 빈 콜백(no-op), 트레이싱 데코레이터 로컬 레코드 검증
from src.evaluation.langfuse_tracer import (
    clear_local_records,
    get_local_records,
    langfuse_callbacks,
    trace,
)


def test_langfuse_callbacks_empty_without_key(monkeypatch):
    # 키가 없으면 콜백을 만들지 않는다 (LangGraph invoke가 no-op으로 동작)
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    assert langfuse_callbacks() == []


def test_trace_records_locally_without_key(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    clear_local_records()

    @trace(name="add")
    def add(a, b):
        return a + b

    assert add(2, 3) == 5
    records = get_local_records()
    assert len(records) == 1
    assert records[0].name == "add"
    assert records[0].error is None
