# 기술명과 직무명을 표준 표기로 정규화하는 유틸리티
import os

from openai import OpenAI

SKILL_ALIASES: dict[str, str] = {
    # Frontend
    "react.js": "React", "reactjs": "React", "react": "React", "리액트": "React",
    "typescript": "TypeScript", "ts": "TypeScript",
    "javascript": "JavaScript", "js": "JavaScript",
    "vue.js": "Vue.js", "vuejs": "Vue.js", "vue": "Vue.js",
    "next.js": "Next.js", "nextjs": "Next.js",
    "tailwind": "Tailwind CSS", "tailwindcss": "Tailwind CSS",
    # Backend / General
    "golang": "Go",
    "spring boot": "Spring Boot", "springboot": "Spring Boot",
    "fastapi": "FastAPI",
    "node.js": "Node.js", "nodejs": "Node.js",
    "python": "Python",
    # Infrastructure
    "docker": "Docker",
    "kubernetes": "Kubernetes", "k8s": "Kubernetes",
    "github actions": "GitHub Actions", "gitlab ci": "GitLab CI",
    "gitlab": "GitLab",
    "terraform": "Terraform",
    # Cloud
    "aws": "AWS", "gcp": "GCP", "azure": "Azure",
    # Database
    "postgresql": "PostgreSQL", "postgres": "PostgreSQL",
    "mongodb": "MongoDB", "mongo": "MongoDB",
    "elasticsearch": "Elasticsearch", "elastic search": "Elasticsearch",
    # Observability
    "datadog": "Datadog",
    # AI / ML
    "langchain": "LangChain", "langgraph": "LangGraph",
    "pytorch": "PyTorch", "torch": "PyTorch",
    "huggingface": "Hugging Face", "hugging face": "Hugging Face",
    "transformers": "Hugging Face Transformers",
    "vllm": "vLLM",
    "lora": "LoRA", "qlora": "QLoRA",
    "ragas": "RAGAS",
    # Vector DB
    "qdrant": "Qdrant",
    "chroma": "Chroma", "chromadb": "Chroma",
    "pinecone": "Pinecone",
    # Graph DB
    "neo4j": "Neo4j",
    # Concept normalization (대소문자 통일)
    "microservices": "Microservices", "micro-services": "Microservices",
    "microservices architecture": "Microservices",
    "micro-services architecture": "Microservices",
    "cybersecurity": "Cybersecurity", "cyber security": "Cybersecurity",
    "salesforce": "Salesforce", "salesForce": "Salesforce",
    "ci/cd": "CI/CD", "ci / cd": "CI/CD",
    "object-oriented programming": "OOP", "oop": "OOP",
    # AI / ML / LLM 동의어 통합
    "artificial intelligence": "AI",
    "ml": "Machine Learning", "machine learning": "Machine Learning",
    "llms": "LLM", "llm": "LLM",
    "genai": "GenAI", "generative ai": "GenAI", "gen ai": "GenAI",
    "rag": "RAG", "retrieval augmented generation": "RAG",
    "retrieval-augmented generation": "RAG",
    # Korean
    "리액트": "React",
}

# (키워드 리스트, 표준 직무명) — 위에서 아래 순으로 매칭 (구체적인 규칙이 앞에 와야 함)
_JOB_TITLE_RULES: list[tuple[list[str], str]] = [
    (["llm", "genai", "gen ai", "agentic", "rag", "agent"], "AI Engineer"),
    (["machine learning", "ml engineer", "ml researcher", "research scientist"], "ML Engineer"),
    (["analytics engineer"], "Analytics Engineer"),
    (["data pipeline", "data engineer", "etl", "airflow"], "Data Engineer"),
    (["data scientist", "data science"], "Data Scientist"),
    (["data analyst", "business analyst", "analyst"], "Data Analyst"),
    (["devops", "mlops", "infra", "sre"], "DevOps Engineer"),
    (["security engineer", "appsec", "devsecops"], "Security Engineer"),
    (["backend", "server", "api engineer"], "Backend Engineer"),
    (["frontend", "ui ", "ux "], "Frontend Engineer"),
    (["mobile", "ios", "android", "react native", "flutter"], "Mobile Engineer"),
    (["platform engineer", "infrastructure", "cloud engineer"], "Platform Engineer"),
    (["software engineer", "software developer", "full stack", "fullstack", "full-stack"], "Software Engineer"),
]

