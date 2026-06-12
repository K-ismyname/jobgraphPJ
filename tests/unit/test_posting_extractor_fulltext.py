# 채용공고 추출기가 2000/3000자 너머의 텍스트도 LLM에 전달하는지 검증
from src.extraction import skill_extractor
from src.extraction.skill_extractor import extract_skills_from_posting


def test_required_section_not_truncated(monkeypatch):
    captured = {}

    def fake_chat(client, prompt, max_tokens=1024):
        captured["prompt"] = prompt
        captured["max_tokens"] = max_tokens
        return '{"required": [], "preferred": []}'

    monkeypatch.setattr(skill_extractor, "_chat", fake_chat)
    # 2000자 이후에 스킬 배치 (기존 cap이면 잘림)
    job = {"title": "Backend", "required_section": ("A" * 2500) + " Elasticsearch " + ("B" * 200)}
    extract_skills_from_posting(job, client=object())

    assert "Elasticsearch" in captured["prompt"]
    assert captured["max_tokens"] >= 1500


def test_full_text_not_truncated(monkeypatch):
    captured = {}

    def fake_chat(client, prompt, max_tokens=1024):
        captured["prompt"] = prompt
        return '{"required": [], "preferred": []}'

    monkeypatch.setattr(skill_extractor, "_chat", fake_chat)
    # required_section 없음 → full_text 경로, 3000자 이후에 스킬 배치
    job = {"title": "Backend", "text_clean": ("A" * 3500) + " Elasticsearch " + ("B" * 200)}
    extract_skills_from_posting(job, client=object())

    assert "Elasticsearch" in captured["prompt"]
