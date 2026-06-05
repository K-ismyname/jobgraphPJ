# RAG 기법 실습 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** LangChain/LangGraph 기반으로 6가지 RAG 기법을 독립 Jupyter 노트북으로 구현한다.

**Architecture:** 각 노트북은 완전히 독립 실행 가능하며, `data/sample.txt` 하나만 공유한다. 별도의 `utils/` 모듈 없이 모든 코드를 노트북 안에 직접 작성한다. ChromaDB를 로컬 벡터 DB로 사용한다.

**Tech Stack:** Python 3.11+, LangChain, LangGraph, ChromaDB, OpenAI API, Anthropic API, rank-bm25, sentence-transformers, transformers (PyTorch), NetworkX

---

## Task 0: 프로젝트 초기 설정

**Files:**
- Create: `requirements.txt`
- Create: `.env.template`
- Create: `data/sample.txt`

- [ ] **Step 1: requirements.txt 작성**

```
langchain>=0.3
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
matplotlib
python-dotenv
openai
anthropic
```

- [ ] **Step 2: .env.template 작성**

```
OPENAI_API_KEY=your_openai_key_here
ANTHROPIC_API_KEY=your_anthropic_key_here
```

- [ ] **Step 3: .env 파일 생성 (실제 키 입력)**

```bash
cp .env.template .env
# .env 파일을 열어서 실제 API 키 입력
```

- [ ] **Step 4: data/sample.txt 작성**

```
Machine learning is a branch of artificial intelligence that enables computers to learn from data and improve their performance on tasks without being explicitly programmed. It involves the development of algorithms and statistical models that allow systems to identify patterns and make decisions with minimal human intervention.

The field of machine learning encompasses several key approaches. Supervised learning involves training models on labeled datasets, where the algorithm learns to map inputs to outputs based on example input-output pairs. Common supervised learning algorithms include linear regression, decision trees, random forests, and neural networks.

Unsupervised learning deals with unlabeled data and aims to discover hidden patterns or structures within datasets. Clustering algorithms like K-means and hierarchical clustering group similar data points together, while dimensionality reduction techniques such as Principal Component Analysis help simplify complex datasets.

Deep learning, a subset of machine learning, uses artificial neural networks with many layers to model complex patterns in data. Convolutional Neural Networks excel at image recognition tasks, while Recurrent Neural Networks and Transformer architectures are widely used for natural language processing applications.

Machine learning has found applications across diverse industries. In healthcare, ML models assist in disease diagnosis and drug discovery. In finance, algorithms detect fraudulent transactions and optimize investment portfolios. E-commerce platforms use recommendation systems to suggest products. Autonomous vehicles rely on computer vision and reinforcement learning to navigate safely.
```

- [ ] **Step 5: 의존성 설치**

```bash
pip install -r requirements.txt
```

예상 출력: `Successfully installed ...` (오류 없이 완료)

- [ ] **Step 6: 커밋**

```bash
git add requirements.txt .env.template data/sample.txt
git commit -m "chore: 프로젝트 초기 설정"
```

---

## Task 1: Hybrid Search + Reranking 노트북

**Files:**
- Create: `notebooks/01_hybrid_reranking.ipynb`

- [ ] **Step 1: 노트북 생성 후 셀 1 — Import 및 환경 설정**

```python
from dotenv import load_dotenv
import os
load_dotenv("../.env")

from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma
from langchain.text_splitter import RecursiveCharacterTextSplitter
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder
import numpy as np

embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
cross_encoder = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
print("로드 완료")
```

예상 출력: `로드 완료`

- [ ] **Step 2: 셀 2 — 문서 로드 및 청킹**

```python
with open("../data/sample.txt", "r") as f:
    text = f.read()

splitter = RecursiveCharacterTextSplitter(chunk_size=300, chunk_overlap=50)
from langchain.schema import Document
docs = splitter.create_documents([text])
chunks = [doc.page_content for doc in docs]
print(f"총 청크 수: {len(chunks)}")
for i, c in enumerate(chunks):
    print(f"\n[{i}] {c[:80]}...")
```

예상 출력: `총 청크 수: 5~8` (sample.txt 길이에 따라 달라짐)

- [ ] **Step 3: 셀 3 — BM25 인덱스 구축**

```python
tokenized = [chunk.lower().split() for chunk in chunks]
bm25 = BM25Okapi(tokenized)
print(f"BM25 인덱스 구축 완료: {len(chunks)}개 문서")
```

