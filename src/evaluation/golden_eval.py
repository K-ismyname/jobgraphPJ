# 갭 분석의 end-task 정확도 측정 — 골든셋 기반 precision / recall / F1
#
# 왜 이 파일이 필요한가: RAGAS Faithfulness는 "생성된 문장이 근거 텍스트에 있는가"만 잰다.
# 즉 에이전트가 근거를 성실히 인용하기만 하면 높은 점수가 나온다 — **그 갭 목록 자체가
# 틀렸어도** 말이다. 이 시스템의 실제 가치는 "부족한 스킬을 정확히 짚어주는 것"인데,
# 그 정확도는 지금까지 어떤 지표로도 측정되지 않았다.
#
# critic도 이걸 못 잡는다. critic은 gap_result를 consensus와 대조할 뿐이라 '내부 일관성'만
# 검사하고 '현실과의 일치'는 보지 못한다. 시스템 전체가 같은 방향으로 틀리면 아무도 모른다.
#
# 측정 방법:
#   정답(golden) = 사람이 라벨링한 직군별 핵심 스킬 - 지원자 보유 스킬
#   예측(pred)   = 에이전트가 내놓은 missing_required
#   precision = |정답 ∩ 예측| / |예측|   → "지목한 것 중 진짜 부족한 게 얼마나 되나" (오탐 억제)
#   recall    = |정답 ∩ 예측| / |정답|   → "진짜 부족한 것 중 얼마나 찾아냈나"   (누락 억제)
#
# precision이 낮으면 사용자가 필요 없는 공부를 하게 되고, recall이 낮으면 정작 필요한 걸 놓친다.
# 둘 다 봐야 하며, F1은 그 조화평균이다.

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from src.extraction.normalizer import normalize_skill

_GOLDEN_PATH = Path(__file__).resolve().parents[2] / "data" / "golden" / "job_family_core_skills.json"


def load_golden(path: Path | None = None) -> dict[str, dict]:
    """골든셋을 읽어 {직군: {"core": [...], "excluded": {...}}} 형태로 반환한다 (_meta 제외)."""
    p = path or _GOLDEN_PATH
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    return {k: v for k, v in data.items() if not k.startswith("_")}


@dataclass
class CaseScore:
    """테스트 케이스 하나(이력서 × 직군)의 채점 결과."""
    case_id: str
    job_family: str
    resume_skills: list[str]
    expected: set[str]      # 정답 — 이 사람이 실제로 갖춰야 하는데 없는 스킬
    predicted: set[str]     # 예측 — 에이전트가 부족하다고 지목한 스킬
    error: str | None = None

    @property
    def hit(self) -> set[str]:
        return self.expected & self.predicted        # 맞게 지목한 것

    @property
    def false_alarm(self) -> set[str]:
        return self.predicted - self.expected        # 필요 없는데 지목한 것 (오탐)

    @property
    def missed(self) -> set[str]:
        return self.expected - self.predicted        # 필요한데 놓친 것 (누락)

    @property
    def precision(self) -> float:
        # 예측이 없으면 오탐도 없다 — 1.0(완벽)이 맞다. 정답도 없는데 아무것도 안 짚었다면 옳은 판단이다.
        return len(self.hit) / len(self.predicted) if self.predicted else 1.0

    @property
    def recall(self) -> float | None:
        """정답이 빈 집합(부족한 스킬이 없는 완벽한 지원자)이면 recall은 정의되지 않는다.

        0.0으로 세면 "다 갖춘 사람"이 평균을 끌어내려 지표가 왜곡된다 — 놓칠 것이 없었으므로
        누락률을 논할 수 없다. None을 반환하고 평균에서 제외한다.
        """
        if not self.expected:
            return None
        return len(self.hit) / len(self.expected)

    @property
    def f1(self) -> float | None:
        p, r = self.precision, self.recall
        if r is None:
            return None
        return 2 * p * r / (p + r) if (p + r) else 0.0


@dataclass
class GoldenReport:
    cases: list[CaseScore] = field(default_factory=list)
    error: str | None = None

    def _mean(self, attr: str) -> float:
        """None(정의되지 않은 케이스)은 평균에서 제외한다."""
        vals = [getattr(c, attr) for c in self.cases if not c.error]
        vals = [v for v in vals if v is not None]
        if not vals:
            return 0.0
        return round(sum(vals) / len(vals), 3)

    def summary(self) -> str:
        scored = [c for c in self.cases if not c.error]
        n_recall = len([c for c in scored if c.recall is not None])
        lines = [
            f"케이스 {len(scored)}개 채점 (실패 {len(self.cases) - len(scored)}개)",
            f"  Precision : {self._mean('precision'):.3f}   (지목한 것 중 진짜 부족한 비율 — 오탐이 적을수록 높음)",
            f"  Recall    : {self._mean('recall'):.3f}   (진짜 부족한 것 중 찾아낸 비율 — 누락이 적을수록 높음, {n_recall}개 케이스)",
            f"  F1        : {self._mean('f1'):.3f}",
        ]
        return "\n".join(lines)


def expected_missing(job_family: str, resume_skills: list[str], golden: dict) -> set[str]:
    """정답 계산 — 그 직군의 핵심 스킬 중 보유하지 않은 것.

    라벨링은 직군별 core 목록 하나만 하면 되고, 케이스별 정답은 여기서 자동 도출된다.
    """
    entry = golden.get(job_family)
    if not entry:
        raise KeyError(f"골든셋에 없는 직군: {job_family}")
    core = {normalize_skill(s) for s in entry["core"]}
    held = {normalize_skill(s) for s in resume_skills}
    return core - held


