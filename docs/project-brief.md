# JobGraph — 프로젝트 브리프 (LLM 프롬프트용)

> 자소서·이력서·면접 답변 생성 등에 컨텍스트로 넣을 사실 정리. 모든 항목은 실제 구현·검증된 내용.

## 한 줄 정의
채용공고를 수집·분석하고, 이력서·포트폴리오·GitHub·배포 URL을 종합해 **직무 적합도**와 그 판단의 **신뢰도**를 분리해 제공하는 Agentic RAG 시스템.

## 한 줄 정의(영문)
An Agentic RAG system that ingests job postings and cross-verifies a candidate's resume, GitHub, and live deployment to report **fit** and the **trustworthiness** of that judgment as two separate axes.

## 도메인·역할·기간
- 도메인: **HR / 채용**(직무 적합도 분석, 채용공고 데이터)
- 역할: **개인 개발**(기획·설계·구현 전담)
- 기간: 2026.06 ~
- 저장소: https://github.com/K-ismyname/jobgraphPJ

## 풀려는 문제
"이 사람이 이 직무에 맞나"는 두 질문이 섞여 망가진다 — (1) 요구 스킬을 **가졌나(적합도)**, (2) 그게 **검증됐나, 이력서 주장일 뿐인가(신뢰도)**. 기존 도구는 한 점수로 뭉개 "스킬 많은 사람"이 "검증된 사람"처럼 부풀려진다. 이 프로젝트는 두 축을 분리하고, 여러 독립 소스의 교차검증으로 신뢰도를 결정적으로 산출한다.

## 핵심 기능
1. 직군별 채용공고 수집(Adzuna) + LLM 스킬 추출·정규화 → Neo4j 그래프
2. 이력서 PDF 업로드 → 직군 핵심 스킬 대비 **적합도(N/10)** + 역방향 직군 추천
3. 이력서·GitHub·배포를 **교차검증**해 스킬별 **신뢰도 등급**(Verified/Corroborated/Claimed)
4. GitHub 프로젝트를 LLM이 이해해 **"이 repo에 무엇을 더하면 부족 스킬을 실증하나"** 코칭 + 연계 학습 추천
5. 분석 **워크플로우 관측 페이지**(LangGraph 구조 Mermaid + 단계별 실제 데이터)

## 기술 스택
- 언어: **Python**
- 에이전트: **LangGraph**(StateGraph, 조건 분기·병렬 fan-out·루프·HITL)
- LLM: **OpenAI** gpt-4o-mini / gpt-4o (+ vision)
- 그래프 DB: **Neo4j Aura**(직군–스킬: REQUIRES / PREFERS / CO_OCCURS / PART_OF)
- 데이터: **Adzuna API**
- PDF: pdfplumber(텍스트) + PyMuPDF(이미지)
- 평가: **RAGAS**(faithfulness) + **Langfuse**(트레이싱)
- 서빙: **FastAPI + Docker** + 정적 웹 프론트
- 도구: VS Code, Git/GitHub, Docker

## 기술별 사용 방식 (무엇을 어떻게 썼나)
| 기술 | 어떻게 쓰는가 |
|---|---|
| **Python** | 전체 구현 언어 |
| **OpenAI API**(gpt-4o-mini/4o, vision) | 공고·이력서 스킬 추출, Gap 판단·코칭 생성, GitHub 프로젝트 프로필 요약, 포트폴리오 vision 분석 |
| **LangGraph** | StateGraph로 멀티에이전트 그래프 조립, `Send` 병렬 fan-out·Gap 루프·`stream`(진행 표시) |
| **LangChain** | `ChatOpenAI`·`bind_tools`로 도구 호출 LLM, `@tool`로 에이전트 툴 정의, 메시지 객체 |
| **RAG / Agentic RAG** | Gap 루프에서 증거 부족 시 그래프·통계 도구 재검색(Corrective RAG) |
| **Neo4j Aura** | 직군–스킬 그래프 적재, 직군 핵심 스킬·CO_OCCURS 연계 스킬 조회, 공고 원문 검증 근거 |
| **Adzuna API** | 직군별 채용공고 원본 수집 |
| **GitHub API** | repo 언어·README·의존성·메타 조회 → 스킬 검증 + 프로젝트 프로필 |
| **httpx** | Adzuna·GitHub·배포 URL HTTP 호출 |
| **pdfplumber** | 이력서·포트폴리오 PDF 텍스트 추출 |
| **PyMuPDF** | 포트폴리오 PDF를 이미지로 렌더 → vision 입력 |
| **Pydantic** | API 요청·응답·내부 모델 스키마 검증 |
| **RAGAS** | RAG 응답의 faithfulness(근거 충실도) 측정 |
| **Langfuse** | 그래프 실행 트레이싱(콜백 주입) |
| **FastAPI + uvicorn** | REST API 서버 + 정적 프론트 동일 출처 서빙 |
| **Docker** | 컨테이너 패키징·기동 |
| **정적 HTML/CSS/JS** | 업로드·분석·결과·관측 웹 UI |
| **Mermaid.js** | 관측 페이지 LangGraph 워크플로우 다이어그램 |
| **pytest** | 단위 테스트 179개 |

