# 기술명을 표준 표기로 정규화하는 유틸리티
#
# 이 파일이 하는 일: pipeline.py의 _normalize_skills()가 호출하는 normalize_skill()의 실제 구현.
# LLM(skill_extractor.py)이 뽑아낸 스킬명은 "React.js", "react", "리액트"처럼 표기가 제각각일 수 있는데,
# 이 파일이 그걸 전부 "React"라는 하나의 표준 표기로 통일해준다.
# 그래야 Neo4j에 (:Skill {name: "React"})가 하나로만 존재하고, "React.js"와 "React"가
# 서로 다른 노드로 중복 생성되는 걸 막을 수 있다.

# SKILL_ALIASES: dict[str, str] 타입 힌트 — {문자열: 문자열} 쌍으로 이루어진 딕셔너리라는 뜻
# 왼쪽(키) = 흔히 나오는 변형 표기 (전부 소문자로 통일해서 등록), 오른쪽(값) = 우리가 정한 표준 표기
SKILL_ALIASES: dict[str, str] = {
    # Frontend
    "react.js": "React", "reactjs": "React", "react": "React", "리액트": "React",
    # "react.js", "reactjs", "react", "리액트" 네 가지 다른 표기 → 전부 "React" 하나로 통일
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
    "salesforce": "Salesforce",
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
    # 아래 항목들은 smart_title()에 맡기면 "Mlops", "Devops"처럼 어색하게 나올 수 있어서
    # 아예 사전에 정답을 미리 박아둔 것 — 사전 매칭이 항상 smart_title보다 우선순위가 높기 때문
    "mlops": "MLOps", "ml ops": "MLOps",
    "devops": "DevOps", "dev ops": "DevOps",
    "siem": "SIEM",
    "github": "GitHub",
    "power bi": "Power BI", "powerbi": "Power BI",
    "dbt": "dbt",
    "css": "CSS", "css3": "CSS",
    "html": "HTML", "html5": "HTML5",
    "cloud security": "Cloud Security",
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
    "spring": "Spring",   # 'spring'은 Spring Framework — Spring Boot와 구분 (springboot는 별도 매핑)
    "databricks mlflow": "MLflow",
    "gcp vertex": "Vertex AI",
    "azure ml": "Azure ML",
}

# 스킬이 아닌 것들 — 자격증·소프트스킬·방법론·협업도구·제네릭 용어
# frozenset[str] : "문자열들의, 변경 불가능한 집합" 타입. 값을 빠르게 조회(in 검사)하려고 집합을 씀
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
    "ai-assisted engineering workflows", "ssh",
    # 너무 broad
    "cloud", "windows", "data science",
})
# 이 목록에 있는 단어들은 "기술 스택"이라기엔 너무 뭉뚱그려지거나(소프트스킬), 스킬이 아니라
# 자격증·방법론 이름이라서, Neo4j에 :Skill 노드로 만들면 분석 품질이 떨어짐 — 그래서 아예 걸러냄


def is_noise_skill(name: str) -> bool:
    """블록리스트에 속하거나 너무 짧은 스킬명이면 True."""
    return name.lower().strip() in SKILL_BLOCKLIST or len(name.strip()) <= 1
    # "A or B" → A(블록리스트에 있음) 또는 B(정리했더니 글자수가 1자 이하) 둘 중 하나라도 참이면 전체가 참
    # len(name.strip()) <= 1 → "a", ""처럼 스킬명이라 보기엔 너무 짧은 노이즈 값 방어
    # 주의: 이 함수는 normalize_skill()이나 pipeline.py의 _normalize_skills()에서 직접 호출되진 않고,
    # 다른 파일(스킬 필터링이 필요한 곳)에서 재사용하도록 노출된 헬퍼로 보임