_normalized_jobs_cache: dict[str, str] = {}


# 대문자 유지가 필요한 약어/브랜드
_KEEP_UPPER = {
    "llm", "llms", "rag", "ai", "ml", "api", "apis", "sql", "nosql",
    "nlp", "cv", "gpu", "cpu", "iam", "sdk", "ci", "cd", "aws", "gcp",
    "etl", "sre", "ui", "ux", "url", "rest", "grpc", "mlops",
}
_TITLE_STOP = {"and", "or", "the", "of", "in", "for", "a", "an", "with", "to"}


def smart_title(name: str) -> str:
    """단어별 첫글자 대문자. 전치사/관사 소문자, 약어는 ALL CAPS 유지."""
    words = name.split()
    result = []
    for i, w in enumerate(words):
        if w.lower() in _KEEP_UPPER:
            result.append(w.upper())
        elif i == 0 or w.lower() not in _TITLE_STOP:
            result.append(w.capitalize())
        else:
            result.append(w.lower())
    return " ".join(result)


def normalize_skill(raw: str) -> str:
    """원문 기술명을 표준 표기로 정규화. 사전에 없으면 smart_title로 표기(대소문자) 통일."""
    key = raw.lower().strip()
    if key in SKILL_ALIASES:
        return SKILL_ALIASES[key]
    return smart_title(raw.strip())


def normalize_job_title(raw_title: str, client: OpenAI | None = None) -> str:
    """직무명을 표준 카테고리로 정규화. 클라이언트 없으면 룰 기반 fallback."""
    if raw_title in _normalized_jobs_cache:
        return _normalized_jobs_cache[raw_title]

    if client is None or not os.getenv("OPENAI_API_KEY"):
        result = _normalize_by_rule(raw_title)
    else:
        result = _normalize_by_llm(raw_title, client)

    _normalized_jobs_cache[raw_title] = result
    return result


def _normalize_by_llm(raw_title: str, client: OpenAI) -> str:
    prompt = f"""다음 채용공고 직무명을 아래 표준 직무 카테고리 중 하나로 분류하세요.

직무명: "{raw_title}"

표준 카테고리:
- AI Engineer        (LLM/GenAI/RAG/Agent 관련)
- ML Engineer        (ML 모델 학습·연구 중심)
- Data Engineer      (데이터 파이프라인·ETL 중심)
- Data Scientist     (분석·통계 중심)
- Backend Engineer   (서버·API·DB 중심)
- Frontend Engineer  (UI·웹 클라이언트 중심)
- Full Stack Engineer (프론트+백엔드 동시)
- Mobile Engineer    (iOS·Android·React Native)
- Platform Engineer  (인프라·Kubernetes·CI/CD·DevOps)
- Security Engineer  (사이버보안·취약점·침해대응)
- Software Engineer  (일반 소프트웨어 개발, 위 카테고리에 해당 없는 SE)
- Other              (비개발 직군 또는 위 카테고리로 분류 불가)

규칙:
- 직함에 "Manager", "Director", "VP" 포함 → Other
- 직함에 "Hardware", "Mechanical", "Civil", "Piping" 포함 → Other
- DevOps/SRE/Platform/Infrastructure 관련 → Platform Engineer
- Security/Cybersecurity/AppSec 관련 → Security Engineer
- 일반 Software Engineer 타이틀 (Backend/Frontend 특정 안 됨) → Software Engineer

카테고리 이름만 출력하세요. 다른 텍스트 없이."""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=20,
            messages=[{"role": "user", "content": prompt}],
        )
        return (response.choices[0].message.content or "").strip()
    except Exception as e:
        print(f"[warn] normalize_job_title LLM 실패, 룰 기반 사용: {e}")
        return _normalize_by_rule(raw_title)


def _normalize_by_rule(raw_title: str) -> str:
    lower = raw_title.lower()
    for keywords, category in _JOB_TITLE_RULES:
        if any(kw in lower for kw in keywords):
            return category
    return "Other"