def score_case(
    case: dict, graph, golden: dict, neo4j=None,
) -> CaseScore:
    """케이스 하나에 대해 실제 에이전트를 돌리고 정답과 대조한다."""
    from src.agent.supervisor import run_analysis

    job_family = case["job_family"]
    resume_skills = case["resume_skills"]
    expected = expected_missing(job_family, resume_skills, golden)

    try:
        final_report = run_analysis(
            graph,
            job_title=job_family,
            owner=case.get("owner", case["case_id"]),
            portfolio_skills=resume_skills,
        )
    except Exception as e:
        return CaseScore(case["case_id"], job_family, resume_skills, expected, set(), error=str(e))

    if not final_report:
        return CaseScore(case["case_id"], job_family, resume_skills, expected, set(),
                         error="에이전트가 리포트를 반환하지 않음")

    predicted: set[str] = set()
    for item in final_report.get("missing_required") or []:
        name = item.get("skill") if isinstance(item, dict) else str(item)
        if name:
            predicted.add(normalize_skill(name))

    return CaseScore(case["case_id"], job_family, resume_skills, expected, predicted)


def run_golden_eval(cases: list[dict], graph, neo4j=None) -> GoldenReport:
    """골든셋 케이스 전체를 채점한다."""
    if not os.getenv("OPENAI_API_KEY"):
        return GoldenReport(error="OPENAI_API_KEY 미설정")
    try:
        golden = load_golden()
    except FileNotFoundError:
        return GoldenReport(error=f"골든셋 파일 없음: {_GOLDEN_PATH}")

    report = GoldenReport()
    for case in cases:
        print(f"  채점 중: {case['case_id']} ({case['job_family']})")
        report.cases.append(score_case(case, graph, golden, neo4j))
    return report


# 테스트 케이스 — 이력서(보유 스킬) × 직군. 정답은 골든셋 core에서 자동 도출된다.
# 실제 이력서 대신 "전형적인 지원자 프로필"을 손으로 구성했다. 진짜 이력서 PDF로 바꾸면
# 파싱 오류까지 포함한 end-to-end 정확도를 잴 수 있다 (다음 단계).
DEFAULT_CASES: list[dict] = [
    {"case_id": "ai_junior", "job_family": "AI/LLM Engineer",
     "resume_skills": ["Python", "Docker", "FastAPI"]},
    {"case_id": "ai_mid", "job_family": "AI/LLM Engineer",
     "resume_skills": ["Python", "PyTorch", "Machine Learning", "Docker", "AI"]},
    {"case_id": "fe_junior", "job_family": "Frontend Engineer",
     "resume_skills": ["JavaScript", "HTML", "CSS"]},
    {"case_id": "fe_mid", "job_family": "Frontend Engineer",
     "resume_skills": ["React", "TypeScript", "JavaScript", "CSS", "HTML"]},
    {"case_id": "de_junior", "job_family": "Data Engineer",
     "resume_skills": ["Python", "SQL"]},
    {"case_id": "da_junior", "job_family": "Data Analyst",
     "resume_skills": ["SQL", "Excel"]},
    {"case_id": "devops_mid", "job_family": "DevOps/SRE",
     "resume_skills": ["Docker", "Kubernetes", "Python"]},
    {"case_id": "ml_mid", "job_family": "ML Engineer",
     "resume_skills": ["Python", "Machine Learning", "PyTorch"]},
]


if __name__ == "__main__":
    from openai import OpenAI
    from src.storage.neo4j_client import Neo4jClient
    from src.agent.supervisor import create_supervisor_graph

    neo4j = Neo4jClient()
    openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY")) if os.getenv("OPENAI_API_KEY") else None
    graph = create_supervisor_graph(neo4j, openai_client)

    print("=== 갭 분석 end-task 정확도 (골든셋 기반) ===\n")
    report = run_golden_eval(DEFAULT_CASES, graph, neo4j=neo4j)

    if report.error:
        print(f"오류: {report.error}")
    else:
        print("\n" + report.summary())
        print("\n[케이스별]")
        for c in report.cases:
            if c.error:
                print(f"  [{c.case_id}] 실패: {c.error}")
                continue
            r_txt = "N/A " if c.recall is None else f"{c.recall:.2f}"
            f_txt = "N/A " if c.f1 is None else f"{c.f1:.2f}"
            print(f"\n  [{c.case_id}] {c.job_family}  P={c.precision:.2f} R={r_txt} F1={f_txt}")
            print(f"     보유   : {', '.join(c.resume_skills)}")
            if not c.expected:
                print("     (핵심 스킬을 모두 보유 — 부족한 것이 없어야 정답)")
            if c.hit:
                print(f"     정확   : {', '.join(sorted(c.hit))}")
            if c.false_alarm:
                print(f"     오탐   : {', '.join(sorted(c.false_alarm))}   ← 필요 없는데 지목")
            if c.missed:
                print(f"     누락   : {', '.join(sorted(c.missed))}   ← 필요한데 못 찾음")

        print("\n해석: Precision이 낮으면 사용자가 필요 없는 공부를 하게 되고,")
        print("      Recall이 낮으면 정작 필요한 스킬을 놓친다.")

    neo4j.close()
