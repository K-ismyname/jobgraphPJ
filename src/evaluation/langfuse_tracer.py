# Langfuse 트레이싱 데코레이터 — 키 없으면 no-op, 있으면 클라우드 전송
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable

# Langfuse 4.x: observe가 LANGFUSE_PUBLIC_KEY 없으면 자동 no-op
from langfuse import get_client, observe  # noqa: F401 (re-export)

# ── 로컬 추적 레코드 (오프라인 검사용) ──────────────────────────────
_local_records: list["LocalTraceRecord"] = []


@dataclass
class LocalTraceRecord:
    """LANGFUSE 키 없이도 함수 호출 정보를 메모리에 기록한다."""

    name: str
    inputs: dict[str, Any]
    output: Any
    duration_ms: float
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def trace(
    name: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Callable:
    """Langfuse observe + 로컬 레코드를 동시에 남기는 데코레이터.

    LANGFUSE_PUBLIC_KEY가 설정돼 있으면 클라우드에도 전송된다.
    없으면 LocalTraceRecord만 메모리에 쌓인다.
    """
    def decorator(fn: Callable) -> Callable:
        trace_name = name or fn.__name__

        # observe()로 Langfuse 계층 적용 (no-op safe)
        fn_with_langfuse = observe(name=trace_name)(fn)

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            error_msg = None
            result = None
            try:
                result = fn_with_langfuse(*args, **kwargs)
                return result
            except Exception as e:
                error_msg = str(e)
                raise
            finally:
                duration = (time.perf_counter() - start) * 1000
                _local_records.append(
                    LocalTraceRecord(
                        name=trace_name,
                        inputs=kwargs,
                        output=result,
                        duration_ms=round(duration, 2),
                        error=error_msg,
                        metadata=metadata or {},
                    )
                )

        wrapper.__name__ = fn.__name__
        wrapper.__doc__  = fn.__doc__
        return wrapper

    return decorator


def flush() -> None:
    """Langfuse 클라이언트의 비동기 큐를 즉시 전송한다. 키 없으면 no-op."""
    if not os.getenv("LANGFUSE_PUBLIC_KEY"):
        return
    try:
        client = get_client()
        client.flush()
    except Exception:
        pass


def get_local_records() -> list[LocalTraceRecord]:
    """메모리에 쌓인 로컬 트레이스 레코드를 반환한다."""
    return list(_local_records)


def clear_local_records() -> None:
    """로컬 레코드를 초기화한다 (테스트용)."""
    _local_records.clear()