예상 출력: `BM25 인덱스 구축 완료: ...개 문서`

- [ ] **Step 4: 셀 4 — ChromaDB 인덱스 구축**

```python
vectorstore = Chroma.from_documents(
    docs, embeddings, collection_name="hybrid_demo"
)
print(f"ChromaDB 인덱스 구축 완료")
```

예상 출력: `ChromaDB 인덱스 구축 완료`

- [ ] **Step 5: 셀 5 — RRF 하이브리드 검색 함수**

```python
def reciprocal_rank_fusion(rankings: list[list[int]], k: int = 60) -> list[tuple[int, float]]:
    scores = {}
    for ranking in rankings:
        for rank, idx in enumerate(ranking):
            scores[idx] = scores.get(idx, 0) + 1 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)

def hybrid_search(query: str, top_k: int = 5) -> list[tuple[str, float]]:
    # BM25 랭킹
    bm25_scores = bm25.get_scores(query.lower().split())
    bm25_ranking = np.argsort(bm25_scores)[::-1].tolist()

    # 벡터 랭킹
    vector_results = vectorstore.similarity_search_with_score(query, k=len(chunks))
    vector_ranking = []
    for r in vector_results:
        try:
            vector_ranking.append(chunks.index(r[0].page_content))
        except ValueError:
            pass

    # RRF 결합
    fused = reciprocal_rank_fusion([bm25_ranking, vector_ranking])
    return [(chunks[idx], score) for idx, score in fused[:top_k] if idx < len(chunks)]

print("hybrid_search 함수 정의 완료")
```

예상 출력: `hybrid_search 함수 정의 완료`

- [ ] **Step 6: 셀 6 — Cross-Encoder 리랭킹 함수**

```python
def rerank(query: str, candidates: list[tuple[str, float]]) -> list[tuple[str, float]]:
    if not candidates:
        return []
    pairs = [(query, text) for text, _ in candidates]
    scores = cross_encoder.predict(pairs)
    reranked = sorted(
        zip([c[0] for c in candidates], scores),
        key=lambda x: x[1],
        reverse=True
    )
    return reranked

print("rerank 함수 정의 완료")
```

예상 출력: `rerank 함수 정의 완료`

- [ ] **Step 7: 셀 7 — 결과 비교 실행**

```python
QUERY = "What are the applications of machine learning in healthcare?"

print("=" * 50)
print("BM25 단독")
print("=" * 50)
bm25_scores = bm25.get_scores(QUERY.lower().split())
for i in np.argsort(bm25_scores)[::-1][:3]:
    print(f"[score: {bm25_scores[i]:.3f}] {chunks[i][:120]}\n")

print("=" * 50)
print("벡터 검색 단독")
print("=" * 50)
for doc, score in vectorstore.similarity_search_with_score(QUERY, k=3):
    print(f"[distance: {score:.4f}] {doc.page_content[:120]}\n")

print("=" * 50)
print("하이브리드 (RRF)")
print("=" * 50)
hybrid_results = hybrid_search(QUERY)
for text, score in hybrid_results[:3]:
    print(f"[rrf: {score:.4f}] {text[:120]}\n")

print("=" * 50)
print("하이브리드 + Cross-Encoder 리랭킹")
print("=" * 50)
reranked = rerank(QUERY, hybrid_results)
for text, score in reranked[:3]:
    print(f"[ce_score: {score:.3f}] {text[:120]}\n")
```

예상 출력: 4가지 방법의 검색 결과가 각각 출력됨. 리랭킹 결과가 가장 관련도 높은 문서를 상위에 위치시켜야 함.

- [ ] **Step 8: 커밋**

```bash
git add notebooks/01_hybrid_reranking.ipynb
git commit -m "feat: 01 Hybrid Search + Reranking 노트북 구현"
```

---

## Task 2: Contextual Retrieval 노트북

**Files:**
- Create: `notebooks/02_contextual_retrieval.ipynb`

- [ ] **Step 1: 셀 1 — Import 및 환경 설정**

```python
from dotenv import load_dotenv
load_dotenv("../.env")

from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.schema import Document
from anthropic import Anthropic

client = Anthropic()
embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
print("로드 완료")
```

예상 출력: `로드 완료`

- [ ] **Step 2: 셀 2 — 문서 로드 및 청킹**

