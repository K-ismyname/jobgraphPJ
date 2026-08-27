from src.api.main import _cleanup_evicted_upload, _cleanup_upload_store


def test_cleanup_evicted_upload_deletes_portfolio_temp_file(tmp_path, monkeypatch):
    monkeypatch.setattr("src.api.main.tempfile.gettempdir", lambda: str(tmp_path))
    pdf = tmp_path / "portfolio.pdf"
    pdf.write_bytes(b"%PDF")

    _cleanup_evicted_upload("pf:123", str(pdf))

    assert not pdf.exists()


def test_cleanup_evicted_upload_ignores_resume_text(tmp_path, monkeypatch):
    monkeypatch.setattr("src.api.main.tempfile.gettempdir", lambda: str(tmp_path))
    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"%PDF")

    _cleanup_evicted_upload("resume-report-id", str(pdf))

    assert pdf.exists()


def test_cleanup_evicted_upload_ignores_paths_outside_temp_dir(tmp_path, monkeypatch):
    tmp_root = tmp_path / "tmp"
    outside = tmp_path / "outside" / "portfolio.pdf"
    tmp_root.mkdir()
    outside.parent.mkdir()
    outside.write_bytes(b"%PDF")
    monkeypatch.setattr("src.api.main.tempfile.gettempdir", lambda: str(tmp_root))

    _cleanup_evicted_upload("pf:123", str(outside))

    assert outside.exists()


def test_cleanup_upload_store_deletes_remaining_portfolio_files(tmp_path, monkeypatch):
    monkeypatch.setattr("src.api.main.tempfile.gettempdir", lambda: str(tmp_path))
    portfolio = tmp_path / "portfolio.pdf"
    portfolio.write_bytes(b"%PDF")
    uploads = {"resume-id": "resume text", "pf:123": str(portfolio)}

    _cleanup_upload_store(uploads)

    assert uploads == {}
    assert not portfolio.exists()
