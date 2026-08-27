# TODO

## 고칠 부분

- [x] ~~`github_eval.py`의 `_validate_project_context()`가 "파일 존재"만 검증하고
  "내용 관련성"은 검증 안 함 — 실제 환각 사례 확인~~ (2026-08-26 수정 완료)
  실제 레포(K-ismyname/jobgraphPJ)로 테스트 중 `PostgreSQL` 스킬이 `current_usage: 중급 패턴`,
  `relevant_files: ['src/storage/neo4j_client.py']`로 잘못 평가됨 — 이 프로젝트는 PostgreSQL을
  전혀 안 쓰고(`neo4j_client.py`에 postgres 언급 0회, `requirements.txt`에도 없음), 원인은
  README가 "이렇게 환각하면 안 된다"는 반례로 든 문장("예: Neo4j를 PostgreSQL로 전환")의
  "PostgreSQL" 단어를 `_skills_from_sources()`가 단순 키워드 매칭으로 주워서 `strength="mention"`
  으로 잡고, 이후 `_assess_project_and_skills()`의 LLM이 그걸 근거로 그럴듯한 `current_usage`·
  `relevant_files`까지 만들어냄. `_validate_project_context()`는 `relevant_files` 경로가
  레포에 "존재하는지"만 확인해서(존재함 — `neo4j_client.py`는 진짜 파일), 파일 내용이 실제로
  그 스킬을 뒷받침하는지는 검증하지 않아 이 환각이 그대로 통과됐음. 수정: `relevant_files`가
  실제 경로에 존재하는지뿐 아니라 파일 내용·언어 확장자가 해당 스킬을 뒷받침하는지 2차 대조하고,
  README-only mention은 LLM의 "이미 확인된 스킬(반드시 포함)" 힌트에서 제외. 함께 루트 전용
  manifest 스캔도 재귀 스캔으로 확장해 `backend/requirements.txt`, `frontend/package.json` 같은
  하위 의존성 파일을 놓치지 않게 함. 회귀 테스트 추가, 전체 unit 312개 통과.

- [x] ~~`src/agent/supervisor.py`의 `verified_names` 계산이 항상 빈 리스트였던 버그~~ (2026-07-07 수정 완료)
  `result.get("consensus").get("skills", [])`를 호출하고 있었는데, consensus는 `{스킬명: {verification, evidences}}`
  형태의 dict라 "skills" 키가 없어 항상 빈 리스트였음. `consensus_dict.items()`를 직접 순회하도록 수정 —
  이제 `recommend_job_postings`가 실제로 Verified/Corroborated 스킬을 우선으로 공고를 추천함.

- [x] ~~`scripts/collect_muse.py` `is_relevant()` 정밀도 문제~~ (2026-07-07 수정 완료)
  `preprocessor.py`의 `_NON_TECH_TITLE_KEYWORDS`에 `field engineer`, `support engineer`, `it support`를
  추가해 2차 필터(`is_tech_job()`)에서 걸러지도록 함. 실제 오탐 사례 4건 전부 재검증 통과
  (`Lead Field Engineer - Piping`, `Critical Infrastructure Mechanical Engineer, Field Engineering`,
  `Sr. IT Support Engineer`, `Customer Support Engineer-Level 1` → 전부 False),
  `Senior Software Engineer`/`AI/LLM Engineer` 같은 정상 케이스는 계속 True. 기존 단위테스트 27개 통과.

- [x] ~~`gap_agent` ReAct 루프 마지막 턴의 텍스트 출력이 버려짐~~ (2026-07-07 완화 완료)
  `_GAP_SYSTEM_PROMPT`(nodes.py) 5번 규칙에 "이 시점의 응답 텍스트는 리포트 생성에 쓰이지 않고
  오직 종료 신호로만 쓰이니, '분석 완료'처럼 한 단어로 답하라"고 명시해 마지막 턴 출력 토큰을 줄임.
  ponytail: 이건 프롬프트 지시일 뿐 코드로 강제된 상한이 아니라서, LLM이 지시를 무시하고 길게
  쓸 가능성은 여전히 남아있음 — 확실히 막으려면 `max_tokens`를 코드로 제한해야 하는데, 그러면
  gap_analysis/verify_skills 같은 도구 호출 인자(스킬 리스트가 길 때)가 잘릴 위험이 있어 보류함.
  더 강하게 조이려면: 도구 호출 유무를 먼저 판별하는 별도의 저비용 사전 호출을 추가하는 구조 변경 필요.

