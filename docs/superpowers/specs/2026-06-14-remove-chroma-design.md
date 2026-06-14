# Chroma(벡터 DB) 제거 — Neo4j 텍스트 근거로 전환

**작성일:** 2026-06-14
**목적:** 효과가 검증되지 않은 벡터 DB(Chroma)를 제거하고, 공고 원문 근거를 Neo4j `JobPosting` 속성으로 옮긴다. 아키텍처를 단순화하고 "왜 벡터 DB를 안 썼나"에 데이터로 답할 수 있게 한다.

**배경(검증 완료):** `verify_skills`/`vector_search`가 **스킬명(키워드)으로** 검색하므로 hybrid의 dense/rerank가 기여하지 못한다 — Chroma 검색 결과 12개 중 11개가 키워드를 정확히 포함(키워드 매칭과 동일). 이 데이터(274 공고)·용도에선 벡터 DB가 기능적 효과가 없다. 원문은 Chroma에만 있는 게 아니라 원천 `data/processed/jobs_filtered.json`(321건, `required_section`·`preferred_section`·`text_clean`, `id`=`source_id`)에 있어 Neo4j로 백필 가능하다.

---

## 범위

**포함:**
1. `JobPosting` 노드에 `required_section`·`preferred_section` 원문 속성 백필 + 적재 시 포함.
2. `verify_skills` 근거 검색을 Chroma → Neo4j 텍스트로.
3. `vector_search` 도구 **제거**.
4. RAGAS `retrieved_contexts`를 Neo4j 텍스트로.
5. Chroma 의존 완전 제거.

**제외:** 적합도·역량·합의·코칭 로직 변경 없음(근거의 *출처*만 바뀜). 공고 재수집 없음(원천 JSON 사용).

---

## 설계

### ① JobPosting 원문 속성 백필

`jobs_filtered.json`의 `required_section`·`preferred_section`을 `source_id`로 매칭해 노드 속성으로:
```cypher
MATCH (p:JobPosting {source_id: $source_id})
SET p.required_section = $required, p.preferred_section = $preferred
```
- 신규 `neo4j_client.set_posting_sections(source_id, required, preferred)`.
- 신규 백필 스크립트 `scripts/backfill_posting_text.py` — `jobs_filtered.json` 순회.
- 적재 파이프라인(JobPosting 생성부)에도 두 속성 포함하도록 추가(향후 수집분).
- `text_clean` 전체는 제외(6,593자×321 과함). 요건 섹션만으로 스킬 근거 충분.

### ② verify_skills — Neo4j 텍스트 근거

현재: `get_postings_requiring_skill(skill)` → `chroma.search`로 청크. 변경:
- `get_postings_requiring_skill`(기존)로 공고 source_id 확보.
- 신규 `neo4j_client.get_posting_sections(source_ids)` → `[{source_id, company, required_section, preferred_section}]`.
- 그 텍스트에서 **스킬 키워드가 든 문장**을 근거로 추출(문장 분리 후 키워드 매칭, 없으면 섹션 앞부분). github_eval의 `_word_match`/`_keywords_for` 재사용.
- 반환 형식은 기존 `verify_skills`와 동일(`{method, posting_count, evidence:[{source_id, company, text}]}`)해서 다운스트림(gap·RAGAS) 무변경.

### ③ vector_search 도구 제거

`create_tools`의 도구 목록에서 `vector_search` 삭제. gap 프롬프트(nodes.py)에서 vector_search 언급 제거. `tools_node`의 vector_search dedup 분기 제거(verify_skills dedup은 유지).

### ④ RAGAS

`ragas_eval`이 evidence(이제 Neo4j 텍스트)를 그대로 retrieved_contexts로 쓰므로 큰 변경 없음. Chroma import만 제거.

### ⑤ Chroma 의존 제거

| 파일 | 변경 |
|------|------|
| `src/storage/chroma_client.py` | 삭제 |
| `src/api/deps.py` | `get_chroma` 제거 |
| `src/api/main.py` | lifespan `app.state.chroma`, `create_supervisor_graph` 인자 |
| `src/api/routers/stats.py` | `chroma_chunks` 제거(스키마도) |
| `src/agent/supervisor.py` | `create_supervisor_graph(neo4j, openai)`, `create_tools(neo4j)` |
| `src/agent/tools.py` | `create_tools(neo4j)`, chroma.search 대체, vector_search 삭제, coach `verify_suggestion`도 Neo4j 텍스트 |
| `src/agent/nodes.py` | `create_nodes(tools, neo4j)` (chroma 인자 제거) |
| `src/ingestion/pipeline.py` | Chroma 적재 단계 제거 |
| `src/evaluation/ragas_eval.py` | Chroma import 제거 |
| `requirements.txt` | `chromadb`, `sentence-transformers`(CrossEncoder rerank용) 제거 검토 |
| 테스트 | chroma mock 쓰던 곳 정리(`test_gap_*`, `test_stats`, `test_agent`) |

`StatsResponse.chroma_chunks` 필드 제거(데이터 탭 UI에서도).

---

## 데이터 흐름 (변경 후)

```
적재: jobs_filtered.json → Neo4j JobPosting(메타 + required/preferred_section)   [Chroma 없음]
분석: verify_skills → Neo4j(스킬 요구 공고 + 요건 섹션 텍스트) → 근거 문장
평가: RAGAS retrieved_contexts ← 같은 Neo4j 근거 텍스트
```

## 에러 처리

| 상황 | 처리 |
|------|------|
| JobPosting에 섹션 속성 없음(백필 전/누락) | verify_skills 근거 빈 리스트, gap은 graph_only로 진행 |
| 섹션에 스킬 문장 없음 | 섹션 앞부분 일부를 근거로(또는 빈), 기존 fallback 유지 |

## 테스트

- 백필: `set_posting_sections` 후 `JobPosting.required_section` 존재(통합).
- `get_posting_sections(source_ids)` 반환 구조(통합).
- `verify_skills`가 Neo4j 근거 반환, evidence에 스킬 키워드 포함(통합, mock 또는 실 Neo4j).
- `create_tools(neo4j)` 단일 인자 동작, vector_search 부재.
- `GET /stats`에 `chroma_chunks` 없음.
- 전체 회귀: chroma import 제거 후 `pytest` 통과, `python -c "import src.api.main"` 성공.

---

## 비결정 사항(구현 중 확정)

- `sentence-transformers` 제거 여부 — CrossEncoder는 Chroma rerank 전용이었으니 다른 데서 안 쓰면 제거. (requirements 점검)
- 근거 문장 추출 입도 — 문장 단위 vs 섹션 통째. MVP는 "스킬 키워드 포함 문장 ±, 없으면 섹션 앞 300자".
- 백필을 적재 코드에 통합 vs 별도 스크립트 — 둘 다(스크립트로 기존 백필, 적재 코드에 향후분).
