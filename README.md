# Job Skill Analyzer — 다중 소스 교차검증 Agentic RAG

> 채용공고를 수집·분석하고, **이력서·포트폴리오·GitHub·배포 URL** 을 종합해
> 직무 **적합도**와 그 판단의 **신뢰도**를 분리해서 알려주는 Agentic RAG 시스템.

**타겟 직무:** AI/LLM 애플리케이션 엔지니어 (Agentic RAG)

---

## 무엇을 푸는가

이력서 한 장만으로 "이 사람이 이 직무에 맞나"를 판단하면 두 가지가 섞여 망가진다.

1. **적합도** — 직무가 요구하는 스킬을 가졌나?
2. **신뢰도** — 그 스킬이 *실제로 검증됐나*, 아니면 *이력서에 적힌 주장*일 뿐인가?

이력서는 "할 줄 안다"는 **주장**이고, GitHub 코드·배포된 서비스는 **실증**이다. 둘을 같은 무게로 다루면 "다 잘하는 사람"처럼 부풀거나, 반대로 축소된다. 이 프로젝트의 핵심은 **이 두 축을 분리**하고, **여러 독립 소스의 교차검증**으로 신뢰도를 *결정적으로* 산출하는 것이다.

> "왜 이 답을 신뢰할 수 있는가?" 에 답할 수 있는 구조 — 이게 설계의 중심이다.

---

## 핵심 설계 1 — 적합도 ⊥ 신뢰도, 두 축 분리

최종 리포트는 한 점수가 아니라 **두 축**으로 나온다.

| 축 | 무엇 | 어떻게 산출 |
|----|------|-------------|
| **적합도** `match_rate` | 직무 요구 스킬 중 몇 %를 보유했나 | 결정적 계산 (보유∩요구 / 요구) |
| **신뢰도** `confidence` + `verification` | 그 보유가 얼마나 검증됐나 | 합의 노드가 검증 등급을 결정적으로 판정 |

두 축이 직교하므로 "스킬은 맞는데 근거가 약함"과 "근거는 확실한데 스킬이 부족함"을 구별할 수 있다.

---

## 핵심 설계 2 — 다중 소스 교차검증 (멀티에이전트가 *기능에서* 발생)

각 소스는 **서로 다른 modality**라 한 LLM에 합칠 수 없다. 그래서 소스마다 독립 평가자를 둔다 — "억지 멀티에이전트"가 아니라 **기능이 요구하는 멀티에이전트**.

| 평가자 | 입력 | modality | 보는 것 | 검증 기여 |
|--------|------|----------|---------|-----------|
| **이력서** | PDF/텍스트 | 텍스트 (LLM 추출) | 경력·스킬 (주장) | Claimed |
| **포트폴리오** | PDF | 멀티모달 (텍스트+vision) | 프로젝트 규모·성과 | Claimed |
| **GitHub** | repo URL | 코드 (언어·README·의존성) | 코드로 실재 | **Verified** |
| **배포 URL** | URL | 웹 (HTML+헤더) | 작동 실증·배포 경험 | **Verified** |

**합의 노드("서기")** 가 이들을 받아 스킬별 검증 등급을 *결정적으로* 판정한다 — 판단이 아니라 사실 종합이라 임의성이 없다.

```
Verified     : GitHub 코드 / 배포 등 실증 소스에 근거
Corroborated : 2개 이상 독립 소스가 일치
Claimed      : 1개 소스만 (코드 미확인)
```

"여러 독립 소스가 일치하면 믿을 만하다"는 법정·저널리즘의 원칙. GitHub가 없어도 이력서+포트폴리오 교차검증(Corroborated)으로 차별화된다.

**예시 출력:**
```
React       Verified     [deploy, github, resume]   ← 코드+작동+주장 모두 일치
Python      Corroborated [portfolio, resume]        ← 두 소스 일치
Docker      Claimed      [resume]                   ← 이력서 주장만
```

---

## 아키텍처

LangGraph `StateGraph`. 입력에 있는 소스의 평가자만 병렬 fan-out → 합의 → Gap 적합도 루프 → 검증 → 코칭.

```
START
  └→ (dispatcher: 입력에 있는 소스만 Send)
       ├→ 이력서 평가자 ─┐
       ├→ 포폴 평가자   ─┤
       ├→ GitHub 평가자 ─┤   (병렬)
       └→ 배포 평가자   ─┘
                         ▼
                     합의 (검증 등급 — 결정적)
                         ▼
                     seed_gap → call_model ↔ tools (Gap 적합도 루프, Corrective RAG)
                         ▼
                     synthesizer (적합도+신뢰도 리포트)
                         ▼
                     critic (consensus 대조 — 환각 제거·검증 라벨 교정, 결정적)
                         ▼
                     coach (이력서 개선 제안) → 최종 리포트
```

