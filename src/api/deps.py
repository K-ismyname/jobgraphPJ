# FastAPI 의존성 주입 함수 모음
#
# 한 줄 요약: main.py가 app.state에 넣어둔 것들(neo4j, openai, graph 등)을
# 라우터 함수들이 편하게 꺼내 쓸 수 있게 도와주는 작은 헬퍼 함수 모음.

from __future__ import annotations

from collections import OrderedDict
# OrderedDict — 파이썬 3.7+ 이후 일반 dict도 순서를 기억하지만, OrderedDict는
# move_to_end() 같은 "순서를 직접 조작하는" 메서드가 따로 있어서 아래 BoundedDict가 이걸 상속함

from openai import OpenAI
from fastapi import Request
# Request — 브라우저가 보낸 요청 하나하나를 표현하는 객체. 이 안에 app.state(main.py에서 만든 짐칸)도 들어있음

from src.storage.neo4j_client import Neo4jClient


class BoundedDict(OrderedDict):
    """삽입 순서로 최대 maxlen개만 유지, 초과 시 가장 오래된 항목 축출.

    데모 서버가 장기 구동될 때 uploads/reports가 무한 증가하는 것을 막는다.
    """
    # class BoundedDict(OrderedDict) → "OrderedDict를 상속받는다"는 뜻. OrderedDict가 원래 할 수 있는
    # 모든 걸 그대로 할 수 있으면서, 여기에 "개수 제한" 기능만 추가로 얹은 것.
    # langfuse_tracer.py의 deque(maxlen=1000)이랑 목적은 똑같은데, deque는 "리스트"이고
    # 이건 "딕셔너리"(key로 찾아야 하는 데이터)라서 다른 방식으로 구현됨.

    def __init__(self, maxlen: int) -> None:
        super().__init__()
        # super().__init__() → 부모(OrderedDict)의 초기화 코드를 먼저 실행. 이게 있어야
        # 이 객체가 진짜 딕셔너리처럼 제대로 동작함.
        self._maxlen = maxlen
        # 최대 개수를 이 객체 안에 저장해둠 (나중에 __setitem__에서 참조)

    def __setitem__(self, key, value) -> None:
        # __setitem__은 "dict[키] = 값"을 실행할 때 파이썬이 자동으로 호출하는 특수 메서드.
        # 이걸 직접 다시 정의(override)하면, "값을 넣을 때마다" 우리가 원하는 추가 동작을 끼워넣을 수 있음.
        if key in self:
            self.move_to_end(key)
            # 이미 있던 키에 새 값을 넣는 거면, 그 키를 "가장 최근에 쓴 것"으로 순서 맨 뒤로 옮김
        super().__setitem__(key, value)
        # 실제로 값을 넣는 건 부모(OrderedDict)의 원래 동작을 그대로 씀
        while len(self) > self._maxlen:
            self.popitem(last=False)
            # popitem(last=False) → "제일 먼저 들어온"(가장 오래된) 항목을 하나 꺼내서 버림.
            # while문이라 만약 한 번에 여러 개가 넘쳐도 상한을 넘지 않을 때까지 계속 반복해서 지움


def get_neo4j(request: Request) -> Neo4jClient:
    return request.app.state.neo4j
    # request.app.state.neo4j → main.py의 lifespan()이 서버 시작할 때 미리 만들어둔 그 Neo4j 연결


def get_openai(request: Request) -> OpenAI | None:
    return request.app.state.openai
    # 키가 없으면 main.py에서 None으로 저장해뒀으니, 여기도 자연스럽게 None을 반환할 수 있음


def get_uploads(request: Request) -> dict[str, str]:
    """report_id → PDF 텍스트 매핑."""
    return request.app.state.uploads
    # main.py에서 BoundedDict(500)로 만들어둔 그 저장소 — 업로드된 PDF에서 뽑은 텍스트를 담아둠


def get_reports(request: Request) -> dict[str, object]:
    """report_id → ReportResponse 매핑."""
    return request.app.state.reports
    # 마찬가지로 BoundedDict(500) — 완성된 분석 리포트를 담아둠


def get_graph(request: Request):
    """v3 supervisor 그래프 (openai 키 없거나 lifespan 미실행이면 None)."""
    return getattr(request.app.state, "graph", None)
    # 다른 함수들은 request.app.state.xxx로 바로 꺼내는데, 이 함수만 getattr(대상, "이름", 기본값)을 씀.
    # 왜 다르게 짰나: 혹시 app.state에 아직 "graph"라는 속성 자체가 없는 상황(예: 테스트 환경에서
    # lifespan()을 안 거치고 바로 쓸 때)에도, 에러 내지 않고 그냥 None을 반환하게 하려는 더 안전한 방식.
    # (다른 함수들처럼 request.app.state.graph라고 쓰면, 속성 자체가 없을 때 AttributeError가 남)


# ── 이 파일이 FastAPI에서 실제로 쓰이는 방식(의존성 주입) ──────────
# 위 함수들은 라우터 파일에서 이렇게 쓰인다:
#
#   from fastapi import Depends
#   @router.get("/something")
#   def my_endpoint(neo4j: Neo4jClient = Depends(get_neo4j)):
#       ...neo4j.execute_query(...)...
#
# Depends(get_neo4j)라고 써두면, FastAPI가 이 API가 호출될 때마다 자동으로 get_neo4j(request)를
# 실행해서 그 결과를 neo4j 매개변수에 넣어줌. 라우터 함수 코드가 "request.app.state.neo4j"라고
# 매번 길게 안 써도 되고, 테스트할 때도 이 함수만 가짜(mock)로 바꿔치기하기 쉬워지는 장점이 있음.
