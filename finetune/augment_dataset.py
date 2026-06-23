# 타겟 스택(LangGraph, RAG 등) 중심으로 Adzuna 공고를 추가 수집하고
# 기존 dataset에 병합하는 스크립트

import json
import os
import random
import time
from pathlib import Path

import httpx
from openai import OpenAI

# ── 환경변수 ──────────────────────────────────────────────────────
_env = Path(__file__).parent.parent / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
ADZUNA_APP_ID  = os.environ["ADZUNA_APP_ID"]
ADZUNA_APP_KEY = os.environ["ADZUNA_APP_KEY"]

client    = OpenAI(api_key=OPENAI_API_KEY)
DATASET_DIR = Path(__file__).parent / "dataset"

# ── 타겟 쿼리 ─────────────────────────────────────────────────────
TARGET_QUERIES = [
    "langchain langgraph agent",
    "rag retrieval augmented generation",
    "vector database llm",
    "llm application engineer",
    "agentic ai engineer",
    "langfuse evaluation llm",
    "neo4j graph database engineer",
    "prompt engineering llm",
    "chroma weaviate vector search",
    "hugging face transformers fine-tuning",
    "mlops langchain",
    "generative ai engineer python",
]

# ── 후처리 상수 ───────────────────────────────────────────────────
ABSTRACT_CONCEPTS = {
    "machine learning", "ai", "artificial intelligence", "deep learning",
    "data science", "data analysis", "data engineering", "computer science",
    "software engineering", "software development", "cloud computing",
    "distributed systems", "big data", "analytics", "business intelligence",
    "predictive modeling", "statistical analysis", "data modeling",
    "data visualization", "optimization", "scalability", "system design",
    "microservices", "agile", "ci/cd", "devops", "algorithm", "algorithms",
    "natural language processing", "computer vision", "reinforcement learning",
    "data collection", "data processing", "model development", "api development",
    "backend development", "web development", "mobile development",
    "problem solving", "communication", "teamwork", "collaboration",
    "ml", "software applications", "enterprise software", "technical skills",
    "quantitative finance", "ai systems", "cloud services", "data pipelines",
    "data infrastructure",
}

LLM_VARIANTS = {
    "llms", "large language models (llms)", "large language models (llm)",
    "llm (large language model)", "llm based solutions", "ai & llm",
    "ml (machine learning)",
}

EXTRA_ALIASES: dict[str, str] = {
    "natural language processing (nlp)": "NLP",
    "automatic speech recognition (asr)": "ASR",
    "foundational ai models": "Foundation Models",
    "production grade ml systems": "Production ML Systems",
    "production-grade ml systems": "Production ML Systems",
    "generative ai solutions": "Generative AI",
    "generative ai engineering": "Generative AI",
    "genai applications": "GenAI",
    "llm-based ai components": "LLM",
    "llm development": "LLM",
    "large-scale data systems": "Large-scale Systems",
    "data platforms": "Data Platform",
    "optimization systems": "Optimisation",
}

