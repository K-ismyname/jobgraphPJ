# RAG 기법 실습 프로젝트 설계

**날짜:** 2026-06-05  
**상태:** 승인됨

---

## 개요

LangChain/LangGraph 기반으로 6가지 RAG 기법을 Jupyter 노트북으로 독립 실습하는 프로젝트.

## 기술 스택

- **언어:** Python 3.11+
- **RAG 프레임워크:** LangChain, LangGraph
- **벡터 DB:** ChromaDB (로컬, 설정 없이 사용)
- **LLM:** OpenAI GPT-4o, Anthropic Claude
- **임베딩:** OpenAI `text-embedding-3-small`
- **환경변수:** `.env` + `python-dotenv`

## 프로젝트 구조

```
pj1/
├── notebooks/
│   ├── 01_hybrid_reranking.ipynb
│   ├── 02_contextual_retrieval.ipynb
│   ├── 03_late_chunking.ipynb
│   ├── 04_smart_indexing.ipynb
│   ├── 05_graph_rag.ipynb
│   └── 06_agentic_rag.ipynb
├── data/
│   └── sample.txt
├── .env
└── requirements.txt
```

- `utils/` 없음 — 모든 노트북 완전 독립 실행 가능
- 공통 샘플 문서(`data/sample.txt`)만 공유

## 각 노트북 공통 흐름

```
1. import 및 라이브러리 확인
2. .env 로드
3. 샘플 문서 로드 및 청킹
4. 기법 구현 (메인 섹션)
5. 테스트 쿼리 실행 및 결과 출력
```

## 기법별 구현 명세

### 01. Hybrid Search + Reranking
- BM25(`rank-bm25`)와 ChromaDB 벡터 검색 결과를 RRF(Reciprocal Rank Fusion)로 결합
- Cross-Encoder(`sentence-transformers/cross-encoder/ms-marco-MiniLM-L-6-v2`)로 재정렬
- 출력: BM25 단독 / 벡터 단독 / 하이브리드+리랭킹 결과 비교

### 02. Contextual Retrieval
- 각 청크에 대해 Claude API로 "이 청크가 문서 전체에서 갖는 맥락" 설명 생성
- `[CONTEXT]\n{context}\n\n[CHUNK]\n{chunk}` 형태로 결합 후 ChromaDB에 저장
- 출력: 일반 청크 검색 vs 맥락 부착 청크 검색 결과 비교

### 03. Late Chunking
- HuggingFace `transformers`로 전체 문서를 한 번에 인코딩
- 토큰 경계 기준으로 hidden state를 분할 후 평균 풀링으로 청크 임베딩 생성
- 출력: 일반 청킹 임베딩 vs Late Chunking 임베딩 검색 결과 비교

### 04. Smart Indexing
- 각 청크를 LLM으로 요약 생성
- ChromaDB에 요약문 임베딩 저장 (metadata에 원본 청크 보관)
- 쿼리 시 요약으로 검색 → 원본 청크를 LLM 컨텍스트로 전달
- 출력: 일반 검색 vs 스마트 인덱싱 검색 결과 비교

### 05. Graph RAG
- LLM으로 청크에서 엔티티·관계 추출 (예: `(삼성전자) -[개발]-> (갤럭시)`)
- `networkx`로 지식 그래프 구축
- 쿼리 엔티티와 연결된 서브그래프 노드를 컨텍스트로 활용
- 출력: 벡터 검색 단독 vs Graph RAG 결과 비교

### 06. Agentic RAG
- LangGraph로 상태 머신 구성:
  - `retrieve` 노드: ChromaDB에서 검색
  - `grade` 노드: 검색 결과 관련성 판단
  - `rewrite` 노드: 쿼리 재작성 (관련성 낮을 때)
  - `generate` 노드: 최종 답변 생성
- 출력: 단계별 상태 변화 및 최종 답변

## 샘플 데이터

`data/sample.txt`: 영어 Wikipedia 수준 단락 5개 내외. 실습 초점이 기법에 있으므로 내용은 임의 선택.

## 의존성 (requirements.txt)

```
langchain
langchain-openai
langchain-anthropic
langchain-chroma
langgraph
chromadb
rank-bm25
sentence-transformers
transformers
torch
networkx
python-dotenv
openai
anthropic
```
