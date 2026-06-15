# _job_family 직군 판별 — Architect 제거 후 미분류, 기존 직군 보존
from src.ingestion.pipeline import _job_family


def test_architect_removed():
    assert _job_family("Senior Data Architect") is None
    assert _job_family("Solutions Architect") is None
    assert _job_family("TECHNICAL ARCHITECT") is None


def test_known_families_kept():
    assert _job_family("Frontend Engineer") == "Frontend Engineer"
    assert _job_family("Senior Security Engineer") == "Security Engineer"
    assert _job_family("Machine Learning Engineer") == "ML Engineer"