```python
with open("../data/sample.txt", "r") as f:
    full_text = f.read()

splitter = RecursiveCharacterTextSplitter(chunk_size=300, chunk_overlap=50)
docs = splitter.create_documents([full_text])
print(f"총 청크 수: {len(docs)}")
```

예상 출력: `총 청크 수: 5~8`

- [ ] **Step 3: 셀 3 — 맥락 생성 함수 정의**

```python
def generate_context(full_doc: str, chunk: str) -> str:
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=150,
        messages=[{
            "role": "user",
            "content": f"""<document>
{full_doc}
</document>

위 문서에서 아래 청크가 전체 문서에서 갖는 맥락을 1-2문장으로 설명해줘. 청크 내용을 요약하지 말고, 문서 전체에서 이 청크의 위치와 역할을 설명해.

<chunk>
{chunk}
</chunk>

설명만 반환해."""
        }]
    )
    return response.content[0].text.strip()

print("generate_context 함수 정의 완료")
```

예상 출력: `generate_context 함수 정의 완료`

- [ ] **Step 4: 셀 4 — 맥락 생성 실행 (API 호출)**

```python
contextual_docs = []
for i, doc in enumerate(docs):
    context = generate_context(full_text, doc.page_content)
    contextual_content = f"[맥락] {context}\n\n{doc.page_content}"
    contextual_docs.append(Document(page_content=contextual_content))
    print(f"청크 {i+1}/{len(docs)} 처리 완료")
    print(f"  맥락: {context[:80]}...\n")

print("전체 맥락 생성 완료")
```

예상 출력: 각 청크에 대해 Claude가 생성한 맥락 설명이 출력됨.

- [ ] **Step 5: 셀 5 — ChromaDB에 두 버전 저장**

```python
plain_store = Chroma.from_documents(
    docs, embeddings, collection_name="plain_chunks"
)
contextual_store = Chroma.from_documents(
    contextual_docs, embeddings, collection_name="contextual_chunks"
)
print("두 벡터 DB 저장 완료")
```

예상 출력: `두 벡터 DB 저장 완료`

- [ ] **Step 6: 셀 6 — 결과 비교**

```python
QUERY = "What methods are used for pattern recognition in data?"

print("=" * 50)
print("일반 청크 검색")
print("=" * 50)
for doc, score in plain_store.similarity_search_with_score(QUERY, k=3):
    print(f"[distance: {score:.4f}]\n{doc.page_content[:200]}\n")

print("=" * 50)
print("맥락 부착 청크 검색")
print("=" * 50)
for doc, score in contextual_store.similarity_search_with_score(QUERY, k=3):
    print(f"[distance: {score:.4f}]\n{doc.page_content[:250]}\n")
```

예상 출력: 맥락 부착 버전이 더 낮은 distance(더 높은 유사도)로 관련 문서를 검색해야 함.

- [ ] **Step 7: 커밋**

```bash
git add notebooks/02_contextual_retrieval.ipynb
git commit -m "feat: 02 Contextual Retrieval 노트북 구현"
```

---

## Task 3: Late Chunking 노트북

**Files:**
- Create: `notebooks/03_late_chunking.ipynb`

- [ ] **Step 1: 셀 1 — Import 및 모델 로드**

```python
from dotenv import load_dotenv
load_dotenv("../.env")

from transformers import AutoTokenizer, AutoModel
import torch
import numpy as np
import chromadb
from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.schema import Document

MODEL_NAME = "jinaai/jina-embeddings-v2-base-en"
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)
model = AutoModel.from_pretrained(MODEL_NAME, trust_remote_code=True)
model.eval()
print("Jina 모델 로드 완료 (첫 실행 시 다운로드 시간 소요)")
```

예상 출력: `Jina 모델 로드 완료 ...` (처음 실행 시 모델 다운로드 발생)

- [ ] **Step 2: 셀 2 — 문서 로드**

```python
with open("../data/sample.txt", "r") as f:
    full_text = f.read()
print(f"문서 길이: {len(full_text)} 문자")
```

예상 출력: `문서 길이: 1700~2000 문자`

- [ ] **Step 3: 셀 3 — Late Chunking 함수 정의**

