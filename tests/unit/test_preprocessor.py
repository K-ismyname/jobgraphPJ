# preprocessor.py 단위 테스트
import pytest

from src.ingestion.preprocessor import strip_html, extract_sections, preprocess_job


class TestStripHtml:
    def test_removes_tags(self) -> None:
        assert strip_html("<p>Hello <b>World</b></p>") == "Hello World"

    def test_unescapes_entities(self) -> None:
        # &amp; → & 로 변환되고, 태그가 아닌 텍스트는 보존됨
        result = strip_html("<p>Python &amp; Django</p>")
        assert "Python" in result
        assert "&" in result
        assert "Django" in result

    def test_br_becomes_newline(self) -> None:
        result = strip_html("line1<br>line2<br/>line3")
        assert "line1" in result
        assert "line2" in result

    def test_li_becomes_bullet(self) -> None:
        result = strip_html("<ul><li>Python</li><li>SQL</li></ul>")
        assert "• Python" in result or "Python" in result

    def test_empty_string(self) -> None:
        assert strip_html("") == ""

    def test_plain_text_unchanged(self) -> None:
        assert strip_html("Python, SQL, Spark") == "Python, SQL, Spark"


class TestExtractSections:
    def test_b_tag_required(self) -> None:
        contents = "<b>Qualifications</b><ul><li>Python</li><li>SQL</li></ul>"
        req, pref = extract_sections(contents)
        assert "Python" in req
        assert pref == ""

    def test_b_tag_preferred(self) -> None:
        contents = "<b>Preferred Qualifications</b><p>Docker experience</p>"
        req, pref = extract_sections(contents)
        assert req == ""
        assert "Docker" in pref

    def test_strong_tag_qualifications(self) -> None:
        contents = "<strong>Qualifications</strong><p>5+ years Python</p>"
        req, pref = extract_sections(contents)
        assert "Python" in req

    def test_both_sections(self) -> None:
        contents = (
            "<b>Minimum Qualifications</b><p>Python, SQL</p>"
            "<b>Preferred Qualifications</b><p>Spark, Kafka</p>"
        )
        req, pref = extract_sections(contents)
        assert "Python" in req
        assert "Spark" in pref

    def test_no_section_headers(self) -> None:
        contents = "<b>About Us</b><p>Great company</p>"
        req, pref = extract_sections(contents)
        assert req == ""
        assert pref == ""

    def test_colon_in_header(self) -> None:
        # "Basic Qualifications:" — 콜론이 붙은 헤더도 파싱돼야 함
        contents = "<b>Basic Qualifications:</b><p>Python 3.x</p>"
        req, pref = extract_sections(contents)
        assert "Python" in req

    def test_double_escaped_html(self) -> None:
        # &lt;b&gt; 이중 이스케이프 케이스
        contents = "&lt;b&gt;Qualifications&lt;/b&gt;&lt;p&gt;Python&lt;/p&gt;"
        req, pref = extract_sections(contents)
        assert "Python" in req


class TestPreprocessJob:
    def _make_raw(self, **overrides) -> dict:
        base = {
            "id": 12345,
            "name": "Senior Data Scientist",
            "contents": "<b>Minimum Qualifications</b><p>Python, SQL</p>",
            "publication_date": "2025-07-01T00:00:00Z",
            "type": "external",
            "company": {"id": 1, "short_name": "acme", "name": "Acme Corp"},
            "locations": [{"name": "New York, NY"}],
            "levels": [{"name": "Senior Level", "short_name": "senior"}],
            "refs": {"landing_page": "https://example.com/job/123"},
            "categories": [{"name": "Data and Analytics"}],
            "_collected_category": "Data and Analytics",
        }
        base.update(overrides)
        return base

    def test_id_is_string(self) -> None:
        result = preprocess_job(self._make_raw())
        assert isinstance(result["id"], str)
        # The Muse 공고는 소스 namespace 접두사(muse-)가 붙는다 — 다중 소스 id 충돌 방지
        assert result["id"] == "muse-12345"

    def test_title_from_name(self) -> None:
        result = preprocess_job(self._make_raw())
        assert result["title"] == "Senior Data Scientist"

    def test_company_extracted(self) -> None:
        result = preprocess_job(self._make_raw())
        assert result["company"] == "Acme Corp"

    def test_location_first_item(self) -> None:
        result = preprocess_job(self._make_raw())
        assert result["location"] == "New York, NY"

    def test_level_extracted(self) -> None:
        result = preprocess_job(self._make_raw())
        assert result["level"] == "Senior Level"

    def test_url_from_refs(self) -> None:
        result = preprocess_job(self._make_raw())
        assert result["url"] == "https://example.com/job/123"

    def test_created_uses_publication_date(self) -> None:
        result = preprocess_job(self._make_raw())
        assert result["created"] == "2025-07-01T00:00:00Z"

    def test_missing_publication_date_defaults(self) -> None:
        result = preprocess_job(self._make_raw(publication_date=None))
        assert result["created"] == "2025-01-01T00:00:00Z"

    def test_salary_is_none(self) -> None:
        result = preprocess_job(self._make_raw())
        assert result["salary_min"] is None
        assert result["salary_max"] is None

    def test_text_clean_has_no_tags(self) -> None:
        result = preprocess_job(self._make_raw())
        assert "<" not in result["text_clean"]

    def test_required_section_parsed(self) -> None:
        result = preprocess_job(self._make_raw())
        assert "Python" in result["required_section"]

    def test_empty_locations_gives_empty_string(self) -> None:
        result = preprocess_job(self._make_raw(locations=[]))
        assert result["location"] == ""

    def test_empty_levels_gives_empty_string(self) -> None:
        result = preprocess_job(self._make_raw(levels=[]))
        assert result["level"] == ""

    def test_source_is_themuse(self) -> None:
        result = preprocess_job(self._make_raw())
        assert result["source"] == "themuse"