ALIASES: dict[str, str] = {
    "react.js": "React", "reactjs": "React",
    "node.js": "Node.js", "nodejs": "Node.js",
    "fastapi": "FastAPI", "langchain": "LangChain", "lang chain": "LangChain",
    "langgraph": "LangGraph", "python": "Python", "python3": "Python",
    "tensorflow": "TensorFlow", "tf": "TensorFlow",
    "pytorch": "PyTorch", "torch": "PyTorch",
    "aws": "AWS", "amazon web services": "AWS",
    "gcp": "GCP", "google cloud platform": "GCP", "google cloud": "GCP",
    "sql": "SQL", "llm": "LLM", "nlp": "NLP", "rag": "RAG", "rlhf": "RLHF",
    "docker": "Docker", "kubernetes": "Kubernetes", "k8s": "Kubernetes",
    "postgresql": "PostgreSQL", "postgres": "PostgreSQL",
    "mongodb": "MongoDB", "neo4j": "Neo4j", "elasticsearch": "Elasticsearch",
    "hugging face": "Hugging Face", "huggingface": "Hugging Face",
    "openai": "OpenAI", "anthropic": "Anthropic", "mlops": "MLOps",
    "scikit-learn": "scikit-learn", "sklearn": "scikit-learn",
    "pandas": "pandas", "numpy": "NumPy", "github": "GitHub", "git": "Git",
    "rest api": "REST API", "restful api": "REST API", "restful": "REST API",
    "graphql": "GraphQL", "typescript": "TypeScript", "javascript": "JavaScript",
    "html": "HTML", "css": "CSS",
    "chroma": "Chroma", "chromadb": "Chroma",
    "weaviate": "Weaviate", "pinecone": "Pinecone",
    "langfuse": "Langfuse", "ragas": "RAGAS",
    "lora": "LoRA", "qlora": "QLoRA",
    "transformer": "Transformer", "transformers": "Transformers",
    "redis": "Redis", "flask": "Flask", "django": "Django",
    "spark": "Spark", "apache spark": "Spark",
    "kafka": "Kafka", "azure": "Azure", "microsoft azure": "Azure",
    "gpt": "GPT", "bert": "BERT", "ci/cd": "CI/CD",
    "peft": "PEFT", "vllm": "vLLM", "ollama": "Ollama",
    "haystack": "Haystack", "llamaindex": "LlamaIndex", "llama index": "LlamaIndex",
    "xgboost": "XGBoost", "lightgbm": "LightGBM",
    "matplotlib": "Matplotlib", "jupyter": "Jupyter",
    "linux": "Linux", "bash": "Bash", "airflow": "Airflow",
}

INSTRUCTION = (
    'Extract technical skills from the job posting below. '
    'Return valid JSON only with this exact schema — no markdown fences, no commentary:\n'
    '{"job_title": "string", "skills": [{"raw": "string", '
    '"category": "language|framework|database|cloud|tool|concept", '
    '"importance": "required|preferred"}]}'
)


# ── 유틸 함수 ─────────────────────────────────────────────────────

def fetch_page(query: str, page: int = 1, n: int = 50) -> list[dict]:
    resp = httpx.get(
        f"https://api.adzuna.com/v1/api/jobs/gb/search/{page}",
        params={
            "app_id": ADZUNA_APP_ID, "app_key": ADZUNA_APP_KEY,
            "what": query, "results_per_page": n, "content-type": "application/json",
        },
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json().get("results", [])


def label_job(job: dict) -> dict | None:
    title = job.get("title", "")
    desc  = job.get("description", "")[:2000]
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=1024,
            messages=[{"role": "user",
                       "content": f"{INSTRUCTION}\n\nTitle: {title}\n\nDescription:\n{desc}"}],
        )
        raw = resp.choices[0].message.content.strip().replace("```json", "").replace("```", "").strip()
        parsed = json.loads(raw)
        if not parsed.get("skills"):
            return None
        return {
            "instruction": INSTRUCTION,
            "input": f"Title: {title}\n\nDescription:\n{desc}",
            "output": json.dumps(parsed, ensure_ascii=False, separators=(",", ":")),
        }
    except Exception:
        return None


def _smart_title(s: str) -> str:
    words = s.strip().split()
    result = []
    for w in words:
        if w.isupper() and len(w) >= 2:
            result.append(w)
        elif w and w[0].isupper() and not w[1:].islower():
            result.append(w)
        else:
            result.append(w.capitalize())
    return " ".join(result)


def normalize_raw(raw: str) -> str:
    lower = raw.strip().lower()
    if lower in ALIASES:
        return ALIASES[lower]
    if lower in EXTRA_ALIASES:
        return EXTRA_ALIASES[lower]
    return _smart_title(raw)


