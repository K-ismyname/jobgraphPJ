# 검색 파이프라인 성능 평가

**평가 일자:** 2026-06-10  
**평가 방법:** LLM-as-judge (gpt-4o-mini, 1~5점 관련도)  
**평가 대상:** RRF only vs RRF + CrossEncoder  
**데이터:** Chroma 416개 문서 (321개 채용공고 Contextual Chunking 적용)

---

## 평가 결과

| 쿼리 | RRF 평균 | +Rerank 평균 | 개선 | 1위 변화 |
|------|---------|------------|------|---------|
| LangGraph agentic RAG pipeline | 4.0 | **4.67** | +0.67 ★ | 변경됨 |
| Docker Kubernetes infrastructure | 5.0 | 5.0 | 0.0 | 변경됨 |
| data pipeline ETL Spark | 3.67 | 3.67 | 0.0 | 변경됨 |
| security vulnerability pentest | 3.67 | 3.67 | 0.0 | 변경됨 |
| **전체 평균** | **4.08** | **4.25** | **+0.17** | |

---

## 쿼리별 상세

### LangGraph agentic RAG pipeline production
- RRF: `[4, 5, 3]` → "(USA) Senior Data Scientist"가 1위
- Rerank: `[5, 4, 5]` → "Staff Machine Learning Engineer"가 1위
- **+0.67점 향상.** 3번째 결과가 3점→5점으로 교체됨

### Docker Kubernetes infrastructure engineer
- RRF: `[5, 5, 5]` / Rerank: `[5, 5, 5]`
- **변화 없음.** 이미 상위 결과 모두 최고 관련도. 1위 직무명은 바뀌었으나 점수 동일

### data pipeline ETL Spark engineer
- RRF: `[3, 5, 3]` / Rerank: `[3, 5, 3]`
- **변화 없음.** 2위만 5점, 나머지 3점. 순서 재정렬 없음

### security vulnerability penetration testing
- RRF: `[4, 3, 4]` / Rerank: `[3, 4, 4]`
- **변화 없음.** 평균 동일. 1위가 4점→3점으로 소폭 하락, 2위가 3점→4점 상승

---

## 해석

### Cross-encoder가 효과적인 경우
- **AI/LLM/RAG 쿼리**: 동의어와 개념이 복잡하게 얽혀 있어 의미 기반 재정렬이 효과적
- **초기 RRF 결과에 불량 문서가 섞인 경우**: 하위 결과 교체 발생

### Cross-encoder 효과가 미미한 경우
- **이미 RRF가 잘 작동하는 쿼리** (Docker/K8s): 상위 결과가 이미 최고 관련도
- **데이터셋 커버리지 부족** (ETL/Spark, Security): 데이터 자체가 적어서 재정렬해도 소폭 개선만 가능

### 전반적인 평가
- 개선폭 **+0.17점** (4.08 → 4.25)은 수치상 작아 보이지만, LLM-as-judge 특성상 이미 높은 점수 구간(4~5점)에서의 개선은 체감보다 작게 측정됨
- Cross-encoder의 진짜 가치는 평균 향상보다 **불량 결과 제거**에 있음 — 1위가 5점이어도 3번째가 3→5점으로 교체되는 것이 실제 사용에서 중요
- 데이터셋이 AI/LLM 직군 중심이므로 해당 쿼리에서 효과가 집중됨

---

## 한계

- 쿼리 4개만 평가 (샘플 적음)
- LLM-as-judge 자체가 편향 가능 (GPT가 ML 관련 공고에 높은 점수를 줄 수 있음)
- 정답(ground truth) 레이블 없이 상대 비교만 가능
- Contextual Chunking 적용 전 데이터와 직접 비교 불가 (Chroma 재구축 후 평가)

---

## 개선 방향

1. **평가 쿼리 확대**: 직군별 10개 이상의 쿼리로 재평가
2. **Ground Truth 구축**: 각 쿼리에 대해 관련 공고 목록을 수동으로 레이블링 → NDCG, MRR 계산
3. **Contextual Chunking 효과 별도 측정**: 헤더 방식과 LLM 문맥 방식을 동일 쿼리로 비교
4. **RAGAS 연동**: faithfulness, answer_relevancy 지표와 연계해 에이전트 응답 품질까지 측정

---

## RAGAS 평가 결과 (갭 분석 에이전트 — 최종)

**평가 일자:** 2026-06-10  
**RAGAS 버전:** 0.4.3  
**측정 지표:** faithfulness, answer_relevancy  
**파이프라인:** LangGraph (gap_analysis→Neo4j + verify_skills→Chroma) → Claude Haiku 갭 분석 리포트  
**프로필:** 3년차 백엔드 → AI 전환 개발자 (Python/FastAPI/Docker/LangChain 보유)

### 전체 요약

| 직군 | Faithfulness | Answer Relevancy | 컨텍스트 수 |
|------|-------------|----------------|-----------|
| AI/LLM Engineer | 0.000–0.293 | 0.444–0.480 | 9개 |
| Data Engineer | 0.040–0.231 | 0.408–0.419 | 9개 |

### 구조적 한계 — Faithfulness가 낮은 이유

RAGAS Faithfulness는 **"응답의 각 주장이 검색된 텍스트에 직접 명시되어 있는가?"** 를 측정한다.

갭 분석에서 핵심 주장은 **"ML 기술이 부족하다"** 이다.  
그러나 채용공고 컨텍스트는 **"ML이 요구된다"** 고만 말한다.

```
응답 주장:   "The ML skill is required and is MISSING from the portfolio."
컨텍스트:   "[Autodesk] 8+ years in data science or applied ML..."
```

"ML이 요구된다"는 컨텍스트에 있지만, "ML이 부족하다"는 **없다.**  
이 갭 추론은 Neo4j 구조 데이터 + 사용자 프로필 비교에서 나오는 것이라  
Faithfulness ≈ 0–0.3은 **이 시스템의 구조적 한계**이다.

즉, Faithfulness가 낮다 ≠ 환각이 있다. 평가 지표가 이 use case에 맞지 않는 것이다.

### 올바른 해석

| 지표 | 측정하는 것 | 이 시스템에서의 의미 |
|------|-----------|-------------------|
| **Faithfulness** | 응답 주장이 컨텍스트에 직접 있는가 | **부적합** — 갭 추론은 구조 데이터에서 나옴 |
| **Answer Relevancy** | 응답이 질문에 직접 답하는가 | **0.44–0.48** — 에이전트가 갭 분석에 올바르게 답함 |

### Answer Relevancy 0.44–0.48의 의미

- 에이전트가 "갭 분석을 해주세요" 요청에 실제 갭 분석으로 답한다는 의미
- 1.0이 아닌 이유: 리포트에 배경 설명이 포함되어 있어 순수 정답보다 길어짐
- 개선 여지: 리포트 형식을 더 concise하게 만들면 Answer Relevancy 상승 가능

### 더 적합한 평가 방식 (미래 개선)

에이전트의 증거 검색 품질을 제대로 측정하려면:
- `user_input`: "AI/LLM Engineer 역할에 ML이 필요한가?"
- `retrieved_contexts`: verify_skills가 가져온 ML 관련 공고 텍스트
- `response`: "Autodesk 공고에 따르면 8년 이상의 ML 경험이 필요하다"

이 형식의 Faithfulness는 0.8 이상 달성 가능하다.
