# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트 목적

다양한 RAG(Retrieval-Augmented Generation) 기법을 실습하는 프로젝트. 각 기법을 독립 Jupyter 노트북으로 구현하고 비교한다.

**실습 대상 기법:**
- Hybrid Search + Reranking
- Contextual Retrieval (Anthropic 방식 — 청크 앞에 컨텍스트 설명 부착)
- Late Chunking (임베딩 후 청킹)
- Smart Indexing (요약 검색 + 원본 전달)
- Graph RAG (Neo4j 또는 NetworkX 기반 지식 그래프)
- Agentic RAG (LangGraph 기반 멀티스텝 검색 에이전트)

## 기술 스택

- **언어/환경:** Python 3.11+, Jupyter Notebook
- **LLM:** OpenAI GPT-4o, Anthropic Claude (`openai`, `anthropic` SDK)
- **RAG 프레임워크:** LangChain, LangGraph
- **벡터 DB:** Qdrant (기본), ChromaDB (경량 로컬 테스트용)
- **그래프 DB:** Neo4j (Graph RAG), NetworkX (경량 대안)
- **임베딩:** `sentence-transformers`, OpenAI `text-embedding-3-small`
- **BM25:** `rank-bm25`
- **리랭킹:** Cohere Rerank 또는 Cross-Encoder (`sentence-transformers`)
- **환경변수:** `.env` 파일 (`python-dotenv`)

## 디렉토리 구조 (예정)

```
pj1/
├── notebooks/          # 기법별 Jupyter 노트북
│   ├── 01_hybrid_reranking.ipynb
│   ├── 02_contextual_retrieval.ipynb
│   ├── 03_late_chunking.ipynb
│   ├── 04_smart_indexing.ipynb
│   ├── 05_graph_rag.ipynb
│   └── 06_agentic_rag.ipynb
├── data/               # 실습용 샘플 문서
├── utils/              # 공통 헬퍼 (청킹, 임베딩 래퍼 등)
├── .env                # API 키 (gitignore)
└── requirements.txt
```

## 개발 방식

각 노트북은 독립 실행 가능하게 작성한다. 공통 로직(청킹, 벡터 저장, 검색)은 `utils/`로 분리하되, 노트북 내에서 인라인으로 먼저 작성하고 반복될 때만 추출한다.

## 환경 설정

```bash
# 의존성 설치
pip install -r requirements.txt

# .env 파일에 필요한 키
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
COHERE_API_KEY=...       # 리랭킹 사용 시
NEO4J_URI=...            # Graph RAG 사용 시
NEO4J_USERNAME=...
NEO4J_PASSWORD=...
```

## 각 기법 핵심 포인트

| 기법 | 핵심 | 주의사항 |
|------|------|----------|
| Hybrid + Reranking | BM25 + 벡터 점수 결합 후 Cross-Encoder 재정렬 | α 가중치 튜닝 필요 |
| Contextual Retrieval | 청크마다 LLM으로 맥락 설명 생성 후 앞에 붙임 | 사전 처리 비용 높음 |
| Late Chunking | 전체 문서 임베딩 후 토큰 경계로 청킹 | long-context 모델 필요 |
| Smart Indexing | 요약본으로 검색, 원본 청크를 LLM에 전달 | 인덱스 2개 관리 |
| Graph RAG | 엔티티·관계 추출 → 그래프 구축 → 서브그래프 검색 | 구축 비용 높음, 문서 변경 시 재구축 |
| Agentic RAG | LangGraph로 검색·판단·재검색 루프 구성 | 토큰 소비량 많음 |
