# observe.html이 데이터 탭 제거 후 워크플로우 단독 구조인지 검사하는 회귀 가드
from pathlib import Path

HTML = (Path(__file__).resolve().parents[2] / "web" / "observe.html").read_text(encoding="utf-8")


def test_workflow_panel_present():
    assert 'id="workflow"' in HTML


def test_data_tab_removed():
    assert 'id="tab-data"' not in HTML
    assert 'id="panel-data"' not in HTML
    assert 'class="tabs"' not in HTML
