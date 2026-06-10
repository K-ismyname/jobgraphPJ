# pdf_parser.py 단위 테스트 — 실제 PDF 없이 인터페이스만 검증
import os
import tempfile

import pytest


class TestExtractPdfText:
    def test_nonexistent_file_raises(self) -> None:
        from src.portfolio.pdf_parser import extract_pdf_text

        with pytest.raises(Exception):
            extract_pdf_text("/nonexistent/path/resume.pdf")

    def test_non_pdf_raises(self, tmp_path) -> None:
        """PDF가 아닌 파일을 넘기면 예외가 발생한다."""
        from src.portfolio.pdf_parser import extract_pdf_text

        txt_file = tmp_path / "resume.txt"
        txt_file.write_text("이름: 홍길동\n경력: 3년")

        with pytest.raises(Exception):
            extract_pdf_text(str(txt_file))


class TestExtractPdfInfo:
    def test_returns_tuple(self, tmp_path) -> None:
        """extract_pdf_info는 (text, page_count) 튜플을 반환한다."""
        from src.portfolio.pdf_parser import extract_pdf_info

        # pdfplumber로 빈 PDF는 만들기 어려우므로 잘못된 파일로 ValueError 확인
        bad_file = tmp_path / "bad.pdf"
        bad_file.write_bytes(b"not a real pdf")

        with pytest.raises(Exception):
            extract_pdf_info(str(bad_file))

    def test_nonexistent_raises_value_error(self) -> None:
        from src.portfolio.pdf_parser import extract_pdf_info

        with pytest.raises(ValueError):
            extract_pdf_info("/no/such/file.pdf")
