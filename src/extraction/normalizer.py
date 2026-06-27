# 기술명을 표준 표기로 정규화하는 유틸리티
SKILL_ALIASES: dict[str, str] = {
    # Frontend
    "react.js": "React", "reactjs": "React", "react": "React", "리액트": "React",
    "typescript": "TypeScript", "ts": "TypeScript",
    "javascript": "JavaScript", "js": "JavaScript",
    "vue.js": "Vue.js", "vuejs": "Vue.js", "vue": "Vue.js",
    "next.js": "Next.js", "nextjs": "Next.js",
    "tailwind": "Tailwind CSS", "tailwindcss": "Tailwind CSS", "tailwind css": "Tailwind CSS",
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
    # 약어·브랜드 표기 정규화 (smart_title가 잘못 처리하는 것들)
    "mlops": "MLOps", "ml ops": "MLOps",
    "devops": "DevOps", "dev ops": "DevOps",
    "siem": "SIEM",
    "github": "GitHub",
    "power bi": "Power BI", "powerbi": "Power BI",
    "dbt": "dbt",
    "css": "CSS", "css3": "CSS",
    "html": "HTML", "html5": "HTML5",
    "cloud security": "Cloud Security",
    # Korean
    "리액트": "React",
    # 중복 정규화 (같은 스킬 다른 표기)
    "apache spark": "Spark", "apache kafka": "Kafka",
    "microsoft azure": "Azure", "ms azure": "Azure",
    "amazon web services": "AWS",
    "google cloud": "GCP", "google cloud platform": "GCP",
    "scikit learn": "Scikit-learn", "sklearn": "Scikit-learn",
    "restful apis": "REST", "restful api": "REST", "rest api": "REST",
    "ci/cd pipelines": "CI/CD", "ci/cd pipeline": "CI/CD",
    "large language models": "LLM", "large language model": "LLM",
    "node": "Node.js",
    "unix/linux": "Linux", "unix": "Linux",
    "spring": "Spring Boot",
    "databricks mlflow": "MLflow",
    "gcp vertex": "Vertex AI",
    "azure ml": "Azure ML",
}

# 스킬이 아닌 것들 — 자격증·소프트스킬·방법론·협업도구·제네릭 용어
SKILL_BLOCKLIST: frozenset[str] = frozenset({
    # 소프트스킬 / 너무 generic
    "coding", "testing", "troubleshooting", "design", "analytical thinking",
    "problem solving", "communication", "open-source", "software integration",
    "computer science", "mathematics", "data analytics", "data analysis",
    # 방법론 / 협업 도구
    "agile", "scrum", "jira", "confluence", "sdlc",
    # 자격증 (스킬이 아닌 자격 취득)
    "cissp", "cism", "cisa", "crisc", "c|eh", "sans giac", "cis",
    "iso", "aws certified security - specialty", "nist",
    # 비스킬 표현
    "apis", "orchestration", "cloud infrastructure", "finops",
    "ai-assisted engineering workflows", "ssh", "open-source",
    # 너무 broad
    "cloud", "windows", "data science",
})


def is_noise_skill(name: str) -> bool:
    """블록리스트에 속하거나 너무 짧은 스킬명이면 True."""
    return name.lower().strip() in SKILL_BLOCKLIST or len(name.strip()) <= 1


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