```python
def late_chunking(text: str, chunk_size_chars: int = 350) -> list[tuple[str, np.ndarray]]:
    """
    전체 문서를 한번에 인코딩 → 토큰 hidden states를 청크 단위로 평균 풀링.
    일반 청킹과 달리 각 청크 임베딩이 전체 문서 맥락을 반영한다.
    """
    inputs = tokenizer(
        text,
        return_tensors="pt",
        truncation=True,
        max_length=8192,
        return_offsets_mapping=True
    )
    offset_mapping = inputs.pop("offset_mapping")[0]  # (seq_len, 2)

    with torch.no_grad():
        outputs = model(**inputs)

    hidden_states = outputs.last_hidden_state[0]  # (seq_len, hidden_dim)

    results = []
    start_char = 0

    while start_char < len(text):
        end_char = min(start_char + chunk_size_chars, len(text))
        # 단어 경계로 조정
        if end_char < len(text):
            last_space = text.rfind(" ", start_char, end_char)
            if last_space > start_char:
                end_char = last_space

        chunk_text = text[start_char:end_char].strip()

        # 해당 char 범위에 속하는 토큰 인덱스
        token_mask = (
            (offset_mapping[:, 0] >= start_char) &
            (offset_mapping[:, 1] <= end_char) &
            (offset_mapping[:, 0] != offset_mapping[:, 1])  # 특수 토큰 제외
        )

        if token_mask.sum() > 0 and chunk_text:
            chunk_emb = hidden_states[token_mask].mean(dim=0).numpy()
            results.append((chunk_text, chunk_emb))

        start_char = end_char

    return results

print("late_chunking 함수 정의 완료")
```

예상 출력: `late_chunking 함수 정의 완료`

- [ ] **Step 4: 셀 4 — Late Chunking 실행 및 ChromaDB 저장**

```python
chunks_with_embeddings = late_chunking(full_text)
print(f"Late Chunking 결과: {len(chunks_with_embeddings)}개 청크\n")

# 커스텀 임베딩으로 ChromaDB에 저장
chroma_client = chromadb.Client()
late_collection = chroma_client.get_or_create_collection("late_chunking")

for i, (chunk_text, emb) in enumerate(chunks_with_embeddings):
    late_collection.add(
        ids=[f"chunk_{i}"],
        documents=[chunk_text],
        embeddings=[emb.tolist()]
    )
    print(f"[{i}] {chunk_text[:80]}...")

print("\nLate Chunking DB 저장 완료")
```

예상 출력: 각 청크 텍스트가 출력되고 `Late Chunking DB 저장 완료` 메시지

- [ ] **Step 5: 셀 5 — 비교용 일반 청킹 DB 구축**

```python
openai_embeddings = OpenAIEmbeddings(model="text-embedding-3-small")

splitter = RecursiveCharacterTextSplitter(chunk_size=350, chunk_overlap=50)
plain_docs = splitter.create_documents([full_text])
plain_store = Chroma.from_documents(
    plain_docs, openai_embeddings, collection_name="plain_chunks_late"
)
print(f"일반 청킹 DB 저장 완료: {len(plain_docs)}개 청크")
```

예상 출력: `일반 청킹 DB 저장 완료: ...개 청크`

- [ ] **Step 6: 셀 6 — 결과 비교**

```python
QUERY = "neural networks for image recognition"

# Late Chunking 쿼리 임베딩 (같은 Jina 모델 사용)
query_inputs = tokenizer(QUERY, return_tensors="pt")
with torch.no_grad():
    query_output = model(**query_inputs)
query_emb = query_output.last_hidden_state[0].mean(dim=0).numpy()

print("=" * 50)
print("Late Chunking 검색 (Jina 임베딩, 전체 문서 맥락 반영)")
print("=" * 50)
late_results = late_collection.query(
    query_embeddings=[query_emb.tolist()],
    n_results=3
)
for doc, dist in zip(late_results["documents"][0], late_results["distances"][0]):
    print(f"[distance: {dist:.4f}]\n{doc[:150]}\n")

print("=" * 50)
print("일반 청킹 검색 (OpenAI 임베딩, 청크 단독 맥락)")
print("=" * 50)
for doc, score in plain_store.similarity_search_with_score(QUERY, k=3):
    print(f"[distance: {score:.4f}]\n{doc.page_content[:150]}\n")
```

예상 출력: 두 방법의 검색 결과 비교. Late Chunking이 더 문맥적으로 일관된 결과를 반환해야 함.

- [ ] **Step 7: 커밋**

```bash
git add notebooks/03_late_chunking.ipynb
git commit -m "feat: 03 Late Chunking 노트북 구현"
```

---

## Task 4: Smart Indexing 노트북

**Files:**
- Create: `notebooks/04_smart_indexing.ipynb`

