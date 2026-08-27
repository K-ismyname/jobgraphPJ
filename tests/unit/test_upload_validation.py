# _read_pdf_upload — 스트리밍 크기 검증 + magic bytes 확인
import asyncio

import pytest
from fastapi import HTTPException

from src.api.routers import portfolio as p


class _FakeUpload:
    def __init__(self, data: bytes, filename: str = "resume.pdf"):
        self._data = data
        self.filename = filename
        self._pos = 0

    async def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            chunk = self._data[self._pos:]
            self._pos = len(self._data)
        else:
            chunk = self._data[self._pos:self._pos + size]
            self._pos += len(chunk)
        return chunk


def test_valid_pdf_returns_content():
    data = b"%PDF-1.7 fake body"
    out = asyncio.run(p._read_pdf_upload(_FakeUpload(data)))
    assert out == data


def test_rejects_non_pdf_extension():
    with pytest.raises(HTTPException) as ei:
        asyncio.run(p._read_pdf_upload(_FakeUpload(b"%PDF", filename="x.txt")))
    assert ei.value.status_code == 415


def test_rejects_wrong_magic_bytes():
    # 확장자는 .pdf지만 내용이 PDF가 아님
    with pytest.raises(HTTPException) as ei:
        asyncio.run(p._read_pdf_upload(_FakeUpload(b"<html>not a pdf</html>")))
    assert ei.value.status_code == 415


def test_rejects_oversize_before_full_read(monkeypatch):
    monkeypatch.setattr(p, "_MAX_PDF_BYTES", 100)   # 작게 잡아 대용량 할당 회피
    big = b"%PDF" + b"0" * 500
    with pytest.raises(HTTPException) as ei:
        asyncio.run(p._read_pdf_upload(_FakeUpload(big)))
    assert ei.value.status_code == 413


def test_upload_resume_hides_pdf_parser_internal_error(monkeypatch):
    def fail_parse(path):
        raise ValueError(f"PDF 파싱 실패: {path} — internal library detail")

    monkeypatch.setattr(p, "extract_pdf_info", fail_parse)
    with pytest.raises(HTTPException) as ei:
        asyncio.run(p.upload_resume(_FakeUpload(b"%PDF-1.7 broken"), uploads={}))

    assert ei.value.status_code == 422
    assert ei.value.detail == "PDF를 처리할 수 없습니다. 파일이 손상되었거나 암호화되었을 수 있습니다."
    assert "internal library detail" not in ei.value.detail