**최종 리포트:**
```python
{
  "gap":          { match_rate(적합도), confidence_level(신뢰도), advice, skills[...] },
  "verification": { counts: {Verified, Corroborated, Claimed},
                    skills: [{skill, verification, sources}] },   # 신뢰도 축 상세
  "coaching":     { summary, suggestions }
}
```

---

## 설계 의사결정 — "왜 이렇게 만들었나"

신뢰를 내세우는 시스템이라, **신뢰해야 할 값은 LLM이 추측하지 않고 코드가 계산**한다.

- **신뢰도·적합도 = 결정적.** `confidence_level`은 합의 검증 분포에서, `match_rate`는 도구 결과에서 코드로 산출. LLM이 숫자를 지어내지 못하게 덮어쓴다. (LLM의 임의 `fit_score`는 제거)
- **Critic = 결정적 검증기.** LLM-as-judge가 아니라, 리포트의 보유 스킬을 합의(사실)와 대조해 **합의에 없는 환각을 제거**하고 **부풀린 검증 라벨을 교정**한다.
- **합의 노드 = 판단 없는 "서기".** 검증 등급 판정 + 증거 통합만 — 적합도 판단은 Gap에 위임해 합의에 임의성이 없다.
- **직무 무관 범용.** 후보 스킬을 직군별 Neo4j 어휘로 매칭. 10개 직군(Software/Data/AI·LLM/DevOps/Frontend/Security/…) 어디든 평가.
- **포트폴리오 하이브리드.** 텍스트가 추출되는 페이지는 텍스트로(저렴), 이미지/벡터-outline 페이지는 vision으로(필요할 때만). 전체 커버 + 비용 적응형.
- **소스는 모두 선택적.** 있는 소스만 평가 — 이력서만 줘도 적합도는 나오고, 소스가 많을수록 신뢰도가 오른다.

---

## 기술 스택

| 역할 | 기술 | 비고 |
|------|------|------|
| 에이전트 | **LangGraph** (StateGraph, Send) | 조건 분기·병렬 fan-out·루프 |
| LLM | **OpenAI** gpt-4o-mini(기본)/gpt-4o(복잡), vision | 단일 공급자 |
| 검색 | **Chroma + Contextual Hybrid** (BM25 + Dense + CrossEncoder rerank) | |
| 그래프 DB | **Neo4j Aura** | 직무–스킬 관계, 직군별 어휘 |
| 데이터 | Adzuna API | 채용공고 수집 |
| PDF | pdfplumber(텍스트) + PyMuPDF(이미지 렌더) | |
| 서빙 | FastAPI + Docker | |

---

## 실행

```bash
pip install -r requirements.txt
cp .env.example .env        # OPENAI_API_KEY, NEO4J_*, ADZUNA_* 등

# 데이터 수집 (Adzuna → Neo4j)
python -m src.ingestion.adzuna_client

# 에이전트 실행
python -m src.agent.supervisor

# 테스트
pytest tests/unit/
```

`run_supervisor(graph, job_family, owner, pdf_path=, portfolio_path=, github_url=, deploy_url=, neo4j=)` — 가진 소스만 넘기면 된다. Adzuna·Neo4j·GitHub 등 데이터 키가 없으면 mock/fallback으로 동작하고, LLM 키(`OPENAI_API_KEY`)는 에이전트 실행에 필요하다.

---

## 정직한 한계

- **배포 평가자**: 프론트·작동은 보이나 백엔드·AI 기술은 외부에서 안 보임 → 주 가치는 "작동 실증". GitHub 코드와 교차할 때 강한 검증.
- **포트폴리오 vision**: 페이지별 호출이라 비용·변동성 존재. 이미지 페이지 상한(기본 25장).
- **4개 소스를 vision 포함 한 프로세스로 동시 실행**은 리소스 부담 — 소스 조합/단독 실행 권장.

---

## 설계·구현 문서

- 설계: [`docs/superpowers/specs/2026-06-11-agent-v3-fit-assessment-design.md`](docs/superpowers/specs/2026-06-11-agent-v3-fit-assessment-design.md)
- 진행 기록: [`progress.md`](progress.md)
- 구현 계획: [`docs/superpowers/plans/`](docs/superpowers/plans/)