- [ ] **Step 1: 셀 1 — Import 및 환경 설정**

```python
from dotenv import load_dotenv
load_dotenv("../.env")

from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_chroma import Chroma
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.schema import Document
from langchain_core.prompts import ChatPromptTemplate

llm = ChatOpenAI(model="gpt-4o-mini")
embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
print("로드 완료")
```

예상 출력: `로드 완료`

- [ ] **Step 2: 셀 2 — 문서 로드 및 청킹**

```python
with open("../data/sample.txt", "r") as f:
    full_text = f.read()

splitter = RecursiveCharacterTextSplitter(chunk_size=300, chunk_overlap=50)
docs = splitter.create_documents([full_text])
print(f"총 청크 수: {len(docs)}")
```

예상 출력: `총 청크 수: 5~8`

- [ ] **Step 3: 셀 3 — 요약 생성**

```python
def summarize_chunk(chunk: str) -> str:
    response = llm.invoke(
        f"다음 텍스트를 핵심만 담아 1문장으로 요약해줘:\n\n{chunk}"
    )
    return response.content.strip()

summaries = []
for i, doc in enumerate(docs):
    summary = summarize_chunk(doc.page_content)
    summaries.append(summary)
    print(f"청크 {i+1}: {summary}")

print("\n요약 생성 완료")
```

예상 출력: 각 청크의 1문장 요약이 출력됨.

- [ ] **Step 4: 셀 4 — 스마트 인덱스 구축**

```python
# 요약 임베딩으로 저장, metadata에 원본 청크 보관
summary_docs = [
    Document(
        page_content=summary,
        metadata={"original": doc.page_content, "chunk_idx": i}
    )
    for i, (doc, summary) in enumerate(zip(docs, summaries))
]

smart_store = Chroma.from_documents(
    summary_docs, embeddings, collection_name="smart_index"
)

# 비교용: 원본 청크 직접 임베딩
plain_store = Chroma.from_documents(
    docs, embeddings, collection_name="plain_index_smart"
)

print("스마트 인덱스 및 일반 인덱스 구축 완료")
```

예상 출력: `스마트 인덱스 및 일반 인덱스 구축 완료`

- [ ] **Step 5: 셀 5 — 검색 결과 비교**

```python
QUERY = "How does unsupervised learning differ from supervised learning?"

print("=" * 50)
print("일반 검색 (원본 청크 임베딩)")
print("=" * 50)
for doc, score in plain_store.similarity_search_with_score(QUERY, k=3):
    print(f"[distance: {score:.4f}]\n{doc.page_content[:150]}\n")

print("=" * 50)
print("스마트 인덱싱 (요약으로 검색 → 원본 전달)")
print("=" * 50)
smart_results = smart_store.similarity_search_with_score(QUERY, k=3)
for doc, score in smart_results:
    print(f"[distance: {score:.4f}]")
    print(f"검색된 요약: {doc.page_content}")
    print(f"LLM에 전달할 원본: {doc.metadata['original'][:150]}\n")
```

예상 출력: 스마트 인덱싱이 더 낮은 distance로 관련 청크를 찾고, 원본 전체가 함께 표시됨.

- [ ] **Step 6: 셀 6 — 원본 청크로 RAG 실행**

```python
context = "\n\n".join([
    doc.metadata["original"] for doc, _ in smart_results
])

prompt = ChatPromptTemplate.from_messages([
    ("human", "다음 컨텍스트를 참고해서 질문에 답해줘.\n\n컨텍스트:\n{context}\n\n질문: {query}")
])
chain = prompt | llm
response = chain.invoke({"context": context, "query": QUERY})

print("=" * 50)
print("LLM 최종 답변 (스마트 인덱싱 컨텍스트 사용)")
print("=" * 50)
print(response.content)
```

예상 출력: 질문에 맞는 구체적인 답변이 생성됨.

- [ ] **Step 7: 커밋**

```bash
git add notebooks/04_smart_indexing.ipynb
git commit -m "feat: 04 Smart Indexing 노트북 구현"
```

---

## Task 5: Graph RAG 노트북

**Files:**
- Create: `notebooks/05_graph_rag.ipynb`

- [ ] **Step 1: 셀 1 — Import 및 환경 설정**

```python
from dotenv import load_dotenv
load_dotenv("../.env")

import networkx as nx
import json
import matplotlib.pyplot as plt
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_chroma import Chroma
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.schema import Document

llm = ChatOpenAI(model="gpt-4o-mini")
embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
print("로드 완료")
```

