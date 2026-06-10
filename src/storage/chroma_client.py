# 공고·이력서 텍스트를 Contextual Hybrid(BM25+Dense+CrossEncoder) 방식으로 저장·검색하는 클라이언트
from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import chromadb
from chromadb.utils import embedding_functions
from rank_bm25 import BM25Okapi

if TYPE_CHECKING:
    from sentence_transformers import CrossEncoder
    from openai import OpenAI

_CROSS_ENCODER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
_CONTEXT_PROMPT = """\
아래는 채용공고 전문입니다:
<document>
{full_doc}
</document>

아래는 그 중 한 섹션입니다:
<chunk>
{chunk}
</chunk>

이 섹션이 전체 공고에서 어떤 역할인지 1-2문장으로 설명하세요.
(예: "이 구절은 Stripe의 Senior ML Engineer 공고 필수 요건 섹션으로, \
LLM 파인튜닝과 프로덕션 배포 경험을 명시적으로 요구한다.")
코드 펜스나 추가 설명 없이 설명문만 출력하세요."""

ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_PERSIST_DIR = str(ROOT / "data" / "chroma")
_COLLECTION_NAME = "job_sections"


class ChromaClient:
    def __init__(self, persist_dir: str = _DEFAULT_PERSIST_DIR) -> None:
        ef = self._build_embedding_function()
        self._client = chromadb.PersistentClient(path=persist_dir)
        self._col = self._client.get_or_create_collection(
            name=_COLLECTION_NAME,
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )
        # BM25 인덱스 + 메타 캐시는 첫 검색 시 lazily 구축
        self._bm25: BM25Okapi | None = None
        self._bm25_ids: list[str] = []
        self._bm25_meta: list[dict] = []
        # Cross-encoder는 첫 rerank 호출 시 lazy load (모델 ~80MB)
        self._cross_encoder: "CrossEncoder | None" = None

    # ── 인덱싱 ──────────────────────────────────────────────────

    def ingest_posting(self, job: dict, openai_client: "OpenAI | None" = None) -> int:
        """공고 1개의 섹션을 Chroma에 적재. 추가된 문서 수 반환.

        openai_client 가 있으면 각 청크에 LLM 생성 문맥 설명을 prepend한다
        (Anthropic Contextual Retrieval 방식). 없으면 메타데이터 헤더만 사용.
        required/preferred 섹션이 있으면 각각 별도 문서로 저장.
        섹션이 없으면 text_clean 전체를 fallback으로 사용.
        """
        added = 0
        has_section = False
        full_doc = job.get("text_clean", "")[:2000]  # 문맥 생성용 전체 공고 (토큰 절약)

        for section_type in ("required", "preferred"):
            text = job.get(f"{section_type}_section", "").strip()
            if not text:
                continue
            has_section = True
            added += self._upsert_doc(job, section_type, text, full_doc, openai_client)

        if not has_section:
            fallback_text = job.get("bullet_section", "").strip()
            fallback_type = "bullet"
            if not fallback_text:
                fallback_text = job.get("text_clean", "").strip()[:3000]
                fallback_type = "full_text"
            if fallback_text:
                added += self._upsert_doc(job, fallback_type, fallback_text, full_doc, openai_client)

        if added:
            self._bm25 = None
        return added

    def _upsert_doc(
        self,
        job: dict,
        section_type: str,
        text: str,
        full_doc: str = "",
        openai_client: "OpenAI | None" = None,
    ) -> int:
        doc_id = f"{job['id']}_{section_type}"

        if openai_client and full_doc:
            # Contextual Retrieval: LLM이 청크의 문맥을 1-2문장으로 설명
            llm_context = self._generate_context(full_doc, text, openai_client)
            context_doc = f"{llm_context}\n\n{text}"
        else:
            # fallback: 메타데이터 헤더만 prepend
            context_doc = f"[{job['title']} @ {job['company']} | {section_type}] {text}"

        self._col.upsert(
            ids=[doc_id],
            documents=[context_doc],
            metadatas=[{
                "source_id": str(job["id"]),
                "job_title": job["title"],
                "company": job.get("company", ""),
                "section_type": section_type,
                "original_text": text,
            }],
        )
        return 1

    def _generate_context(self, full_doc: str, chunk: str, client: "OpenAI") -> str:
        """LLM으로 청크의 문맥 설명 생성. 실패 시 빈 문자열 반환."""
        try:
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{
                    "role": "user",
                    "content": _CONTEXT_PROMPT.format(full_doc=full_doc, chunk=chunk[:800]),
                }],
                max_tokens=120,
                temperature=0,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            print(f"[warn] 문맥 생성 실패: {e}")
            return ""

    def ingest_resume(self, owner: str, sections: list[dict]) -> int:
        """이력서 섹션을 Chroma에 적재. sections: [{title, text}] 형태.
        추가된 문서 수 반환."""
        added = 0
        for section in sections:
            text = section.get("text", "").strip()
            if not text:
                continue

            doc_id = f"resume_{owner}_{section['title']}"
            context_doc = f"[Resume | {owner} | {section['title']}] {text}"

            self._col.upsert(
                ids=[doc_id],
                documents=[context_doc],
                metadatas=[{
                    "source_id": f"resume_{owner}",
                    "job_title": "",
                    "company": owner,
                    "section_type": "resume",
                    "original_text": text,
                }],
            )
            added += 1

        if added:
            self._bm25 = None
        return added

    # ── 검색 ────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        n_results: int = 5,
        section_type: str | None = None,
        source_ids: list[str] | None = None,
        rerank: bool = True,
    ) -> list[dict]:
        """Hybrid(BM25 + Dense + CrossEncoder) 검색.

        section_type, source_ids를 Chroma 메타데이터 필터로 적용한다.
        - source_ids: Neo4j가 찾은 공고만 검색 (Neo4j-guided hybrid)
        - section_type: 요건 섹션으로 제한해 복지·noise 억제
        - rerank: CrossEncoder로 최종 재정렬 (기본 True, 후보 적을 때는 자동 스킵)
        두 조건은 AND로 결합된다.
        """
        total = self._col.count()
        if total == 0:
            return []
        if self._bm25 is None:
            self._build_bm25()

        # ── Chroma where 절 조립 ─────────────────────────────────
        conditions: list[dict] = []
        if section_type:
            conditions.append({"section_type": section_type})
        if source_ids:
            conditions.append({"source_id": {"$in": list(source_ids)}})

        where: dict | None
        if not conditions:
            where = None
        elif len(conditions) == 1:
            where = conditions[0]
        else:
            where = {"$and": conditions}

        # rerank 시 후보를 더 넓게 뽑고 cross-encoder로 압축
        candidate_n = min(n_results * 4 if rerank else n_results * 3, total)

        # Dense 검색 — where 절로 후보 제한
        dense = self._col.query(
            query_texts=[query],
            n_results=candidate_n,
            where=where,
        )
        dense_ids: list[str] = dense["ids"][0]

        # BM25 검색 — 캐시된 메타데이터로 후필터 (재조회 없음)
        tokens = query.lower().split()
        bm25_scores = self._bm25.get_scores(tokens)
        bm25_ranked = [
            self._bm25_ids[i]
            for i in sorted(
                range(len(bm25_scores)),
                key=lambda x: bm25_scores[x],
                reverse=True,
            )
        ]
        if conditions:
            bm25_ranked = self._filter_by_metadata(
                bm25_ranked,
                section_type=section_type,
                source_ids=source_ids,
            )
        bm25_ranked = bm25_ranked[:candidate_n]

        # RRF 합산
        rrf_ids = self._rrf(dense_ids, bm25_ranked)[:candidate_n]
        if not rrf_ids:
            return []

        # CrossEncoder 재정렬 — 후보가 n_results보다 많을 때만 실행
        if rerank and len(rrf_ids) > n_results:
            final_ids, final_metas = self._rerank(query, rrf_ids, n_results)
        else:
            final_ids = rrf_ids[:n_results]
            fetched = self._col.get(ids=final_ids, include=["metadatas"])
            # get()은 id 삽입 순서로 반환 — rrf 순서 유지
            id_to_meta = dict(zip(fetched["ids"], fetched["metadatas"]))
            final_metas = [id_to_meta[i] for i in final_ids if i in id_to_meta]

        return [
            {
                "original_text": m["original_text"],
                "job_title": m["job_title"],
                "company": m["company"],
                "section_type": m["section_type"],
                "source_id": m["source_id"],
            }
            for m in final_metas
        ]

    def count(self) -> int:
        return self._col.count()

    # ── 내부 유틸 ────────────────────────────────────────────────

    def _rerank(
        self, query: str, candidate_ids: list[str], n_results: int
    ) -> tuple[list[str], list[dict]]:
        """CrossEncoder로 후보 문서를 재정렬해 상위 n_results를 반환.

        RRF가 순위를 매긴 후보 풀을 cross-encoder가 (쿼리, 문서) 쌍으로 읽고
        실제 관련도 점수를 계산한다. Dense 유사도나 BM25 점수보다 정확하다.
        """
        from sentence_transformers import CrossEncoder

        if self._cross_encoder is None:
            print(f"[chroma] CrossEncoder 로드 중: {_CROSS_ENCODER_MODEL}")
            self._cross_encoder = CrossEncoder(_CROSS_ENCODER_MODEL)

        fetched = self._col.get(ids=candidate_ids, include=["documents", "metadatas"])
        if not fetched["ids"]:
            return [], []

        id_to_doc  = dict(zip(fetched["ids"], fetched["documents"]))
        id_to_meta = dict(zip(fetched["ids"], fetched["metadatas"]))

        # 문서는 컨텍스트 헤더 포함 버전(임베딩에 사용한 것)으로 점수 계산
        pairs = [(query, id_to_doc[i]) for i in candidate_ids if i in id_to_doc]
        valid_ids = [i for i in candidate_ids if i in id_to_doc]

        scores: list[float] = self._cross_encoder.predict(pairs).tolist()

        ranked = sorted(zip(valid_ids, scores), key=lambda x: x[1], reverse=True)
        top_ids = [doc_id for doc_id, _ in ranked[:n_results]]
        top_metas = [id_to_meta[i] for i in top_ids]

        return top_ids, top_metas

    def _build_bm25(self) -> None:
        data = self._col.get(include=["documents", "metadatas"])
        self._bm25_ids = data["ids"]
        self._bm25_meta: list[dict] = data["metadatas"]  # 메타 캐시 — 재조회 방지
        tokenized = [doc.lower().split() for doc in data["documents"]]
        self._bm25 = BM25Okapi(tokenized)

    def _filter_by_metadata(
        self,
        ids: list[str],
        section_type: str | None = None,
        source_ids: list[str] | None = None,
    ) -> list[str]:
        """캐시된 메타데이터로 BM25 결과를 필터링한다. Chroma 재조회 없음."""
        if not ids:
            return []
        source_set = set(source_ids) if source_ids else None
        meta_by_id = dict(zip(self._bm25_ids, self._bm25_meta))
        result = []
        for doc_id in ids:
            m = meta_by_id.get(doc_id)
            if m is None:
                continue
            if section_type and m.get("section_type") != section_type:
                continue
            if source_set and m.get("source_id") not in source_set:
                continue
            result.append(doc_id)
        return result

    @staticmethod
    def _rrf(*ranked_lists: list[str], k: int = 60) -> list[str]:
        """Reciprocal Rank Fusion으로 여러 랭킹 리스트를 합산."""
        scores: dict[str, float] = {}
        for ranked in ranked_lists:
            for rank, doc_id in enumerate(ranked):
                scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (rank + k)
        return sorted(scores, key=lambda x: scores[x], reverse=True)

    @staticmethod
    def _build_embedding_function():
        key = os.getenv("OPENAI_API_KEY")
        if key:
            return embedding_functions.OpenAIEmbeddingFunction(
                api_key=key,
                model_name="text-embedding-3-small",
            )
        print("[chroma] OPENAI_API_KEY 없음 — 로컬 임베딩 모델 사용")
        return embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )
