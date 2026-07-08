# Langfuse 트레이싱 데코레이터 — 키 없으면 no-op, 있으면 클라우드 전송
#
# 한 줄 요약: "이 함수가 언제, 어떤 입력으로, 얼마나 걸려서, 무슨 결과를 냈는지" 자동으로 기록해주는 파일.
# CLAUDE.md에 나온 "Langfuse + RAGAS 평가"에서 Langfuse(트레이싱·관측) 부분이 이 파일입니다.
# 핵심 아이디어: Langfuse API 키가 없어도 프로그램이 안 죽고, 그냥 "기록을 클라우드로 안 보낼 뿐"
# 로컬 메모리에는 계속 기록되게 만들어져 있습니다. 이런 걸 "no-op(아무 일도 안 함) 안전 설계"라고 부릅니다.

from __future__ import annotations

import functools
import os
import time
from collections import deque
# deque(데크) — 리스트랑 비슷한데, "최대 개수"를 미리 정해두면 그 개수를 넘는 순간
# 제일 오래된 것부터 자동으로 버려짐. 계속 쌓이기만 하는 리스트와 달리 메모리가 무한정 안 늘어남.
from dataclasses import dataclass, field
# dataclass — pydantic의 BaseModel과 비슷하게 "이런 필드를 가진 상자"를 간단히 만드는 방법.
# pydantic만큼 엄격한 검증은 안 하지만, 코드가 더 짧고 가벼움. 이 파일처럼 "그냥 데이터만 담는 상자"엔 충분.
from typing import Any, Callable

# Langfuse 4.x: observe가 LANGFUSE_PUBLIC_KEY 없으면 자동 no-op
from langfuse import get_client, observe  # noqa: F401 (re-export)
# get_client, observe는 이 파일에서 직접 안 쓰이는 것처럼 보여도(observe는 아래서 씀),
# "# noqa: F401"은 린터(코드 검사 도구)에게 "이 import 경고는 무시해라"라고 알려주는 표시.
# 다른 파일이 이 파일을 통해서 get_client를 가져다 쓸 수 있게 "재수출(re-export)"하는 용도.

# ── 로컬 추적 레코드 (오프라인 검사용) ──────────────────────────────
# 장기 구동 서버에서 무한 증가하지 않도록 최근 N개만 유지
_local_records: "deque[LocalTraceRecord]" = deque(maxlen=1000)
# maxlen=1000 → 최근 1000개까지만 기억하고, 1001번째가 들어오면 제일 오래된 걸 자동으로 지움.
# 이게 없으면 서버를 오래 켜둘수록 이 리스트가 끝없이 커져서 메모리를 다 잡아먹는 문제(메모리 누수)가 생김.


@dataclass
class LocalTraceRecord:
    """LANGFUSE 키 없이도 함수 호출 정보를 메모리에 기록한다."""

    name: str
    inputs: dict[str, Any]
    output: Any
    duration_ms: float
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    # 기본값이 dict({})나 list([])처럼 "바뀔 수 있는 값"일 땐 그냥 "= {}"라고 못 쓰고
    # field(default_factory=dict)라고 써야 함 — 파이썬의 규칙. dataclass를 쓸 때 자주 나오는 관용구.


def trace(
    name: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Callable:
    """Langfuse observe + 로컬 레코드를 동시에 남기는 데코레이터.

    LANGFUSE_PUBLIC_KEY가 설정돼 있으면 클라우드에도 전송된다.
    없으면 LocalTraceRecord만 메모리에 쌓인다.
    """
    # "데코레이터"란: 함수를 하나 받아서, "그 함수 실행 앞뒤로 뭔가를 더 해주는 새 함수"로 바꿔주는 문법.
    # 여기선 "원래 함수를 실행하면서, 시간도 재고 결과도 기록해주는" 기능을 덧붙임.
    def decorator(fn: Callable) -> Callable:
        # decorator(fn) — 실제로 감쌀 대상 함수(fn)를 받는 안쪽 함수
        trace_name = name or fn.__name__
        # trace(name="내이름")처럼 이름을 직접 안 줬으면, 함수 자체의 이름(fn.__name__)을 그대로 씀

        # observe()로 Langfuse 계층 적용 (no-op safe)
        fn_with_langfuse = observe(name=trace_name)(fn)
        # Langfuse 라이브러리가 제공하는 observe()로 한 번 더 감쌈 — 이게 실제로 클라우드 전송을 담당.
        # 문서에 적힌 대로, 키가 없으면 observe()는 아무것도 안 하고 원래 함수를 그대로 통과시킴(no-op).

        @functools.wraps(fn)
        # @functools.wraps(fn) — 데코레이터를 쓰면 원래 함수의 이름·설명(docstring) 같은 정보가
        # 사라지고 wrapper라는 이름으로 덮여버리는데, 이 한 줄이 그 정보를 원래 함수 것 그대로 유지해줌.
        # (없어도 동작은 하지만, 디버깅할 때 함수 이름이 다 "wrapper"로 나와서 헷갈리는 걸 방지)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            # perf_counter() — 아주 정밀하게 시간을 재는 시계. "지금부터 시작"이라고 찍어둠
            error_msg = None
            result = None
            try:
                result = fn_with_langfuse(*args, **kwargs)
                return result
            except Exception as e:
                error_msg = str(e)
                raise
                # 에러가 나면 error_msg에 내용만 적어두고, raise로 에러를 그대로 다시 던짐 —
                # 이 데코레이터는 "기록만" 할 뿐 에러를 숨기거나 대신 처리하지 않음
            finally:
                # finally 블록은 성공하든 에러가 나든 무조건 실행됨 — "기록 남기기"는 결과와 상관없이 항상 해야 하니까
                duration = (time.perf_counter() - start) * 1000
                # 끝난 시각에서 시작 시각을 빼면 걸린 시간(초)이 나오고, *1000으로 밀리초(ms) 단위로 바꿈
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
                # 함수 하나 실행할 때마다 이 기록을 deque에 추가 — 1000개 넘으면 오래된 것부터 자동 삭제됨

        return wrapper

    return decorator
    # trace(name=..., metadata=...)를 호출하면 decorator 함수가 반환되고,
    # 그 decorator에 실제 함수를 넣으면(@trace("이름")\ndef 함수(): ...) wrapper가 최종적으로 그 자리를 대체함


def langfuse_callbacks() -> list:
    """LangGraph invoke에 주입할 Langfuse 콜백 목록.

    LANGFUSE_PUBLIC_KEY가 있으면 LangChain CallbackHandler 1개를 반환해
    그래프 전체(노드·LLM 호출)가 자동 트레이싱된다. 키가 없으면 빈 목록을 반환해
    no-op으로 동작한다(핸들러를 만들지 않아 인증 경고도 남기지 않는다).
    """
    # 이 함수가 supervisor.py의 run_supervisor(), run_analysis()에서 이미 봤던 그 함수 —
    # graph.stream(initial, config, ...)의 config 안에 "callbacks": langfuse_callbacks()로 들어가던 것
    if not os.getenv("LANGFUSE_PUBLIC_KEY"):
        return []
        # 환경변수(키)가 아예 없으면, 콜백 객체를 만들려는 시도조차 안 하고 빈 리스트를 바로 반환.
        # "만들었다가 실패하는" 게 아니라 "애초에 시도를 안 하는" 게 인증 경고 로그가 안 남는 이유.
    try:
        from langfuse.langchain import CallbackHandler
        return [CallbackHandler()]
    except Exception:
        return []
        # 키는 있는데 라이브러리 버전 문제 등으로 CallbackHandler 생성이 실패해도,
        # 프로그램이 죽지 않고 그냥 트레이싱 없이 진행되게 조용히 빈 리스트로 넘어감


def flush() -> None:
    """Langfuse 클라이언트의 비동기 큐를 즉시 전송한다. 키 없으면 no-op."""
    # 왜 필요한가: Langfuse로 보내는 기록은 보통 "비동기"(백그라운드에서 조금씩) 전송됨.
    # 그런데 프로그램이 곧 종료될 상황(예: 짧은 스크립트, 배치 작업 끝)이면, 다 보내기 전에
    # 프로그램이 꺼져서 마지막 기록들이 유실될 수 있음. flush()는 "지금 쌓인 거 다 지금 당장 보내라"는 명령.
    if not os.getenv("LANGFUSE_PUBLIC_KEY"):
        return
    try:
        client = get_client()
        client.flush()
    except Exception:
        pass
        # 전송 실패해도(네트워크 문제 등) 조용히 넘어감 — 트레이싱은 부가 기능이라 이것 때문에
        # 프로그램 전체가 에러로 멈추면 안 된다는 원칙


def get_local_records() -> list[LocalTraceRecord]:
    """메모리에 쌓인 로컬 트레이스 레코드를 반환한다."""
    return list(_local_records)
    # deque를 그대로 반환하지 않고 list()로 감싸서 반환 — 호출한 쪽이 이 리스트를 마음대로
    # 수정해도 원본 _local_records(진짜 저장소)에는 영향이 안 가게 하려는 안전한 복사


def clear_local_records() -> None:
    """로컬 레코드를 초기화한다 (테스트용)."""
    _local_records.clear()
    # 테스트할 때 "이전 테스트의 기록이 남아서 이번 테스트 결과가 헷갈리는" 상황을 막기 위한 초기화 함수