예상 출력: `로드 완료`

- [ ] **Step 2: 셀 2 — 문서 로드 및 청킹**

```python
with open("../data/sample.txt", "r") as f:
    full_text = f.read()

splitter = RecursiveCharacterTextSplitter(chunk_size=300, chunk_overlap=50)
docs = splitter.create_documents([full_text])
print(f"총 청크 수: {len(docs)}")
```

예상 출력: `총 청크 수: 5~8`

- [ ] **Step 3: 셀 3 — 엔티티·관계 추출**

```python
def extract_entities_relations(chunk: str) -> dict:
    response = llm.invoke(
        f"""다음 텍스트에서 주요 엔티티(개념, 기술, 방법론)와 관계를 추출해줘.
반드시 JSON만 반환해. 다른 텍스트 없이 JSON만.

텍스트: {chunk}

형식:
{{"entities": ["엔티티1", "엔티티2"], "relations": [["엔티티1", "관계동사", "엔티티2"]]}}"""
    )
    try:
        content = response.content.strip()
        if "```" in content:
            content = content.split("```")[1].replace("json", "").strip()
        return json.loads(content)
    except Exception as e:
        print(f"파싱 실패: {e}")
        return {"entities": [], "relations": []}

extractions = []
for i, doc in enumerate(docs):
    ext = extract_entities_relations(doc.page_content)
    extractions.append(ext)
    print(f"청크 {i+1}: 엔티티 {len(ext['entities'])}개, 관계 {len(ext['relations'])}개")
    print(f"  엔티티: {ext['entities']}")
```

예상 출력: 각 청크에서 추출된 엔티티와 관계 수 출력.

- [ ] **Step 4: 셀 4 — NetworkX 그래프 구축**

```python
G = nx.DiGraph()

for i, (doc, ext) in enumerate(zip(docs, extractions)):
    for entity in ext["entities"]:
        if entity not in G:
            G.add_node(entity, chunk_idx=i, chunk_text=doc.page_content)

    for rel in ext["relations"]:
        if len(rel) == 3 and rel[0] in G.nodes and rel[2] in G.nodes:
            G.add_edge(rel[0], rel[2], relation=rel[1], chunk_idx=i)

print(f"그래프 구축 완료: 노드 {G.number_of_nodes()}개, 엣지 {G.number_of_edges()}개")
print(f"노드 목록: {list(G.nodes())}")
```

예상 출력: 노드와 엣지 수, 노드 목록 출력.

- [ ] **Step 5: 셀 5 — 그래프 시각화**

```python
plt.figure(figsize=(14, 9))
pos = nx.spring_layout(G, seed=42, k=2)
nx.draw(
    G, pos,
    with_labels=True,
    node_color="lightblue",
    node_size=2000,
    font_size=8,
    font_weight="bold",
    arrows=True,
    arrowsize=20
)
edge_labels = nx.get_edge_attributes(G, "relation")
nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels, font_size=7)
plt.title("Knowledge Graph — RAG 실습")
plt.tight_layout()
plt.savefig("../knowledge_graph.png", dpi=100, bbox_inches="tight")
plt.show()
print("그래프 저장: knowledge_graph.png")
```

예상 출력: 그래프 시각화 이미지 표시 및 파일 저장.

- [ ] **Step 6: 셀 6 — 그래프 기반 검색 함수**

```python
def graph_search(query: str, top_k: int = 3) -> list[str]:
    query_words = set(query.lower().split())
    
    # 쿼리 단어와 매칭되는 노드 찾기
    matching_nodes = [
        node for node in G.nodes()
        if any(word in node.lower() for word in query_words)
    ]
    
    if not matching_nodes:
        # 매칭 없으면 LLM으로 관련 엔티티 추출
        response = llm.invoke(
            f"다음 쿼리에서 핵심 개념 키워드를 3개 추출해. 키워드만 쉼표로 구분해서 반환:\n{query}"
        )
        keywords = [k.strip().lower() for k in response.content.split(",")]
        matching_nodes = [
            node for node in G.nodes()
            if any(kw in node.lower() for kw in keywords)
        ]
    
    print(f"매칭 노드: {matching_nodes}")
    
    # 1-hop 이웃 포함 청크 수집
    related_chunk_indices = set()
    for node in matching_nodes:
        related_chunk_indices.add(G.nodes[node].get("chunk_idx", -1))
        for neighbor in list(G.successors(node)) + list(G.predecessors(node)):
            related_chunk_indices.add(G.nodes[neighbor].get("chunk_idx", -1))
    
    related_chunk_indices.discard(-1)
    return [docs[idx].page_content for idx in list(related_chunk_indices)[:top_k]]