# 대문자 유지가 필요한 약어/브랜드
_KEEP_UPPER = {
    "llm", "llms", "rag", "ai", "ml", "api", "apis", "sql", "nosql",
    "nlp", "cv", "gpu", "cpu", "iam", "sdk", "ci", "cd", "aws", "gcp",
    "etl", "sre", "ui", "ux", "url", "rest", "grpc", "mlops",
}
# 이 단어들은 smart_title()이 그냥 "Llm", "Api"처럼 첫 글자만 대문자로 바꾸면 안 되고,
# 원래 약어 관례대로 "LLM", "API"처럼 전부 대문자로 나와야 하는 것들
_TITLE_STOP = {"and", "or", "the", "of", "in", "for", "a", "an", "with", "to"}
# 영어에서 제목(타이틀)을 쓸 때 관례적으로 소문자로 남겨두는 전치사/관사/접속사 목록
# (예: "Machine Learning and AI"에서 "and"는 대문자로 안 바꾸는 게 자연스러움)


def smart_title(name: str) -> str:
    """단어별 첫글자 대문자. 전치사/관사 소문자, 약어는 ALL CAPS 유지."""
    # SKILL_ALIASES 사전에 없는, 처음 보는 스킬명이 들어왔을 때 "그나마 보기 좋게" 표기를 다듬는 역할
    words = name.split()
    # .split()은 인자 없이 쓰면 공백(스페이스, 탭, 개행 등) 기준으로 단어를 쪼개서 리스트로 만듦
    result = []  # 단어별로 다듬은 결과를 하나씩 담을 빈 리스트
    for i, w in enumerate(words):
        # enumerate(words)로 "몇 번째 단어인지(i)"와 "그 단어(w)"를 함께 얻음
        if w.lower() in _KEEP_UPPER:
            result.append(w.upper())
            # 약어 목록에 있으면 무조건 전체 대문자로 (예: "llm" → "LLM")
        elif any(c.isupper() for c in w[1:]):
            # w[1:] → 첫 글자를 뺀 나머지 부분 (슬라이싱: 인덱스 1부터 끝까지)
            # any(c.isupper() for c in w[1:]) → 첫 글자 이후에 대문자가 하나라도 있으면 True
            # 예: "PyTorch"의 경우 w[1:]는 "yTorch"인데 그 안에 대문자 T가 있음 → True
            result.append(w)   # 이미 CamelCase/브랜드 표기(PyTorch·GraphQL) → 훼손 없이 보존
            # 이미 스스로 대소문자를 신경 써서 쓴 것처럼 보이는 단어는 건드리지 않고 그대로 둠
        elif i == 0 or w.lower() not in _TITLE_STOP:
            result.append(w.capitalize())
            # .capitalize()는 첫 글자만 대문자로, 나머지는 전부 소문자로 바꾸는 메서드
            # "i == 0"(문장 맨 첫 단어) 이거나, "TITLE_STOP에 없는 단어"면 이 규칙 적용
            # (맨 첫 단어는 전치사여도 예외적으로 대문자로 — 제목이 "The"로 시작하면 대문자 유지하는 영어 관례)
        else:
            result.append(w.lower())
            # 위 세 조건에 다 안 걸리면(=TITLE_STOP에 있는 전치사/관사이고 맨 앞 단어도 아니면) 소문자로
    return " ".join(result)
    # 다듬어진 단어들을 다시 공백으로 이어붙여 하나의 문자열로 반환


def normalize_skill(raw: str) -> str:
    """원문 기술명을 표준 표기로 정규화. 사전에 없으면 smart_title로 표기(대소문자) 통일."""
    key = raw.lower().strip()
    # 사전 조회를 위해 소문자+공백 제거로 통일 (SKILL_ALIASES의 키들도 전부 소문자로 등록돼 있음)
    if key in SKILL_ALIASES:
        return SKILL_ALIASES[key]
        # 사전에 정확히 일치하는 항목이 있으면, 우리가 미리 정해둔 표준 표기를 그대로 반환 (최우선)
    return smart_title(raw.strip())
    # 사전에 없는 처음 보는 스킬명이면, smart_title()로 "그나마 규칙적인" 표기로 다듬어서 반환
    # (예: LLM이 "graphql"이라고 뽑았다면 사전엔 없으니 smart_title이 "GraphQL"처럼은 못 만들고 "Graphql"이 됨 —
    #  완벽하진 않지만, 사전에 없는 새로운 기술명도 최소한의 일관성 있는 표기로는 나오게 하는 안전망 역할)
