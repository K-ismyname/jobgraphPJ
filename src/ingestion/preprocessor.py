# Muse 원본 JSON을 Neo4j 적재용 중간 포맷으로 변환하는 전처리 모듈
from __future__ import annotations

import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

_REQUIRED_HEADERS = frozenset([
    "minimum qualifications", "required qualifications", "requirements",
    "qualifications", "what you'll need", "what you need",
    "must have", "basic qualifications", "job requirements",
    "required skills", "required experience", "responsibilities and requirements",
    # 추가: 실제 공고에서 자주 쓰이는 표현
    "the ideal candidate will have", "ideal candidate", "who are we looking for",
    "what we're looking for", "what we look for", "who you are",
    "you have", "you bring", "you'll bring", "your background",
    "what you bring", "about you", "skills & experience",
    "skills and experience", "experience and skills",
])

_PREFERRED_HEADERS = frozenset([
    "preferred qualifications", "preferred skills", "nice to have",
    "bonus points", "preferred", "plus", "desired qualifications",
    "what we'd love", "great to have",
    # 추가
    "nice to haves", "it's a plus", "bonus if you have",
    "even better if", "ideally you also",
])


def strip_html(raw: str) -> str:
    """HTML 태그·엔터티를 제거해 가독성 있는 텍스트로 변환."""
    text = html.unescape(raw)
    text = re.sub(r"<br\s*/?>|</p>|</li>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<li\s*>", "• ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


_MAX_HEADER_LEN = 100  # 실제 섹션 헤더는 짧다 (예: "qualifications" = 14자)


def extract_sections(contents: str) -> tuple[str, str]:
    """HTML contents에서 required/preferred 섹션 텍스트를 추출.

    <b>...</b> 헤더를 기준으로 섹션을 분리한 뒤 헤더 키워드로 분류.
    파싱 실패 시 빈 문자열 반환 (pipeline에서 fallback 처리).

    일부 공고(DoorDash 등)는 <b> 태그가 짧은 헤더가 아닌 콘텐츠 블록 자체를
    감싸는 구조를 사용한다. 이 경우:
    - 헤더 길이 > _MAX_HEADER_LEN → 헤더 텍스트 자체를 섹션 본문으로 사용
    - 헤더 길이 <= _MAX_HEADER_LEN → </b> 이후 body를 섹션 본문으로 사용 (정상 패턴)
    """
    # 일부 공고는 HTML 엔터티로 이중 이스케이프된 경우가 있어 먼저 unescape
    unescaped = html.unescape(contents)
    # <b\b> 패턴: <br>, <button> 등 다른 태그와 혼동하지 않기 위해 단어 경계(\b) 사용
    # <b>는 매칭되지만 <br>은 매칭되지 않음 — Apple처럼 <br>이 많은 공고에서 오파싱 방지
    parts = re.split(r"<(?:b\b|strong|h[23])[^>]*>(.*?)</(?:b\b|strong|h[23])>", unescaped, flags=re.DOTALL | re.IGNORECASE)
    # parts: [pre, header1, body1, header2, body2, ...]

    required_chunks: list[str] = []
    preferred_chunks: list[str] = []

    for i in range(1, len(parts), 2):
        raw_header_text = re.sub(r"<[^>]+>", "", parts[i]).strip()
        header = raw_header_text.lower().rstrip(":")
        body = parts[i + 1] if i + 1 < len(parts) else ""

        # 짧은 헤더 = 실제 섹션 제목 → body가 섹션 내용
        # 긴 헤더 = <b>가 콘텐츠 블록을 감싼 경우 → 헤더 텍스트 자체가 섹션 내용
        if len(header) > _MAX_HEADER_LEN:
            clean = raw_header_text.strip()
            # 긴 블록이 보상·복지 위주면 요건 섹션으로 분류 불가 → 건너뜀
            noise_hits = len(_NOISE_SIGNALS.findall(clean))
            req_hits = len(_REQ_SIGNALS.findall(clean))
            if noise_hits > req_hits:
                continue
        else:
            clean = strip_html(body).strip()

        if not clean:
            continue

        # preferred 체크를 먼저 — "preferred qualifications"이 "qualifications" 키워드로
        # required에 잘못 분류되는 것을 방지
        if header in _PREFERRED_HEADERS or "preferred" in header or any(
            kw in header for kw in ("nice to have", "bonus points", "plus")
        ):
            preferred_chunks.append(clean)
        elif header in _REQUIRED_HEADERS or any(
            kw in header for kw in ("required", "qualifications", "requirements", "must")
        ):
            required_chunks.append(clean)

    return "\n\n".join(required_chunks), "\n\n".join(preferred_chunks)


_BULLET_RE = re.compile(r"^[•\-\*]\s+.{10,}")  # 최소 10자 이상인 불릿 라인

# 요건 클러스터 점수 올리는 패턴 (Muse HTML + Adzuna 평문 공통)
_REQ_SIGNALS = re.compile(
    r"\d+\+?\s*years?|experience\s+with|proficient\s+in|knowledge\s+of"
    r"|familiarity\s+with|strong\s+understanding|ability\s+to|skilled\s+in"
    r"|background\s+in|expertise\s+in|demonstrated|degree\s+in|bachelor"
    r"|must\s+have|must\s+be|you\s+must|you\s+will\s+have|you\s+'ll\s+have"
    r"|you\s+should\s+have|we\s+require|required\s+to|looking\s+for"
    r"|ideal\s+candidate|at\s+least|minimum\s+of|\bessential\b|proven\s+experience",
    re.IGNORECASE,
)

# 복지/노이즈 클러스터 점수 깎는 패턴
_NOISE_SIGNALS = re.compile(
    r"\bpto\b|dental|insurance|parental\s+leave|fertility|equity|stock\s+option"
    r"|salary|compensation|401k|remote\s+work|hybrid|commuter|stipend|perks",
    re.IGNORECASE,
)


def extract_bullet_section(text_clean: str, min_bullets: int = 4) -> str:
    """text_clean에서 요건 불릿 클러스터를 추출.

    연속된 불릿 묶음(클러스터)을 모두 찾은 뒤,
    요건 키워드가 많고 복지·노이즈 키워드가 적은 클러스터를 반환.
    """
    lines = text_clean.split("\n")
    clusters: list[list[str]] = []
    current: list[str] = []
    gap = 0

    for line in lines:
        stripped = line.strip()
        if _BULLET_RE.match(stripped):
            current.append(stripped)
            gap = 0
        else:
            if current:
                gap += 1
                if gap > 2:
                    clusters.append(current[:])
                    current = []
                    gap = 0

    if current:
        clusters.append(current)

    valid = [c for c in clusters if len(c) >= min_bullets]
    if not valid:
        return ""

    def score(cluster: list[str]) -> float:
        text = " ".join(cluster)
        req_hits = len(_REQ_SIGNALS.findall(text))
        noise_hits = len(_NOISE_SIGNALS.findall(text))
        # 요건 신호 가중치 2, 노이즈 패널티 3, 길이 보너스 0.1
        return req_hits * 2 - noise_hits * 3 + len(cluster) * 0.1

    best = max(valid, key=score)
    # 점수가 0 이하면 요건 클러스터로 보기 어려움 → 빈 문자열 반환
    return "" if score(best) <= 0 else "\n".join(best)


def extract_requirement_sentences(text_clean: str, min_sentences: int = 3) -> str:
    """불릿 없는 서술형 공고에서 요건 문장을 추출.

    _REQ_SIGNALS 패턴이 포함된 문장만 모아 반환.
    min_sentences 미만이면 빈 문자열 반환.
    """
    # 마침표/줄바꿈 기준으로 문장 분리
    raw_sentences = re.split(r"(?<=[.!?])\s+|\n", text_clean)
    req_sentences = [
        s.strip()
        for s in raw_sentences
        if len(s.strip()) > 20 and _REQ_SIGNALS.search(s)
    ]
    return "" if len(req_sentences) < min_sentences else "\n".join(req_sentences)


def preprocess_job(raw: dict) -> dict:
    """Muse 원본 공고 1개를 파이프라인 중간 포맷으로 변환.

    반환 포맷은 neo4j_client.ingest_posting()이 기대하는 키 구조와 호환됨.
    스킬 추출 전 단계이므로 "skills" 키는 없음.
    """
    contents = raw.get("contents", "")
    text_clean = strip_html(contents)
    required_section, preferred_section = extract_sections(contents)

    # '•' 같이 기호만 남은 섹션은 실질적으로 빈 것으로 처리
    # (Celonis 패턴: <strong>헤더</strong> 뒤 <li> 여는 태그만 남아 '•' 생성)
    if len(required_section.strip()) < 10:
        required_section = ""

    # 섹션 파싱 실패 시: 불릿 클러스터 → 요건 문장 순으로 추출
    bullet_section = ""
    if not required_section:
        bullet_section = extract_bullet_section(text_clean)
        if not bullet_section:
            bullet_section = extract_requirement_sentences(text_clean)

    company_info = raw.get("company", {})
    company_name = (
        company_info.get("name", "") if isinstance(company_info, dict) else str(company_info)
    )

    locations = raw.get("locations", [])
    location = locations[0]["name"] if locations else ""

    levels = raw.get("levels", [])
    level = levels[0]["name"] if levels else ""

    url = (raw.get("refs") or {}).get("landing_page", "")
    created = raw.get("publication_date") or "2025-01-01T00:00:00Z"

    return {
        "id": f"muse-{raw['id']}",
        "title": raw.get("name", ""),
        "company": company_name,
        "location": location,
        "level": level,
        "url": url,
        "created": created,
        "salary_min": None,
        "salary_max": None,
        "contract_type": raw.get("type", ""),
        "text_clean": text_clean,
        "required_section": required_section,
        "preferred_section": preferred_section,
        "bullet_section": bullet_section,
        "category": raw.get("_collected_category", ""),
        "source": "themuse",
    }


# 비기술 직군으로 간주해 제외할 타이틀 키워드
_NON_TECH_TITLE_KEYWORDS = frozenset([
    "engineering manager", "engineering director", "engineering program manager",
    "head of engineering", "vp of engineering", "vice president",
    "hardware engineer", "mechanical engineer", "electrical engineer",
    "civil engineer", "reliability engineer", "test engineer",
    "quality engineer", "qa engineer", "value engineering",
])


def is_tech_job(title: str) -> bool:
    """비기술 직군(관리직·하드웨어·QA 등)이면 False 반환."""
    t = title.lower()
    return not any(kw in t for kw in _NON_TECH_TITLE_KEYWORDS)


def preprocess_file(
    input_path: str | Path,
    output_path: str | Path,
) -> list[dict]:
    """raw JSON 파일을 읽어 전처리 후 저장.

    중복 (title+company) 제거 및 비기술 직군 필터링 포함.
    """
    input_path = Path(input_path)
    output_path = Path(output_path)

    with open(input_path, encoding="utf-8") as f:
        raw_jobs: list[dict] = json.load(f)

    processed_all = [preprocess_job(job) for job in raw_jobs]
    before = len(processed_all)

    # 비기술 직군 제거
    processed_all = [j for j in processed_all if is_tech_job(j["title"])]
    filtered_non_tech = before - len(processed_all)

    # (title+company) 중복 제거 — 먼저 나온 것 유지
    seen: set[tuple[str, str]] = set()
    processed: list[dict] = []
    for j in processed_all:
        key = (j["title"].strip().lower(), j["company"].lower())
        if key not in seen:
            seen.add(key)
            processed.append(j)
    filtered_dup = len(processed_all) - len(processed)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(processed, f, ensure_ascii=False, indent=2)

    total = len(processed)
    with_req = sum(1 for j in processed if j["required_section"])
    with_pref = sum(1 for j in processed if j["preferred_section"])
    print(f"{before}개 → 비기술 -{filtered_non_tech} / 중복 -{filtered_dup} → {total}개")
    print(f"  required 섹션 파싱: {with_req}/{total} ({with_req/total*100:.0f}%)")
    print(f"  preferred 섹션 파싱: {with_pref}/{total} ({with_pref/total*100:.0f}%)")

    return processed
