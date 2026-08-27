# Job Skill Analyzer 면접 준비

핵심 설명 + 예상 질문 모음. 답변은 각 질문 아래 직접 메모.

---

## 모듈 0 — 한 줄 피치

### 핵심 설명
"채용공고를 수집·분석해서 이력서를 올리면 직무 대비 부족한 기술과 개선 방향을 알려주는 Agentic RAG 시스템"

오프닝 40초 공식: **문제 → 해결책 → 차별점**
- 문제: 기존 채용 플랫폼은 이력서 점수만 주고 근거가 없다
- 해결책: 실제 공고 데이터 + 코드·배포 교차검증으로 신뢰도 있는 갭 분석
- 차별점: "이 스킬이 부족하다"는 주장이 얼마나 믿을 만한지(신뢰도)를 분리해서 보여줌

### 예상 질문
- "이 프로젝트를 간단히 소개해주세요."

---

## 모듈 1 — 왜 만들었나

### 핵심 설명
- 단순 키워드 매칭: "Python 잘 함"이 이력서에 있으면 무조건 통과 → 근거 없음
- 이 프로젝트: LLM이 "이 주장이 코드/배포로 확인되는가?"를 판단
- 신뢰도(Verified/Corroborated/Claimed)를 적합도와 분리 — 점수와 근거를 다르게 다룸

### 예상 질문
- "이 프로젝트를 만든 계기가 뭔가요?"
- "기존 채용 플랫폼과 어떻게 다른가요?"

---

## 모듈 2 — 아키텍처 큰 그림

### 핵심 설명
```
공고 수집(Layer 1) → Neo4j 저장(Layer 2) → LangGraph 에이전트(Layer 3)
→ 갭 분석(Layer 4) → RAGAS 평가(Layer 5) → FastAPI 서빙(Layer 6)
```
- 원칙: 뒤 레이어를 앞 레이어보다 먼저 짜지 않는다
- 데이터 흐름: 이력서 PDF → 4개 평가자 병렬 → 교차검증 → gap 루프 → 코칭 → 리포트

### 예상 질문
- "시스템 아키텍처를 설명해주세요."
- "어떤 순서로 개발했나요? 왜 그 순서인가요?"

---

## 모듈 3 — 기술 스택 선택 이유

### 핵심 설명
| 기술 | 선택 이유 | 대안을 버린 이유 |
|------|----------|----------------|
| LangGraph | 조건 분기·루프·HITL 필수 | LangChain만으로 불가 |
| Neo4j | 직무-기술 관계 표현 최적 | 벡터DB는 관계 표현 불가 |
| Chroma 제거 | 검색 12건 중 11건이 키워드 매칭과 동일 | 효과 없음을 측정 후 제거 |
| Adzuna API | 무료·합법·JSON 구조화 | 직접 크롤링은 약관 위반 |
| OpenAI 단일 | 비용 효율·통일된 인터페이스 | 복수 공급자는 복잡도만 증가 |

### 예상 질문
- "왜 LangGraph를 선택했나요?"
- "벡터 DB를 안 쓴 이유가 뭔가요?"
- "Chroma를 제거한 근거가 있나요?"

---

## 모듈 4 — 핵심 설계 의사결정 (가장 중요)

### 핵심 설명

**1. 적합도 ⊥ 신뢰도 분리**
- 적합도(fit): 직군 핵심 스킬 중 몇 개 보유 (코드로 계산)
- 신뢰도: 그 주장이 얼마나 믿을 만한가 (Verified/Corroborated/Claimed)
- "Python 잘 함(이력서)"과 "Python 잘 함(GitHub 확인)"은 다름

**2. 결정적 계산 — LLM이 숫자를 못 만들게**
- consensus.py, critic.py는 LLM 없이 코드로만 동작
- LLM은 숫자를 지어낸다 → 신뢰도 등급은 규칙 기반으로 산출

**3. 다중 소스 교차검증**
- resume / github / portfolio / deploy 독립 평가 후 합의
- 이력서 주장만 믿으면 과장이 걸러지지 않음

**4. Corrective RAG 루프**
- 근거가 부족하면 tools를 다시 호출 (최대 5회)
- 에이전트가 스스로 "증거가 충분한가?"를 판단

**5. Critic = 판단 없는 서기**
- Gap 리포트 ↔ Consensus 대조해 환각만 제거
- 적합도 판단은 Gap 루프에 위임, Critic은 라벨 교정만

### 예상 질문
- "RAG 구조를 어떻게 설계했나요?"
- "신뢰도는 어떻게 측정하나요?"
- "환각(hallucination)은 어떻게 처리했나요?"
- "에이전트가 스스로 추가 검색을 결정하는 로직은?"

---

## 모듈 5 — LangGraph 에이전트 상세

### 핵심 설명
```
입력 → evaluator_dispatch
  ↓ [Send API로 병렬 fan-out]
resume_eval | github_eval | portfolio_eval | deploy_eval
  ↓ (모두 완료)
consensus (등급 결정적 산출)
  ↓
seed_gap → [루프, 최대 5회] call_model ↔ tools
  ↓
synthesizer → critic → [루프, 최대 3회] coach → END
```
- Send API: 병렬 fan-out 구현
- interrupt: HITL 구현 (애매한 경우 사용자에게 되묻기)
- 루프 종료: MAX_ITERATIONS 카운터

### 예상 질문
- "LangGraph로 무엇을 구현했나요?"
- "병렬 처리는 어떻게 했나요?"
- "루프는 언제 멈추나요?"

---

## 모듈 6 — 핵심 코드 파일

### 핵심 설명
- `consensus.py`: 4개 평가자 결과 → Verified/Corroborated/Claimed (규칙 기반, LLM 없음)
- `critic.py`: Gap 리포트 스킬 ↔ Consensus 대조, 없으면 제거 + 라벨 교정
- `gap_analyzer.py`: 직군 상위 10개 스킬 vs 이력서 스킬 교집합 계산
- `normalizer.py`: "React.js" → "React" 동의어 70개 규칙
- `supervisor.py`: 전체 StateGraph 조립·실행 진입점

### 예상 질문
- "가장 복잡했던 부분은 무엇인가요?"
- "코드에서 LLM 의존성을 줄인 곳이 있나요?"

---

## 모듈 7 — 심층 질문 대비

### Q: "Chroma 제거 측정 데이터가 있나요?"
검색 12건을 직접 실행해 결과를 키워드 매칭과 비교. 11건이 동일한 결과, 1건도 실질적 차이 없음. 복잡도 추가 없이 제거 결정.

### Q: "RAGAS 지표 결과는?"
Faithfulness=0.250, AnswerRelevancy=0.876.
Faithfulness가 낮은 이유: Adzuna 공고가 "required" 명시 없이 간접 표현("familiarity with X") 사용 → NLI 매칭 어려움. 구조적 한계.

### Q: "벡터 검색 없이 어떻게 RAG인가요?"
RAG의 핵심은 외부 소스에서 증거를 검색해 LLM 답변을 보강하는 것. Neo4j 그래프 쿼리와 GitHub API·배포 URL 검색으로 구현. 벡터 유사도 검색이 RAG의 필수 요소가 아님.

### Q: "왜 단일 LLM 공급자(OpenAI)만 쓰나요?"
포트폴리오 단계에서 다중 공급자는 불필요한 복잡도. gpt-4o-mini를 기본으로, 복잡한 추론만 gpt-4o 사용. 비용 효율적.
