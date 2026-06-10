# Critic의 결정적 부분(replan 가드레일, 빈 입력 처리)을 검증
from src.agent.critic import decide_replan


def test_replan_blocked_at_limit():
    # 상한(2) 도달 시 unfaithful이어도 replan 금지
    assert decide_replan(faithful=False, replan_count=2) is False
    assert decide_replan(faithful=False, replan_count=3) is False


def test_replan_allowed_below_limit():
    assert decide_replan(faithful=False, replan_count=0) is True
    assert decide_replan(faithful=False, replan_count=1) is True


def test_no_replan_when_faithful():
    assert decide_replan(faithful=True, replan_count=0) is False
