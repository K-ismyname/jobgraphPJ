# index.html이 app.js 계약(필수 id)과 신규 섹션을 모두 갖는지 검사하는 회귀 가드
from pathlib import Path

import pytest

HTML = (Path(__file__).resolve().parents[2] / "web" / "index.html").read_text(encoding="utf-8")

# app.js가 document.getElementById로 참조하는 id — 하나라도 빠지면 분석 흐름이 깨진다
REQUIRED_IDS = [
    "file", "upload-btn", "upload-msg", "step-upload",
    "job-family", "github-url", "deploy-url", "analyze-btn", "analyze-msg", "step-analyze",
    "progress", "result", "step-result",
]

# 홈페이지 개편으로 추가되는 섹션·앵커
NEW_MARKERS = [
    'class="topnav"', 'id="hero"', 'id="how"', 'id="contact"', 'class="cta"',
]


@pytest.mark.parametrize("anchor_id", REQUIRED_IDS)
def test_required_id_present(anchor_id):
    assert f'id="{anchor_id}"' in HTML, f"app.js가 쓰는 id 누락: {anchor_id}"


@pytest.mark.parametrize("marker", NEW_MARKERS)
def test_new_section_present(marker):
    assert marker in HTML, f"홈페이지 섹션 마커 누락: {marker}"
