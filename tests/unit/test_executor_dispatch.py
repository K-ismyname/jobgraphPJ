# Executor 디스패치가 plan의 병렬 가능 step만 Send로 펼치는지 검증
from src.agent.supervisor import executor_dispatch


def _state(steps):
    return {"plan": {"steps": steps, "reason": "x"}}


def test_dispatches_parallel_agents_only():
    steps = [
        {"agent": "profile", "goal": "a"},
        {"agent": "retrieval", "goal": "b"},
        {"agent": "market", "goal": "c"},
        {"agent": "gap", "goal": "d"},     # gap은 병렬 그룹에서 제외(의존성)
    ]
    sends = executor_dispatch(_state(steps))
    targets = sorted(s.node for s in sends)
    assert targets == ["market", "profile", "retrieval"]


def test_skips_profile_when_absent():
    steps = [
        {"agent": "retrieval", "goal": "b"},
        {"agent": "market", "goal": "c"},
        {"agent": "gap", "goal": "d"},
    ]
    sends = executor_dispatch(_state(steps))
    targets = sorted(s.node for s in sends)
    assert targets == ["market", "retrieval"]
