# 이력서 추출기가 앞 4000자 너머의 텍스트도 LLM에 전달하는지 검증
from src.extraction import skill_extractor
from src.extraction.skill_extractor import extract_skills_from_resume


def test_full_text_sent_to_llm(monkeypatch):
    captured = {}

    def fake_chat(client, prompt, max_tokens=1024):
        captured["prompt"] = prompt
        captured["max_tokens"] = max_tokens
        return '{"candidate_name": "X", "sections": []}'

    monkeypatch.setattr(skill_extractor, "_chat", fake_chat)
    # 4000자 이후에 핵심 스킬을 배치
    long_text = "머리말 " + ("A" * 5000) + " Java Spring Redis " + ("B" * 1000)
    extract_skills_from_resume(long_text, client=object())

    assert "Java Spring Redis" in captured["prompt"]   # 잘리지 않고 포함
    assert captured["max_tokens"] >= 4096
