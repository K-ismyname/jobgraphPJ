# v3 API 스키마 검증
from src.api.schemas import AnalyzeRequest, ReportResponse, VerificationItem, ProjectSuggestion, LearningRecommendation


def test_analyze_request_v3_fields():
    req = AnalyzeRequest(report_id="r1", job_family="Software Engineer",
                         github_urls=["https://github.com/x/y"], deploy_urls=["https://x.com"])
    assert req.job_family == "Software Engineer"
    assert req.github_urls == ["https://github.com/x/y"] and req.deploy_urls == ["https://x.com"]
    req2 = AnalyzeRequest(report_id="r1", job_family="Software Engineer")
    assert req2.github_urls == [] and req2.deploy_urls == []


def test_report_response_v3_shape():
    r = ReportResponse(
        report_id="r1", status="done", owner="x", job_family="Software Engineer",
        match_rate=0.44, confidence_level="high", advice="좋음",
        verification_counts={"Verified": 2, "Corroborated": 0, "Claimed": 1},
        verified_skills=[VerificationItem(skill="React", verification="Verified", sources=["github"])],
        coaching_summary="요약",
        project_suggestions=[ProjectSuggestion(repo="me/app", add_skill="K8s", why="...", how="...")],
        learning_recommendations=[LearningRecommendation(skill="Helm", reason="K8s와 연계")],
    )
    assert r.match_rate == 0.44
    assert r.verified_skills[0].skill == "React"
    assert r.verification_counts["Verified"] == 2