print("graph_search 함수 정의 완료")
```

예상 출력: `graph_search 함수 정의 완료`

- [ ] **Step 7: 셀 7 — 벡터 검색 vs Graph RAG 비교**

```python
vectorstore = Chroma.from_documents(
    docs, embeddings, collection_name="graph_rag_plain"
)

QUERY = "deep learning neural networks"

print("=" * 50)
print("벡터 검색 단독")
print("=" * 50)
for doc, score in vectorstore.similarity_search_with_score(QUERY, k=3):
    print(f"[distance: {score:.4f}]\n{doc.page_content[:150]}\n")

print("=" * 50)
print("Graph RAG (엔티티 그래프 경유)")
print("=" * 50)
graph_results = graph_search(QUERY)
if graph_results:
    for i, text in enumerate(graph_results):
        print(f"[{i+1}]\n{text[:150]}\n")
else:
    print("매칭 엔티티 없음 — 쿼리를 바꿔서 시도해보세요")
```

예상 출력: 벡터 검색과 그래프 검색 결과 비교.

- [ ] **Step 8: 커밋**

```bash
git add notebooks/05_graph_rag.ipynb knowledge_graph.png
git commit -m "feat: 05 Graph RAG 노트북 구현"
```

---

## Task 6: Agentic RAG 노트북

**Files:**
- Create: `notebooks/06_agentic_rag.ipynb`

- [ ] **Step 1: 셀 1 — Import 및 환경 설정**

```python
from dotenv import load_dotenv
load_dotenv("../.env")

from typing import TypedDict, List
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_chroma import Chroma
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.schema import Document
from langgraph.graph import StateGraph, END

llm = ChatOpenAI(model="gpt-4o-mini")
embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
print("로드 완료")
```

예상 출력: `로드 완료`

- [ ] **Step 2: 셀 2 — 벡터 DB 구축**

```python
with open("../data/sample.txt", "r") as f:
    full_text = f.read()

splitter = RecursiveCharacterTextSplitter(chunk_size=300, chunk_overlap=50)
docs = splitter.create_documents([full_text])
vectorstore = Chroma.from_documents(
    docs, embeddings, collection_name="agentic_rag"
)
retriever = vectorstore.as_retriever(search_kwargs={"k": 3})
print(f"벡터 DB 구축 완료: {len(docs)}개 청크")
```

예상 출력: `벡터 DB 구축 완료: ...개 청크`

- [ ] **Step 3: 셀 3 — State 정의**

```python
class AgentState(TypedDict):
    query: str
    documents: List[Document]
    generation: str
    retry_count: int

print("AgentState 정의 완료")
```

예상 출력: `AgentState 정의 완료`

- [ ] **Step 4: 셀 4 — 노드 함수 정의**

```python
def retrieve(state: AgentState) -> AgentState:
    print(f"\n[retrieve] 쿼리: '{state['query']}'")
    retrieved_docs = retriever.invoke(state["query"])
    print(f"[retrieve] {len(retrieved_docs)}개 문서 검색됨")
    return {**state, "documents": retrieved_docs}

def grade_documents(state: AgentState) -> AgentState:
    query = state["query"]
    relevant = []
    for doc in state["documents"]:
        response = llm.invoke(
            f"다음 문서가 질문과 관련있으면 'yes', 없으면 'no'만 답해.\n\n질문: {query}\n\n문서: {doc.page_content}"
        )
        if "yes" in response.content.lower():
            relevant.append(doc)
    print(f"[grade] {len(state['documents'])}개 중 {len(relevant)}개 관련 문서 통과")
    return {**state, "documents": relevant}

def decide_to_generate(state: AgentState) -> str:
    if len(state["documents"]) == 0 and state["retry_count"] < 2:
        print(f"[decide] 관련 문서 없음 → 쿼리 재작성 (시도 {state['retry_count']+1}/2)")
        return "rewrite"
    print(f"[decide] {'관련 문서 ' + str(len(state['documents'])) + '개 확인' if state['documents'] else '최대 재시도 초과'} → 답변 생성")
    return "generate"

