# 코칭 텍스트의 파일 경로 환각 결정적 제거 검증
from src.agent.nodes import scrub_invented_paths

_VALID = {
    "src/extraction/skill_extractor.py",
    "src/api/main.py",
    "requirements.txt",
}


def test_invented_path_drops_project_suggestion():
    # 실제 오탐 사례 재현: 레포에 없는 파일을 지목한 제안 → 제거
    coaching = {"project_suggestions": [
        {"add_skill": "LLM", "why": "성능 향상",
         "how": "src/agent/supervisor.py 파일에서 모델 튜닝 피드백 루프를 추가하세요."},
        {"add_skill": "Docker", "why": "배포 실증", "how": "멀티스테이지 빌드로 이미지를 경량화하세요."},
    ]}
    out = scrub_invented_paths(coaching, _VALID)
    assert [s["add_skill"] for s in out["project_suggestions"]] == ["Docker"]
    assert any("LLM" in r for r in out["scrubbed_paths"])


def test_real_path_mention_kept():
    coaching = {"project_suggestions": [
        {"add_skill": "AI", "why": "정확도",
         "how": "src/extraction/skill_extractor.py의 추출 프롬프트를 개선하세요."},
    ]}
    out = scrub_invented_paths(coaching, _VALID)
    assert len(out["project_suggestions"]) == 1


def test_learning_how_sentence_scrubbed_not_whole_item():
    # learning은 스킬 갭 자체가 결정적 산출이므로 항목은 유지, 지어낸 경로 문장만 제거
    coaching = {"learning_recommendations": [
        {"skill": "Machine Learning", "reason": "직군 요구",
         "how": "기초 모델을 학습하세요. 이를 src/analysis/capability.py 파일에 통합하는 방식으로 실습할 수 있습니다."},
    ]}
    out = scrub_invented_paths(coaching, _VALID)
    rec = out["learning_recommendations"][0]
    assert rec["skill"] == "Machine Learning"          # 항목 유지
    assert "capability.py" not in rec["how"]            # 지어낸 경로 문장 제거
    assert "기초 모델을 학습하세요." in rec["how"]        # 나머지 문장 유지


def test_tech_names_not_false_positive():
    # Node.js 같은 기술명은 경로로 오판하지 않는다
    coaching = {"project_suggestions": [
        {"add_skill": "Node.js", "why": "백엔드", "how": "Node.js와 Vue.js 조합을 검토하세요."},
    ]}
    out = scrub_invented_paths(coaching, _VALID)
    assert len(out["project_suggestions"]) == 1


def test_no_github_all_paths_invented():
    # GitHub 미연동(유효 경로 없음)인데 파일을 지목 → 전부 환각으로 제거
    coaching = {"project_suggestions": [
        {"add_skill": "AI", "why": "x", "how": "app/main.py를 고치세요."},
    ]}
    out = scrub_invented_paths(coaching, set())
    assert out["project_suggestions"] == []


def test_non_dict_coaching_passthrough():
    assert scrub_invented_paths({"raw": "...", "error": "JSON 파싱 실패"}, _VALID)["error"] == "JSON 파싱 실패"