- [x] ~~`src/portfolio/github_connector.py`의 `parse_github_username()` 죽은 코드~~ (2026-07-07 삭제 완료)
  테스트도 없고 어디서도 호출되지 않아 제거함.

- [x] **`boost_confidence_from_github()` 프로덕션 미연결 — 그대로 두기로 결정** (2026-07-07 결정)
  `AppState`에 `github_username` 필드가 없어 연결하려면 State 스키마 확장 + Supervisor 그래프
  수정이 필요한 별도 기능 추가 사안 — 지금 당장 필요 없다고 판단해 보류. 테스트
  (`tests/unit/test_github_boost.py`)는 계속 유지. 실제로 필요해지면 그때 연결.

- [x] ~~`src/portfolio/github_connector.py`의 `_SKILL_KEYWORDS` vs `normalizer.py` 이원화~~ (2026-07-07 수정 완료)
  `boost_confidence_from_github()`가 `_SKILL_KEYWORDS`(수동 튜닝 키워드: dockerfile, k8s, boto3 등)와
  `keywords_for()`(정규화 별칭: react.js, 리액트 등)를 합집합으로 합쳐 쓰도록 수정 — 실제로 교체 전
  검증해보니 `_SKILL_KEYWORDS`에만 있고 `SKILL_ALIASES`엔 없는 키워드가 9개 스킬에서 발견돼
  단순 교체 대신 합집합 방식을 택함. `print()`도 `logger`로 교체. 기존 테스트 2개 통과.

- [x] ~~`src/agent/tools.py`의 `_PORTFOLIO_SKILLS_QUERY` 죽은 상수~~ (2026-07-07 삭제 완료)
  어디서도 참조되지 않아 제거함.

- [x] ~~`gap_analysis()`의 `unverified_required`가 항상 빈 리스트였던 버그~~ (2026-07-08 수정 완료)
  `neo4j.get_portfolio_demonstrated_skills(owner)`로 confidence를 조회했는데, 이 데이터를 쓰는
  `save_portfolio()`가 실제 흐름에서 한 번도 호출되지 않아(확인: 배포 Neo4j에 `PortfolioItem` 노드
  0개) 항상 빈 dict → `conf`가 항상 `"medium"` 기본값 → `unverified_required`(근거 약한 보유 스킬)가
  구조적으로 절대 채워지지 않았음. `consensus.py`가 이미 계산해둔 실제 verification 등급
  (Verified/Corroborated/Claimed)을 `nodes.py`의 `make_tools_node()`가 `gap_analysis` 호출 시
  `state["consensus"]`로 직접 주입하도록 수정 — Neo4j 왕복도 필요 없고 LLM이 문맥을 재파싱할
  필요도 없어짐. 검증: React(Verified)→have_required, Docker(Claimed)→unverified_required로
  정확히 분리되는 것 확인. 관련 테스트 27개 통과.

- [x] ~~`src/evaluation/ragas_eval.py`의 `_report_to_natural_text()` 죽은 코드~~ (2026-07-07 삭제 완료)
  테스트도 없고 어디서도 호출되지 않아 제거함 (`test_ragas_eval.py` 4개 통과 확인).
  아마 리포트 전체를 통째로 평가하던 이전 방식("옵션 B")의 흔적으로, 지금은 스킬 단위로
  평가하는 `_build_evidence_samples()`("옵션 A")로 대체된 것으로 보임.

- [x] ~~`src/api/schemas.py`의 `ErrorResponse` 죽은 코드~~ (2026-07-07 삭제 완료)
  어디서도 참조되지 않아 제거함. `main.py`의 에러 핸들러는 이 클래스 없이 직접 딕셔너리를 반환.

- [x] ~~`VerificationItem.verification` 필드가 `str`이라 값 제한이 없던 문제~~ (2026-07-07 수정 완료)
  `consensus.py`가 "Verified"/"Corroborated"/"Claimed" 세 문자열만 결정적으로 만들어내는 걸
  확인하고 `Literal["Verified", "Corroborated", "Claimed"]`로 좁힘 — `InterviewCoaching.type`과
  스타일 통일. 관련 테스트(`test_api_mapping`, `test_consensus`, `test_umbrella_skills` 등 25개) 통과.

