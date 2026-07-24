# 배선 검증 — "정의만 되고 실제 흐름에 연결 안 된 죽은 코드"를 잡는 장치
#
# 왜 이 파일이 필요한가: 이 프로젝트의 반복된 버그 유형이 "함수는 만들었는데 호출부에
# 연결 안 함"이었다. is_noise_skill(노이즈 필터), _evidence_mentions_skill(근거 필터),
# consensus 주입 — 전부 함수는 정확했지만 실제 파이프라인에서 불리지 않아, 단위 테스트는
# 통과하면서도 프로덕션에서는 아무 효과가 없었다.
#
# 일반 단위 테스트는 "함수가 올바른가"만 본다. 이 파일은 "그 함수가 실제로 불리는가"를 본다.
# 두 종류가 다르다 — 아무리 정확한 필터도 호출되지 않으면 없는 것과 같다.
#
# 주의: "정의됐지만 안 불리는 함수"가 전부 버그인 것은 아니다. 의도적으로 안 쓰는 헬퍼도
# 있다. 그래서 이 검증은 자동 탐지가 아니라 **명시적 등록(_MUST_BE_WIRED)** 방식이다 —
# "이건 반드시 실제 흐름에 연결돼야 한다"를 사람이 프로젝트 지식으로 지정한다. 이 목록은
# 프로젝트마다 다르다.

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1].parent / "src"

# (함수명, 정의 파일 상대경로, 반드시 호출돼야 하는 파일 상대경로들)
# — 이 프로젝트에서 "만들어놓고 배선 안 함" 버그가 실제로 났던 지점들.
_MUST_BE_WIRED = [
    # 노이즈 스킬 필터 — 적재 파이프라인에서 불려야 개념어가 :Skill 노드로 굳지 않는다
    ("is_noise_skill", "extraction/normalizer.py", ["ingestion/pipeline.py"]),
    # 근거-스킬 일치 필터 — 평가에서 무관한 근거를 걸러낸다
    ("_evidence_mentions_skill", "evaluation/ragas_eval.py", ["evaluation/ragas_eval.py"]),
    # 환각 제거 — critic 노드에서 gap_result를 consensus와 대조해야 한다
    ("verify_gap_against_consensus", "agent/critic.py", ["agent/critic.py"]),
    # SSRF 가드 — 사용자 URL을 fetch하는 safe_get이 반드시 이걸 거쳐야 한다
    ("assert_safe_url", "common/url_guard.py", ["common/url_guard.py"]),
    # 배포 평가자는 httpx.get이 아니라 safe_get을 써야 한다 (SSRF 방어)
    ("safe_get", "common/url_guard.py", ["agent/evaluators/deploy_eval.py"]),
]


def _count_calls(func_name: str, file_rel: str) -> int:
    """file_rel 안에서 func_name(...)이 호출되는 횟수 (정의부 def는 제외)."""
    path = _SRC / file_rel
    tree = ast.parse(path.read_text(encoding="utf-8"))
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            # 직접 호출 f(...) 또는 속성 호출 obj.f(...) 둘 다 잡는다
            name = getattr(fn, "id", None) or getattr(fn, "attr", None)
            if name == func_name:
                count += 1
    return count


@pytest.mark.parametrize("func_name,def_file,call_files", _MUST_BE_WIRED,
                         ids=[m[0] for m in _MUST_BE_WIRED])
def test_critical_function_is_wired(func_name, def_file, call_files):
    """등록된 핵심 함수가 지정된 파일에서 실제로 호출되는지 검증한다.

    실패하면 = 누군가 배선을 빼먹었거나 호출부를 지웠다는 뜻이다.
    (함수 자체가 맞는지는 다른 단위 테스트가 본다. 여기는 '연결'만 본다.)
    """
    assert (_SRC / def_file).exists(), f"{func_name} 정의 파일이 없음: {def_file}"
    for cf in call_files:
        calls = _count_calls(func_name, cf)
        assert calls > 0, (
            f"{func_name}이 {cf}에서 호출되지 않는다 — "
            f"배선이 끊겼다. 정의만 되고 실제 흐름에 연결 안 된 죽은 코드다."
        )


def test_deploy_eval_does_not_bypass_ssrf_guard():
    """deploy_eval이 safe_get을 우회해 httpx.get을 직접 쓰지 않는지 검증한다.

    SSRF 가드는 safe_get 안에 있다. httpx.get을 직접 부르면 가드를 건너뛴다 —
    이 테스트가 그 우회를 막는다.
    """
    src = (_SRC / "agent/evaluators/deploy_eval.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            # httpx.get(...) 형태 탐지
            if getattr(fn, "attr", None) == "get" and getattr(getattr(fn, "value", None), "id", None) == "httpx":
                pytest.fail("deploy_eval이 httpx.get을 직접 호출한다 — safe_get으로 SSRF 가드를 거쳐야 한다.")
