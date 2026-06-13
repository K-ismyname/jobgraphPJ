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
        "coaching": {"summary": "요약", "suggestions": [
            {"target_section": "경력", "missing_skill": "K8s", "rewritten_text": "...",
             "expected_impact": "...", "priority": "high", "verified": True},
        ]},
    }
    r = _map_final_report("r1", "지원자", "Software Engineer", final)
    assert r.status == "done" and r.match_rate == 0.44 and r.confidence_level == "high"
    assert r.verification_counts["Verified"] == 1
    assert [s.skill for s in r.verified_skills] == ["React", "Docker"]
    assert r.coaching_summary == "요약"
    assert r.suggestions[0].missing_skill == "K8s"


def test_map_final_report_tolerates_missing_fields():
    r = _map_final_report("r1", "x", "Software Engineer", {})
    assert r.status == "done" and r.match_rate == 0.0
    assert r.verified_skills == [] and r.suggestions == []


def test_map_final_report_passes_trace():
    from src.api.routers.portfolio import _map_final_report

    final = {
        "gap": {"match_rate": 0.5, "confidence_level": "medium"},
        "verification": {"counts": {}, "skills": []},
        "coaching": {"summary": "s", "suggestions": []},
        "trace": {"evaluators": [{"source": "resume", "skill_count": 3}]},
    }
    resp = _map_final_report("rid", "owner", "Software Engineer", final)
    assert resp.trace == {"evaluators": [{"source": "resume", "skill_count": 3}]}


def test_map_final_report_passes_capability():
    from src.api.routers.portfolio import _map_final_report
    final = {
        "gap": {"match_rate": 0.5},
        "verification": {"counts": {}, "skills": []},
        "coaching": {"summary": "s", "suggestions": []},
        "capability_fit": {"job_family": "Software Engineer", "core": ["backend_fw"], "fit": 1.0, "met": ["backend_fw"], "unmet": []},
        "recommended_families": [{"job_family": "Software Engineer", "fit": 1.0, "met": ["backend_fw"], "unmet": []}],
        "capability_evidence": [{"capability": "backend_fw", "tools": [{"skill": "Spring", "verification": "Verified"}]}],
    }
    resp = _map_final_report("rid", "owner", "Software Engineer", final)
    assert resp.capability_fit["fit"] == 1.0
    assert resp.recommended_families[0]["job_family"] == "Software Engineer"
    assert resp.capability_evidence[0]["capability"] == "backend_fw"