def rewrite_query(state: AgentState) -> AgentState:
    response = llm.invoke(
        f"다음 검색 쿼리로 좋은 결과를 얻지 못했어. 같은 의도를 다른 표현으로 바꿔줘. 쿼리만 반환해:\n\n{state['query']}"
    )
    new_query = response.content.strip()
    print(f"[rewrite] '{state['query']}' → '{new_query}'")
    return {**state, "query": new_query, "retry_count": state["retry_count"] + 1}

def generate(state: AgentState) -> AgentState:
    context = "\n\n".join([doc.page_content for doc in state["documents"]])
    if not context:
        context = "관련 문서를 찾지 못했습니다. 일반 지식으로 답해주세요."

    response = llm.invoke(
        f"다음 컨텍스트를 참고해서 질문에 상세히 답해줘.\n\n컨텍스트:\n{context}\n\n질문: {state['query']}"
    )
    print(f"[generate] 답변 생성 완료")
    return {**state, "generation": response.content}

print("노드 함수 4개 정의 완료: retrieve, grade_documents, rewrite_query, generate")
```

예상 출력: `노드 함수 4개 정의 완료: retrieve, grade_documents, rewrite_query, generate`

- [ ] **Step 5: 셀 5 — LangGraph 빌드**

```python
workflow = StateGraph(AgentState)

workflow.add_node("retrieve", retrieve)
workflow.add_node("grade", grade_documents)
workflow.add_node("rewrite", rewrite_query)
workflow.add_node("generate", generate)

workflow.set_entry_point("retrieve")
workflow.add_edge("retrieve", "grade")
workflow.add_conditional_edges(
    "grade",
    decide_to_generate,
    {"rewrite": "rewrite", "generate": "generate"}
)
workflow.add_edge("rewrite", "retrieve")
workflow.add_edge("generate", END)

app = workflow.compile()
print("LangGraph 빌드 완료")
print("흐름: retrieve → grade → (rewrite → retrieve)* → generate → END")
```

예상 출력: `LangGraph 빌드 완료`

- [ ] **Step 6: 셀 6 — 실행 및 결과 확인**

```python
QUERY = "What are deep learning applications in healthcare?"

print("=" * 50)
print(f"쿼리: {QUERY}")
print("=" * 50)

result = app.invoke({
    "query": QUERY,
    "documents": [],
    "generation": "",
    "retry_count": 0
})

print("\n" + "=" * 50)
print("최종 결과")
print("=" * 50)
print(f"최종 쿼리: {result['query']}")
print(f"사용 문서 수: {len(result['documents'])}")
print(f"\n답변:\n{result['generation']}")
```

예상 출력: 각 노드 실행 로그([retrieve], [grade], [decide], [generate])가 출력된 후 최종 답변 생성.

- [ ] **Step 7: 셀 7 — 재검색 발동 테스트**

```python
# 관련 문서가 없을 가능성이 높은 쿼리로 rewrite 노드 발동 확인
QUERY_OUT_OF_SCOPE = "quantum computing cryptography"

print("=" * 50)
print(f"쿼리 (범위 밖): {QUERY_OUT_OF_SCOPE}")
print("=" * 50)

result2 = app.invoke({
    "query": QUERY_OUT_OF_SCOPE,
    "documents": [],
    "generation": "",
    "retry_count": 0
})

print(f"\n최종 쿼리: {result2['query']}")
print(f"사용 문서 수: {len(result2['documents'])}")
print(f"\n답변:\n{result2['generation']}")
```

예상 출력: `[rewrite]` 노드가 발동되어 쿼리가 변환된 후 재검색하는 과정이 로그에 표시됨.

- [ ] **Step 8: 커밋**

```bash
git add notebooks/06_agentic_rag.ipynb
git commit -m "feat: 06 Agentic RAG 노트북 구현"
```

---

## 셀프 리뷰 체크리스트

- [x] 스펙 커버리지: 6개 기법 모두 태스크로 구현됨
- [x] 플레이스홀더 없음: 모든 셀에 실제 실행 가능한 코드 포함
- [x] 타입 일관성: `AgentState`, `Document`, `hybrid_search` 등 타입/함수명이 태스크 내에서 일관됨
- [x] 독립 실행 가능: 각 노트북이 `load_dotenv`부터 시작해 완전히 독립적
- [x] ChromaDB 충돌 방지: 각 노트북이 서로 다른 `collection_name` 사용
