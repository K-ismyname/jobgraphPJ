# final_report → v3 ReportResponse 매핑 (순수 함수)
from src.api.routers.portfolio import _map_final_report


def test_map_final_report():
    final = {
        "gap": {"match_rate": 0.44, "confidence_level": "high", "advice": "좋음"},
        "verification": {
            "counts": {"Verified": 1, "Corroborated": 0, "Claimed": 1},
            "skills": [
                {"skill": "React", "verification": "Verified", "sources": ["github", "deploy"]},
                {"skill": "Docker", "verification": "Claimed", "sources": ["resume"]},
            ],
        },
        "coaching": {"summary": "요약",
                     "project_suggestions": [{"repo": "me/app", "add_skill": "K8s", "why": "DevOps 실증", "how": "Helm 차트 추가"}],
                     "learning_recommendations": [{"skill": "Helm", "reason": "K8s와 연계"}]},
    }
    r = _map_final_report("r1", "지원자", "Software Engineer", final)
    assert r.status == "done" and r.match_rate == 0.44 and r.confidence_level == "high"
    assert r.verification_counts["Verified"] == 1
    assert [s.skill for s in r.verified_skills] == ["React", "Docker"]
    assert r.coaching_summary == "요약"
    assert r.project_suggestions[0].add_skill == "K8s"
    assert r.learning_recommendations[0].skill == "Helm"


def test_map_final_report_tolerates_missing_fields():
    r = _map_final_report("r1", "x", "Software Engineer", {})
    assert r.status == "done" and r.match_rate == 0.0
    assert r.verified_skills == [] and r.project_suggestions == [] and r.learning_recommendations == []


def test_map_final_report_sanitizes_bad_coaching_type():
    # LLM이 strength/gap 밖 type을 내도 리포트가 죽지 않고 strength로 정규화
    final = {
        "gap": {"match_rate": 0.5},
        "verification": {"counts": {}, "skills": []},
        "coaching": {"interview_coaching": [
            {"type": "weakness", "title": "T", "coaching": "C"},   # 잘못된 type
            {"type": "gap", "title": "T2", "coaching": "C2"},
        ]},
    }
    r = _map_final_report("r1", "x", "Software Engineer", final)
    assert r.status == "done"
    assert [c.type for c in r.interview_coaching] == ["strength", "gap"]


def test_map_final_report_passes_trace():
    from src.api.routers.portfolio import _map_final_report

    final = {
        "gap": {"match_rate": 0.5, "confidence_level": "medium"},
        "verification": {"counts": {}, "skills": []},
        "coaching": {"summary": "s", "project_suggestions": [], "learning_recommendations": []},
        "trace": {"evaluators": [{"source": "resume", "skill_count": 3}]},
    }
    resp = _map_final_report("rid", "owner", "Software Engineer", final)
    assert resp.trace == {"evaluators": [{"source": "resume", "skill_count": 3}]}


def test_map_final_report_passes_capability():
    from src.api.routers.portfolio import _map_final_report
    final = {
        "gap": {"match_rate": 0.5},
        "verification": {"counts": {}, "skills": []},
        "coaching": {"summary": "s", "project_suggestions": [], "learning_recommendations": []},
        "capability_fit": {"job_family": "Software Engineer", "fit": 0.5, "total": 2,
                           "met": [{"skill": "Java", "verification": "Verified"}], "unmet": ["SQL"]},
        "recommended_families": [{"job_family": "Software Engineer", "matched_count": 5, "matched_skills": ["Java", "Spring"]}],
    }
    resp = _map_final_report("rid", "owner", "Software Engineer", final)
    assert resp.capability_fit["fit"] == 0.5
    assert resp.recommended_families[0]["job_family"] == "Software Engineer"


def test_map_final_report_passes_rich_coaching_fields():
    final = {
        "gap": {"match_rate": 0.5},
        "verification": {"counts": {}, "skills": []},
        "coaching": {
            "summary": "s",
            "project_understanding": {
                "one_liner": "me/app는 분석 서비스입니다.",
                "architecture": "FastAPI + LangGraph",
                "data_flow": "PDF → 분석 → 리포트",
                "core_design_choices": ["LangGraph로 분기 제어"],
            },
            "evidence_cards": [{
                "skill": "LangGraph",
                "evidence": "src/agent/supervisor.py",
                "what_it_shows": "그래프 오케스트레이션",
                "interview_angle": "분기와 합류를 설명",
            }],
            "project_roadmap": [{
                "step": "테스트 보강",
                "why": "분석 신뢰도 향상",
                "how": "fixture 기반 회귀 테스트 추가",
            }],
            "portfolio_sentences": ["LangGraph 기반 분석 파이프라인을 구현했습니다."],
        },
    }
    resp = _map_final_report("rid", "owner", "Software Engineer", final)
    assert resp.project_understanding.one_liner.startswith("me/app")
    assert resp.evidence_cards[0].skill == "LangGraph"
    assert resp.project_roadmap[0].step == "테스트 보강"
    assert "LangGraph" in resp.portfolio_sentences[0]