- [x] ~~`portfolio.py`의 `_demo_usage` 일일 한도 카운터 경쟁 조건(race condition)~~ (2026-07-07 수정 완료)
  `analyze_portfolio`가 `def`(동기)라 여러 스레드에서 동시 실행 가능한데, "확인 후 증가"가
  원자적이지 않아 동시 요청 시 하루 한도(기본 1회)를 넘길 수 있었음. `threading.Lock`으로
  확인+증가 블록을 감싸 수정. `test_demo_limit.py` 통과.

- [x] ~~`portfolio.py`에서 포트폴리오 임시 파일 재사용 시 조용히 실패하던 문제~~ (2026-07-07 수정 완료)
  같은 `portfolio_report_id`로 두 번째 `/analyze`를 호출하면(예: 다른 직군으로 재분석), 첫 분석
  종료 시 이미 삭제된 임시 PDF 경로를 그대로 참조해 `portfolio_eval.py`가 조용히 빈 결과를
  냈음(에러 없음). `analyze_portfolio`에서 경로가 없거나 파일이 실존하지 않으면 404로 명확히
  거절하도록 추가하고, `_run_analysis` 완료 후 `uploads`에서도 해당 항목을 제거하도록 수정.
  관련 테스트(`test_api_mapping`, `test_demo_limit`, `test_progress_phase`, `test_upload_validation`
  총 14개) 통과.

- [x] **`preprocessor.py`의 `preferred_section`에 fallback 없음 — 보류로 결정** (2026-07-08 결정)
  `required_section`은 실패 시 `extract_bullet_section` → `extract_requirement_sentences` 2단계
  fallback이 있지만, `preferred_section`은 1차(`extract_sections`) 실패 시 그냥 빈 문자열로 남음.
  실측(jobs_raw_muse.json 324건): 필수 텍스트 확보 323건(100%) vs 우대 텍스트 확보 121건(37%) —
  필수는 있는데 우대가 없는 경우 202건(62%). 다만 보류로 결정 — ① 이 202건 중 상당수는 애초에
  "우대사항" 섹션 자체가 없는 공고일 가능성이 높고, ② `tools.py`의 `gap_analysis()`가 계산하는
  핵심 지표 `match_rate`는 `required` 스킬만 씀(`preferred`는 `missing_preferred` 부가 정보에만
  영향), ③ 우대 신호 패턴(`_PREF_SIGNALS`)으로 fallback을 만들어도 필수 문장과 겹쳐 오탐 위험이
  있어 정확도 이득 대비 리스크가 더 큼.

- [x] ~~`neo4j_client.py`의 `save_portfolio()`/`get_portfolio_demonstrated_skills()`/
  `update_portfolio_confidence()` 죽은 코드 3건~~ (2026-07-08 삭제 완료)
  전부 실제 흐름에서 호출자가 없음을 grep으로 확인 후 삭제. 함께 쓰이던 `UPSERT_PORTFOLIO_ITEM`/
  `UPSERT_DEMONSTRATES` Cypher 상수, `CREATE_CONSTRAINTS`의 `portfolio_item_id` 제약, 라이브
  Neo4j Aura에 이미 걸려있던 `portfolio_item_id` 제약(`DROP CONSTRAINT`로 제거, `PortfolioItem`
  노드 0개 확인 후 실행), CLAUDE.md 스키마 문서의 `PortfolioItem`/`DEMONSTRATES` 항목까지 전부 정리.
  단위테스트 241개 통과.

- [x] ~~`ragas_eval.py`의 `_build_evidence_samples()` 평가 설계 결함~~ (2026-07-08 재설계 완료)
  `user_input`이 "Is Docker required?"처럼 Neo4j `REQUIRES` 관계로 이미 답 가능한 질문이라
  RAGAS(LLM 채점기)를 쓸 이유가 약했음(실측: Faithfulness 0.33~0.56, deterministic_reasons는
  Answer Relevancy 0이 나올 정도로 부적합). `user_input`을 "이 직군에서 X이 부족한 이유는
  무엇인가?"로, `response`를 코드로 지어낸 템플릿에서 `gap_result["missing_required"][].reason`
  (실제 LLM 자유생성 텍스트)으로 교체. 추가로 그래프에 전혀 없는 순수 텍스트 정보(스킬별
  숙련도·연차 표현)를 원문에서 찾아 RAG로 답하게 하는 `_build_skill_proficiency_samples()`를
  신설해 `run_ragas_eval()`에 옵션 B로 통합 — 실측 결과 Faithfulness 0.70~0.77,
  Answer Relevancy 0.59~0.64로 옵션 A(0.33~0.56/0.31~0.42) 대비 큰 폭 개선, "그래프로 대체
  불가능한 질문 + 자연어 답변" 조합이라야 RAGAS가 의미 있는 지표를 낸다는 결론.
  부수 발견: `pyarrow` 17.0.0이 `datasets`(ragas 의존성) import 시 `AttributeError` 유발 —
  24.0.0으로 업그레이드해 해결(프로젝트 코드는 pyarrow 직접 미사용).