## 아키텍처 (LangGraph 멀티에이전트)
```
START → dispatcher(입력 소스만 Send) → [평가자 병렬: 이력서·GitHub·배포·포트폴리오]
  → consensus(검증 등급 결정적 판정) → Gap 루프(call_model↔tools, Corrective RAG)
  → synthesizer(적합도+신뢰도, 수치는 코드가 결정적 계산) → critic(환각 제거·라벨 교정)
  → coach(프로젝트 기반 코칭) → END
```
- 소스마다 modality(텍스트·코드·웹·이미지)가 달라 **전용 평가자**로 분리(기능이 요구하는 멀티에이전트).
- **Corrective RAG**: 증거가 부족하면 LLM이 스스로 그래프·통계 도구를 추가 검색.

## 핵심 설계 결정 (차별점·면접 포인트)
- **신뢰할 값은 LLM이 추측하지 않고 코드가 계산** — 적합도·신뢰도는 결정적 산출, LLM의 임의 점수는 덮어씀(환각 차단).
- **교차검증 신뢰도** — 이력서(주장) vs GitHub 코드·배포(실증)를 구분, 2개 이상 독립 출처 일치 시 등급 상승. "법정·저널리즘의 다중 출처 원칙"을 코드로.
- **측정해서 결정** — 벡터 DB(Chroma)를 넣었다가 검색 12건 중 11건이 키워드 매칭과 동일해 **효과 없음을 측정하고 제거**, Neo4j 그래프로 통합.
- **역량 → 스킬 레벨 전환** — 스킬을 거친 "역량"으로 묶으니 Data Analyst/Engineer가 구분 안 됨(핵심 스킬 자카드 0.14) → 개별 스킬 비교로 직군 변별력 확보.
- **Critic = 결정적 검증기** — LLM-as-judge가 아니라, 리포트 스킬을 합의(사실)와 대조해 환각 제거·라벨 교정.

## 트러블슈팅 (원인 분석 사례)
- **적합도 과소평가(대기업 합격자도 30%)**: 현상으로 끝내지 않고 원인(역량 평균 편향)을 데이터로 분석 → 스킬 레벨 전환으로 83% 정상화.
- **직군 데이터 오염**: Architect가 SAP·Data·Solution 아키텍트 잡탕으로 묶임, Security 특화 스킬 약함 → 직군 키워드·수집 쿼리 정교화로 해결(Security 공고 15→107).
- **스킬 표기 분산**: `machine learning`/`Machine Learning`, `ML`/`Machine Learning`이 따로 집계 → 정규화 함수에 표기·동의어 통합.
- **재적재 일부 누락(248/535)**: 오류 로그가 없어 혼란 → 명령의 `tail`에 오류가 잘린 것 + Neo4j Aura 일시 transient임을 재현으로 진단.

## 타겟 직무 적합성 (AI/ML·RAG 인턴)
- **RAG 파이프라인 설계·개발**: 단순 검색-생성을 넘어 Corrective RAG·멀티에이전트 교차검증 직접 설계.
- **LangChain·RAG·OpenAI API·Python**: 전부 실사용.
- **HR 도메인**: 채용 데이터를 다룬 경험으로 도메인 적응 비용 낮음.
- (멀티턴 챗봇 경험은 별도 프로젝트: 응급상황 챗봇·영어 회화 챗봇)