def postprocess(samples: list[dict], decisions: dict[str, str]) -> list[dict]:
    """추상 개념 제거 + 기술명 정규화 + 중복 제거 + LLM 재판단 적용."""
    processed = []
    for s in samples:
        try:
            parsed = json.loads(s["output"])
            skills = parsed.get("skills", [])
            cleaned: list[dict] = []
            seen: set[str] = set()

            for sk in skills:
                raw = sk["raw"]
                cat = sk.get("category", "")

                if cat == "concept":
                    lower = raw.lower()
                    if lower in LLM_VARIANTS:
                        raw = "LLM"
                    elif lower in EXTRA_ALIASES:
                        raw = EXTRA_ALIASES[lower]
                    sk["raw"] = raw
                    if raw.lower() in ABSTRACT_CONCEPTS:
                        continue
                    if decisions.get(raw, "keep") == "remove":
                        continue
                else:
                    raw = normalize_raw(raw)
                    sk["raw"] = raw

                key = raw.lower()
                if key in seen:
                    continue
                seen.add(key)
                cleaned.append(sk)

            if not cleaned:
                continue

            parsed["skills"] = cleaned
            processed.append({
                "instruction": s["instruction"],
                "input": s["input"],
                "output": json.dumps(parsed, ensure_ascii=False, separators=(",", ":")),
            })
        except Exception:
            continue
    return processed


def save_jsonl(data: list[dict], path: Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for item in data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


# ── 메인 ─────────────────────────────────────────────────────────

def main() -> None:
    decisions: dict[str, str] = json.loads(
        (DATASET_DIR / "concept_decisions.json").read_text()
    )

    # 1. 수집
    new_jobs: dict[str, dict] = {}
    print("Adzuna 타겟 쿼리 수집 중...")
    for query in TARGET_QUERIES:
        for page in range(1, 4):
            try:
                jobs = fetch_page(query, page=page, n=50)
                if not jobs:
                    break
                for j in jobs:
                    if j.get("id") and len(j.get("description", "")) >= 100:
                        new_jobs[j["id"]] = j
                print(f"  {query[:42]:42} p{page} → 누적 {len(new_jobs)}개")
                time.sleep(0.5)
            except Exception as e:
                print(f"  [skip] {query} p{page}: {e}")
                break

    jobs_list = list(new_jobs.values())
    random.seed(99)
    random.shuffle(jobs_list)
    print(f"수집 완료: {len(jobs_list)}개\n")

    # 2. 레이블링
    print(f"GPT-4o-mini 레이블링 ({len(jobs_list)}개)...")
    new_samples: list[dict] = []
    for i, job in enumerate(jobs_list):
        result = label_job(job)
        if result:
            new_samples.append(result)
        if (i + 1) % 50 == 0:
            print(f"  [{i+1}/{len(jobs_list)}] 유효 {len(new_samples)}개")
        time.sleep(0.05)
    print(f"레이블링 완료: {len(new_samples)}개\n")

    # 3. 후처리
    new_clean = postprocess(new_samples, decisions)
    print(f"후처리 후: {len(new_clean)}개\n")

    # 4. 기존 데이터와 병합 (title 기준 중복 제거)
    existing_train = [json.loads(l) for l in (DATASET_DIR / "train.jsonl").read_text().splitlines() if l.strip()]
    existing_test  = [json.loads(l) for l in (DATASET_DIR / "test.jsonl").read_text().splitlines() if l.strip()]
    existing_titles = {s["input"][:80] for s in existing_train + existing_test}

    new_deduped = [s for s in new_clean if s["input"][:80] not in existing_titles]
    print(f"중복 제거 후 신규: {len(new_deduped)}개")

    random.seed(77)
    random.shuffle(new_deduped)
    n_test        = max(5, len(new_deduped) // 7)
    combined_train = existing_train + new_deduped[n_test:]
    combined_test  = existing_test  + new_deduped[:n_test]
    random.shuffle(combined_train)
    random.shuffle(combined_test)

    # 5. 저장
    save_jsonl(combined_train, DATASET_DIR / "train.jsonl")
    save_jsonl(combined_test,  DATASET_DIR / "test.jsonl")
    print(f"\n저장 완료 — train {len(combined_train)}개 / test {len(combined_test)}개")


if __name__ == "__main__":
    main()