## 나중에 추가적으로 구현하면 좋을 부분

- [ ] **`gap_agent`의 ReAct 루프가 실제로는 거의 고정 파이프라인** (2026-07-08 논의)
  `_GAP_SYSTEM_PROMPT`(nodes.py)의 5단계 절차 중 1~3번(gap_analysis → verify_skills
  top-5 → skill_unlock top-3)은 순서·조건이 항상 고정이라 사실상 결정적 파이프라인이고,
  진짜 판단이 필요한 건 4번(posting_trend를 "우선순위 판단이 필요한 스킬에만" 선택 호출)
  뿐임. 지금은 이 한 단계의 유연성 때문에 전체를 ReAct 루프(매 턴 LLM 호출, 최대 5회)로
  감싸고 있어, 1~3번을 파이썬으로 고정 실행하고 4번만 규칙 기반(예: verify_skills 결과가
  graph_only인 스킬만 posting_trend 호출)으로 대체 + 마지막에 LLM 1회만 리포트 작성하는
  구조로 바꾸면 LLM 호출을 최대 5회 → 1회로 줄일 수 있음. 다만 비용 문제가 실측된 적은
  없고, 프롬프트만으로 절차를 조정할 수 있는 유연성이 사라지는 트레이드오프가 있어
  지금 당장 급한 건 아님 — 인터뷰 질문("다시 설계한다면?") 답변 소재로 기록만 해둠.

- [ ] **`depth`/`current_usage`(기초·중급·고급) 판정 기준 부재** (2026-07-08 발견)
  `portfolio_eval.py`의 `depth`, `github_eval.py`의 `current_usage` 둘 다 "기초/중급/고급"
  3단계로 나누지만, 프롬프트에 "포트폴리오/코드 근거 기반으로 판단"이라고만 돼 있을 뿐
  등급을 가르는 구체적 기준이 전혀 없음 — 전적으로 LLM의 암묵적 판단에 위임된 상태.
  실제로 문제된 사례는 아직 없지만, 나중에 프롬프트에 구체적 기준을 추가하는 방향 고려
  (예: "기초=API 호출 수준, 중급=커스텀 로직 결합, 고급=아키텍처 설계·최적화 판단 포함").

- [ ] **`levels` 필드 활용**
  현재 `preprocessor.py`가 `level` 값으로 저장만 하고 이후 분석에서 안 씀.
  신입/시니어 등 연차별로 요구 기술 스택이 다른가를 분석하면,
  이력서 갭 분석 시 사용자 연차에 맞는 비교 기준을 제공할 수 있음
  (예: 신입 이력서를 시니어 공고 기준으로 비교해 갭이 과대평가되는 문제 방지).

- [ ] **`publication_date` 필드 활용**
  현재 저장만 되고 트렌드 분석에 미사용.
  최근 N개월 vs 그 이전 기간의 기술 요구 변화를 시계열로 비교하면
  CLAUDE.md의 "직군별 핵심 기술·트렌드 분석" 기능을 더 강화할 수 있음
  (예: LangGraph 언급 비율이 최근 3개월 사이 증가했는지 등).

- [ ] **스킬 추출 오탐: 학위 요건 문구가 스킬로 잘못 추출됨** (2026-07-08 RAGAS 실측 중 발견)
  Walmart 공고의 "Bachelor's degree in ... Mathematics, Computer Science, Information
  Technology" 같은 학위 요건 문구가 `Mathematics`/`Computer Science`/`Information Technology`
  라는 "스킬"로 추출되어 그래프에 들어가 있음. 기존에 기록된 "Adzuna 데이터 결함(추출 환각)"
  문제의 구체 사례로 보임 — `skill_extractor.py` 프롬프트에 "학위/전공명은 스킬이 아니다" 같은
  제외 규칙을 추가하는 방향으로 개선 가능. 지금은 발견만 하고 미수정.
