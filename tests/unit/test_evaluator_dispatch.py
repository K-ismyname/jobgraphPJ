# 디스패처 — 입력에 있는 소스의 평가자만 Send
from src.agent.supervisor import evaluator_dispatch


def test_resume_only():
    sends = evaluator_dispatch({"resume_skills": ["Python"], "github_url": None,
                                "pdf_path": None, "resume_text": None})
    assert sorted(s.node for s in sends) == ["resume_eval"]


def test_resume_and_github():
    sends = evaluator_dispatch({"resume_skills": ["Python"], "github_url": "https://github.com/x",
                                "pdf_path": None, "resume_text": None})
    assert sorted(s.node for s in sends) == ["github_eval", "resume_eval"]


def test_empty_defaults_resume():
    sends = evaluator_dispatch({"resume_skills": [], "github_url": None,
                                "pdf_path": None, "resume_text": None})
    assert [s.node for s in sends] == ["resume_eval"]


def test_portfolio_path_dispatches_portfolio():
    sends = evaluator_dispatch({"resume_skills": [], "github_url": None,
                                "pdf_path": None, "resume_text": None,
                                "portfolio_path": "p.pdf"})
    assert "portfolio_eval" in [s.node for s in sends]


def test_deploy_url_dispatches_deploy():
    sends = evaluator_dispatch({"resume_skills": [], "github_url": None,
                                "pdf_path": None, "resume_text": None,
                                "portfolio_path": None, "deploy_url": "https://x.com"})
    assert "deploy_eval" in [s.node for s in sends]
