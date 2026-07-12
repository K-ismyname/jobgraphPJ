# _evidence_snippet — 근거 문장이 실제로 그 스킬을 언급할 때만 반환하는지 검증
from src.agent.tools import _evidence_snippet


def test_returns_sentence_mentioning_skill():
    text = (
        "• 7+ years of software experience\n"
        "• Experience with container systems such as Docker or Kubernetes\n"
        "• Excellent communication skills"
    )
    out = _evidence_snippet("Docker", text)
    assert "Docker" in out
    assert "communication" not in out  # 무관한 문장은 섞이지 않는다


def test_returns_empty_when_skill_absent():
    """스킬을 언급조차 않는 본문은 근거가 아니다 — 빈 문자열이어야 한다.

    예전에는 앞부분 450자를 그대로 돌려줘서, Docker를 한 글자도 언급하지 않는
    NVIDIA 공고 본문이 "Docker가 필요한 근거"로 사용자에게 제시됐다.
    """
    text = "NVIDIA's Enterprise Product Group is seeking a GenAI Product Integration Lead."
    assert _evidence_snippet("Docker", text) == ""


def test_matches_alias():
    # k8s → Kubernetes 별칭도 근거로 인정된다
    text = "熟悉容器化（Docker/K8s）及自动化运维体系。"
    assert _evidence_snippet("Kubernetes", text) != ""


def test_empty_text_returns_empty():
    assert _evidence_snippet("Docker", "") == ""
    assert _evidence_snippet("Docker", None) == ""
