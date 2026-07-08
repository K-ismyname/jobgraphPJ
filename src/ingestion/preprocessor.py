# Muse 원본 JSON을 Neo4j 적재용 중간 포맷으로 변환하는 전처리 모듈
#
# 이 파일 하나가 하는 일: pipeline.py의 Step 1이 호출하는 실제 작업자.
# The Muse가 준 HTML 섞인 원본 공고를 받아서
# ① HTML 제거 → ② 필수/우대 요건 섹션 분리 → ③ 비기술 직군·중복 제거 → ④ 표준 dict로 변환
# 까지를 담당한다. pipeline.py는 "언제 실행할지"만 정하고, "어떻게 정제할지"는 전부 여기 있다.

from __future__ import annotations
# 구버전 파이썬에서도 `tuple[str, str]`, `str | Path` 같은 최신 타입 문법을 쓸 수 있게 해주는 선언

import html   # HTML 엔터티(&amp; 등)를 실제 문자로 바꿔주는 표준 라이브러리
import json   # JSON 파일 ↔ 파이썬 데이터 변환
import re     # 정규표현식(regex) — 문자열에서 패턴을 찾거나 바꿀 때 사용
from pathlib import Path  # 파일 경로 객체

# 공고 본문에서 "필수 요건" 섹션으로 인식할 헤더 문구 모음
# (예: <b>Requirements</b> 다음에 오는 내용을 required_section으로 분류)
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
# frozenset([...]) = "값이 안 바뀌는(freeze된) 집합". set과 같지만 한번 만들면 항목을 추가/삭제할 수 없음.
# 코드 어디서도 이 목록을 바꿀 일이 없는 "고정된 상수 목록"이라는 의도를 드러내려고 frozenset을 씀.
# 집합(set)을 쓰는 이유: 리스트보다 "이 값이 안에 있는지"(in 연산) 확인하는 속도가 훨씬 빠름.

# 공고 본문에서 "우대 요건" 섹션으로 인식할 헤더 문구 모음
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
    # re.sub(패턴, 바꿀문자열, 대상문자열)은 "대상문자열에서 패턴에 맞는 부분을 전부 찾아 바꿔치기"하는 함수
    text = html.unescape(raw)
    # html.unescape("&amp;")는 "&"로 복원해줌. 원본에 &lt;, &#39; 같은 이스케이프된 문자가 있으면 여기서 실제 문자로 바뀜.
    text = re.sub(r"<br\s*/?>|</p>|</li>", "\n", text, flags=re.IGNORECASE)
    # 정규식 해설: <br\s*/?>  → <br>, <br/>, <br  /> 처럼 br 태그의 여러 변형을 매칭
    #             |          → "또는"(or) 기호. 세 가지 패턴 중 아무거나 매칭되면 됨
    #             </p>, </li> → 닫는 태그 그대로
    # 이 세 가지를 개행문자(\n)로 바꿈. flags=re.IGNORECASE는 <BR>처럼 대문자로 써도 매칭되게 함.
    text = re.sub(r"<li\s*>", "• ", text, flags=re.IGNORECASE)
    # <li> 여는 태그를 불릿 기호(• )로 바꿈. 위에서 </li>(닫는 태그)는 이미 개행으로 바뀌었으므로 순서가 중요함.
    text = re.sub(r"<[^>]+>", "", text)
    # <[^>]+> 해설: <로 시작, >가 아닌 문자([^>])가 1개 이상(+), >로 끝 → "<...>" 형태의 모든 남은 태그
    # 이걸 빈 문자열("")로 바꿔서 사실상 삭제. <div>, <strong>, <em> 등 태그 이름 상관없이 전부 제거됨.
    text = re.sub(r"[ \t]+", " ", text)
    # 스페이스나 탭이 1개 이상 연속되면 스페이스 1개로 압축 (여러 칸 띄어쓰기 정리)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # \n{3,} = 개행이 3번 이상 연속되면, 그걸 2번짜리 개행으로 줄임 (문단 사이 여백을 적당히만 남김)
    return text.strip()
    # .strip()은 문자열 맨 앞/뒤의 공백·개행을 제거하는 메서드


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
    # -> tuple[str, str] : 이 함수는 문자열 두 개를 하나로 묶은 "튜플"을 반환한다는 타입 힌트.
    # 실제로 마지막 줄에서 "return A, B" 형태로 반환하면 파이썬이 자동으로 (A, B) 튜플을 만들어줌.

    # 1단계: 일부 공고는 HTML 엔터티로 이중 이스케이프된 경우가 있어 먼저 unescape
    unescaped = html.unescape(contents)

    # 2단계: <b>, <strong>, <h2>, <h3> 태그를 기준으로 본문을 통째로 쪼갠다.
    # <b\b> 패턴: <br>, <button> 등 다른 태그와 혼동하지 않기 위해 단어 경계(\b) 사용
    # <b>는 매칭되지만 <br>은 매칭되지 않음 — Apple처럼 <br>이 많은 공고에서 오파싱 방지
    parts = re.split(r"<(?:b\b|strong|h[23])[^>]*>(.*?)</(?:b\b|strong|h[23])>", unescaped, flags=re.DOTALL | re.IGNORECASE)
    # re.split(패턴, 문자열)은 "문자열을 패턴이 매칭되는 지점마다 잘라서 리스트로 만드는" 함수.
    # 정규식 해설:
    #   (?:b\b|strong|h[23])  → "그룹이지만 캡처는 안 함"(?:...) 표시. b(단어경계) 또는 strong 또는 h2/h3 중 하나
    #   [^>]*                  → 태그 안에 속성이 더 있어도(<b class="x">) 매칭되도록 > 전까지 아무 문자나 허용
    #   (.*?)                  → 괄호로 감싸면 "캡처 그룹" — 이 안에 매칭된 내용이 결과에 포함됨. .*?는 "최대한 짧게" 매칭
    #   flags=re.DOTALL         → .이 개행문자(\n)까지 포함해서 매칭하게 함 (본문이 여러 줄이어도 캡처되게)
    # re.split이 캡처 그룹을 포함해 쪼개므로 결과는 다음과 같은 배열이 됨:
    # parts = [헤더 앞의 일반 텍스트, 헤더1, 헤더1 다음 본문, 헤더2, 헤더2 다음 본문, ...]

    required_chunks: list[str] = []  # 필수 요건으로 분류된 텍스트 조각들
    preferred_chunks: list[str] = []  # 우대 요건으로 분류된 텍스트 조각들

    # 3단계: (헤더, 본문) 쌍을 하나씩 순회하며 분류
    # parts[0]은 헤더가 아니라 서두 텍스트이므로 건너뛰고, 홀수 인덱스(헤더)부터 2칸씩 이동
    for i in range(1, len(parts), 2):
        # range(시작, 끝, 증가폭) → range(1, len(parts), 2)는 1, 3, 5, 7... 처럼 1부터 홀수만 순서대로 생성
        # parts 배열이 [서두, 헤더1, 본문1, 헤더2, 본문2, ...] 구조라서, 헤더는 인덱스 1, 3, 5...에 있음
        raw_header_text = re.sub(r"<[^>]+>", "", parts[i]).strip()
        # 혹시 헤더 안에 남은 다른 태그(<span> 등)가 있으면 제거하고 앞뒤 공백 정리
        header = raw_header_text.lower().rstrip(":")
        # 소문자로 통일 + 맨 끝의 콜론(:)만 제거(rstrip은 "오른쪽 끝에서부터"만 제거) → "Requirements:" → "requirements"
        body = parts[i + 1] if i + 1 < len(parts) else ""
        # 삼항 표현식: i+1이 배열 범위 안에 있으면 그 값을(헤더 바로 다음 본문), 없으면(배열 끝) 빈 문자열을 씀

        # 3-1. 헤더 길이로 두 가지 HTML 패턴을 구분
        # 짧은 헤더 = 실제 섹션 제목 → body가 섹션 내용
        # 긴 헤더 = <b>가 콘텐츠 블록을 감싼 경우 → 헤더 텍스트 자체가 섹션 내용
        if len(header) > _MAX_HEADER_LEN:
            clean = raw_header_text.strip()
            # 긴 블록이 보상·복지 위주면 요건 섹션으로 분류 불가 → 건너뜀
            noise_hits = len(_NOISE_SIGNALS.findall(clean))
            # .findall(문자열)은 그 문자열 안에서 패턴에 매칭되는 모든 부분을 리스트로 찾아줌 → len()으로 개수만 셈
            req_hits = len(_REQ_SIGNALS.findall(clean))
            if noise_hits > req_hits:
                continue  # continue는 "이번 반복은 여기서 중단하고 다음 반복(i+=2)으로 넘어가라"는 명령
        else:
            clean = strip_html(body).strip()

        if not clean:
            continue  # 내용이 비어있으면 분류할 것도 없으니 건너뜀

        # 3-2. 헤더 문구로 required/preferred 분류
        # preferred 체크를 먼저 — "preferred qualifications"이 "qualifications" 키워드로
        # required에 잘못 분류되는 것을 방지
        if header in _PREFERRED_HEADERS or "preferred" in header or any(
            kw in header for kw in ("nice to have", "bonus points", "plus")
        ):
            # "header in _PREFERRED_HEADERS" → header 문자열이 그 frozenset 안에 정확히 일치하는 게 있는지
            # "preferred" in header → header 문자열 "안에" "preferred"라는 부분 문자열이 포함되는지 (부분 일치)
            # any(...)는 괄호 안 세 키워드 중 하나라도 header에 포함되면 True
            preferred_chunks.append(clean)
        elif header in _REQUIRED_HEADERS or any(
            kw in header for kw in ("required", "qualifications", "requirements", "must")
        ):
            required_chunks.append(clean)
        # 어느 쪽에도 안 걸리면 (예: "About the company" 같은 무관한 헤더) 그냥 버림 (else 블록 자체가 없음)

    # 4단계: 여러 조각으로 나뉜 텍스트를 각각 하나의 문자열로 합쳐서 반환
    return "\n\n".join(required_chunks), "\n\n".join(preferred_chunks)
    # "구분자".join(리스트)는 리스트 안 문자열들을 그 구분자로 이어붙여 하나의 문자열로 만드는 메서드
    # 여기서는 조각들 사이에 빈 줄 하나(\n\n)를 넣어서 이어붙임
    # "A, B" 형태로 반환하면 파이썬이 자동으로 (A, B) 튜플로 묶어줌 → 함수 시그니처의 tuple[str, str]과 일치


_BULLET_RE = re.compile(r"^[•\-\*]\s+.{10,}")  # 최소 10자 이상인 불릿 라인 (너무 짧은 불릿은 노이즈로 간주)
# re.compile(패턴)은 정규식을 미리 컴파일해서 변수에 저장해두는 것 — 같은 패턴을 여러 번 쓸 때 매번 새로 해석 안 해도 되어 빠름
# 패턴 해설: ^ (줄 시작) [•\-\*] (•, -, * 중 하나) \s+ (공백 1개 이상) .{10,} (아무 문자나 10개 이상)

# 요건 클러스터 점수 올리는 패턴 (Muse HTML + Adzuna 평문 공통)
# "3+ years", "experience with", "proficient in" 처럼 실제 요건 문장에 자주 나오는 표현들
_REQ_SIGNALS = re.compile(
    r"\d+\+?\s*years?|experience\s+with|proficient\s+in|knowledge\s+of"
    r"|familiarity\s+with|strong\s+understanding|ability\s+to|skilled\s+in"
    r"|background\s+in|expertise\s+in|demonstrated|degree\s+in|bachelor"
    r"|must\s+have|must\s+be|you\s+must|you\s+will\s+have|you\s+'ll\s+have"
    r"|you\s+should\s+have|we\s+require|required\s+to|looking\s+for"
    r"|ideal\s+candidate|at\s+least|minimum\s+of|\bessential\b|proven\s+experience",
    re.IGNORECASE,
)
# 긴 문자열 여러 줄이 나란히 있는 건 파이썬이 자동으로 이어붙여서 한 문자열로 취급하기 때문 (줄바꿈 안에 콤마 없음)
# \d+\+? → 숫자 1개 이상, 그 뒤에 +기호가 있어도 되고 없어도 됨 (예: "3" 또는 "3+")
# years? → year 뒤의 s가 있어도 되고 없어도 됨 (year 또는 years 둘 다 매칭)
# \s+ → 공백 1개 이상 (단어 사이 간격)
# \b essential \b → 단어 경계로 감싸서 "essential"이라는 단어 자체만 매칭 (예: "nonessential"에서는 매칭 안 되게)

# 복지/노이즈 클러스터 점수 깎는 패턴
# "PTO", "dental", "401k" 처럼 요건이 아니라 복리후생을 설명하는 문장에 나오는 표현들
_NOISE_SIGNALS = re.compile(
    r"\bpto\b|dental|insurance|parental\s+leave|fertility|equity|stock\s+option"
    r"|salary|compensation|401k|remote\s+work|hybrid|commuter|stipend|perks",
    re.IGNORECASE,
)


def extract_bullet_section(text_clean: str, min_bullets: int = 4) -> str:
    """text_clean에서 요건 불릿 클러스터를 추출.

    연속된 불릿 묶음(클러스터)을 모두 찾은 뒤,
    요건 키워드가 많고 복지·노이즈 키워드가 적은 클러스터를 반환.
    (extract_sections()가 <b> 헤더를 못 찾아 실패했을 때 쓰는 2차 시도)
    """
    lines = text_clean.split("\n")
    # "구분자".split(구분자)는 join의 반대 — 문자열을 구분자 기준으로 잘라 리스트로 만듦. 여기선 줄 단위로 쪼갬
    clusters: list[list[str]] = []  # 불릿이 연속으로 이어진 묶음들의 리스트 (리스트 안에 리스트가 들어있는 구조)
    current: list[str] = []  # 지금 만들고 있는 클러스터 (아직 확정 안 된 임시 묶음)
    gap = 0  # 불릿이 아닌 줄이 연속으로 몇 번 나왔는지 세는 카운터

    # 1단계: 줄 단위로 훑으면서 불릿이 연속되는 구간을 클러스터로 묶음
    for line in lines:
        stripped = line.strip()
        if _BULLET_RE.match(stripped):
            # .match(문자열)은 그 문자열이 "맨 앞부터" 패턴과 일치하는지 검사 (findall과 달리 하나만, 앞부분만 확인)
            current.append(stripped)
            gap = 0  # 불릿을 만났으니 공백 카운트 초기화
        else:
            if current:  # current가 비어있지 않다면(=지금까지 불릿을 하나라도 모아뒀다면)
                gap += 1
                if gap > 2:  # 불릿 없는 줄이 3번 넘게 이어지면 클러스터가 끝난 것으로 판단
                    clusters.append(current[:])
                    # current[:] → current 리스트를 통째로 복사한 새 리스트. 그냥 current를 넣으면
                    # 나중에 current를 비울 때(= []) clusters 안의 것까지 같이 사라지는 걸 방지하기 위한 안전한 복사
                    current = []  # 새 클러스터를 담을 준비를 위해 초기화
                    gap = 0

    if current:  # 마지막까지 만들던 클러스터가 남아있으면 추가
        clusters.append(current)

    # 2단계: 너무 짧은 클러스터(불릿 4개 미만)는 요건 섹션으로 보기 어려우니 제외
    valid = [c for c in clusters if len(c) >= min_bullets]
    if not valid:
        return ""

    # 3단계: 클러스터별로 "요건다움" 점수를 매겨 가장 높은 것을 채택
    def score(cluster: list[str]) -> float:
        # 함수 안에 함수를 정의하는 것 — "중첩 함수". score()는 extract_bullet_section() 밖에서는 못 씀
        text = " ".join(cluster)  # 클러스터 안 불릿 줄들을 공백으로 이어붙여 하나의 문자열로 만듦
        req_hits = len(_REQ_SIGNALS.findall(text))
        noise_hits = len(_NOISE_SIGNALS.findall(text))
        # 요건 신호 가중치 2, 노이즈 패널티 3, 길이 보너스 0.1
        return req_hits * 2 - noise_hits * 3 + len(cluster) * 0.1

    best = max(valid, key=score)
    # max(리스트, key=함수) → 리스트의 각 항목에 함수를 적용한 결과값이 가장 큰 항목을 찾아줌
    # 즉 "valid 안의 클러스터들 중 score() 점수가 제일 높은 걸 골라라"는 뜻
    # 점수가 0 이하면 요건 클러스터로 보기 어려움 → 빈 문자열 반환
    return "" if score(best) <= 0 else "\n".join(best)


def extract_requirement_sentences(text_clean: str, min_sentences: int = 3) -> str:
    """불릿 없는 서술형 공고에서 요건 문장을 추출.

    _REQ_SIGNALS 패턴이 포함된 문장만 모아 반환.
    min_sentences 미만이면 빈 문자열 반환.
    (extract_sections(), extract_bullet_section() 둘 다 실패했을 때 쓰는 3차 시도)
    """
    # 1단계: 마침표/느낌표/물음표 뒤 공백, 또는 줄바꿈을 기준으로 문장 분리
    raw_sentences = re.split(r"(?<=[.!?])\s+|\n", text_clean)
    # (?<=[.!?]) 는 "lookbehind" — ".", "!", "?" 중 하나 "바로 뒤"라는 위치 조건 (그 문자 자체는 분리 결과에 남김)
    # \s+ 는 그 뒤에 오는 공백. 즉 "문장부호+공백"을 기준으로 자르되, 문장부호 자체는 앞 문장에 남게 함
    # | \n → 또는 그냥 줄바꿈 기준으로도 자름

    # 2단계: 너무 짧은 문장(20자 이하)은 제외하고, 요건 신호 패턴이 있는 문장만 채택
    req_sentences = [
        s.strip()
        for s in raw_sentences
        if len(s.strip()) > 20 and _REQ_SIGNALS.search(s)
    ]
    # 리스트 컴프리헨션: raw_sentences를 하나씩(s) 보면서, "다듬은 길이가 20자 넘고 AND 요건 신호가 검색되면"
    # .search(문자열)은 문자열 "어디에든" 패턴이 있으면 찾아줌 (.match와 달리 맨 앞이 아니어도 됨)
    return "" if len(req_sentences) < min_sentences else "\n".join(req_sentences)


def preprocess_job(raw: dict) -> dict:
    """Muse 원본 공고 1개를 파이프라인 중간 포맷으로 변환.

    반환 포맷은 neo4j_client.ingest_posting()이 기대하는 키 구조와 호환됨.
    스킬 추출 전 단계이므로 "skills" 키는 없음.
    """
    # ── 1단계: 본문 정제 ──────────────────────────
    contents = raw.get("contents", "")
    # raw.get("contents", "") → raw 딕셔너리에서 "contents" 키를 찾되, 없으면 에러 대신 빈 문자열("")을 씀
    text_clean = strip_html(contents)  # HTML 태그 제거한 순수 텍스트 (fallback 추출용으로도 쓰임)
    required_section, preferred_section = extract_sections(contents)  # 1차 시도: 헤더 기반 섹션 추출
    # extract_sections()가 튜플 (A, B)를 반환하므로, 이렇게 "변수1, 변수2 = 튜플"로 각각 받을 수 있음

    # '•' 같이 기호만 남은 섹션은 실질적으로 빈 것으로 처리
    # (Celonis 패턴: <strong>헤더</strong> 뒤 <li> 여는 태그만 남아 '•' 생성)
    if len(required_section.strip()) < 10:
        required_section = ""

    # ── 2단계: 1차 시도가 실패했으면 fallback 순서대로 재시도 ──
    # 불릿 클러스터 → 요건 문장 순으로 추출 (extract_sections 실패 시 대비책)
    bullet_section = ""
    if not required_section:
        # required_section이 빈 문자열이면(파이썬에서 빈 문자열은 "거짓"으로 취급) 이 블록 실행
        bullet_section = extract_bullet_section(text_clean)
        if not bullet_section:
            bullet_section = extract_requirement_sentences(text_clean)

    # ── 3단계: 회사/위치/레벨 등 메타데이터 추출 ──────
    company_info = raw.get("company", {})
    company_name = (
        company_info.get("name", "") if isinstance(company_info, dict) else str(company_info)
    )
    # isinstance(값, 타입) → 그 값이 그 타입인지 확인. company_info가 dict면 .get()으로 안전 조회,
    # dict가 아니면(예: 그냥 문자열이면) str()로 문자열 변환해서 그대로 사용 — 두 가지 데이터 형태 모두 대비

    locations = raw.get("locations", [])
    location = locations[0]["name"] if locations else ""  # 첫 번째 위치만 사용
    # "locations[0]" → 리스트의 첫 번째 항목 (인덱스 0). "if locations"는 리스트가 비어있지 않을 때만 참
    # 리스트가 비어있으면([]) 인덱스 0을 꺼내려다 에러가 나므로, 삼항 표현식으로 미리 방어

    levels = raw.get("levels", [])
    level = levels[0]["name"] if levels else ""  # 첫 번째 레벨만 사용

    url = (raw.get("refs") or {}).get("landing_page", "")
    # raw.get("refs")가 None이면(키 자체가 없으면) "or {}"가 작동해서 빈 딕셔너리를 대신 씀
    # 그래야 바로 뒤의 .get("landing_page", "")를 None에 대고 호출하는 에러를 방지할 수 있음
    created = raw.get("publication_date") or "2025-01-01T00:00:00Z"  # 값이 없으면 임의 기본값
    # publication_date가 None이거나 빈 문자열이면 "or" 뒤의 기본 날짜 문자열을 대신 씀

    # ── 4단계: 파이프라인 중간 포맷(dict)으로 조립해 반환 ──
    return {
        "id": f"muse-{raw['id']}",  # 다른 소스와 id 충돌 방지를 위해 "muse-" 접두사
        # raw['id']는 raw.get("id")와 달리, 키가 없으면 진짜 에러를 냄 (id는 반드시 있어야 하는 필수 값이라서)
        "title": raw.get("name", ""),
        "company": company_name,
        "location": location,
        "level": level,
        "url": url,
        "created": created,
        "salary_min": None,   # The Muse는 연봉 정보를 안 줌 → 항상 None
        "salary_max": None,
        "contract_type": raw.get("type", ""),
        "text_clean": text_clean,
        "required_section": required_section,
        "preferred_section": preferred_section,
        "bullet_section": bullet_section,
        "category": raw.get("_collected_category", ""),  # collect_muse.py가 태깅한 카테고리
        "source": "themuse",
    }
    # 이 함수는 dict 하나를 "return { 키: 값, ... }" 형태로 즉석에서 만들어 바로 반환함
    # (미리 변수에 담아뒀다가 반환하는 대신, 딕셔너리 리터럴을 그 자리에서 만드는 방식)


# 비기술 직군으로 간주해 제외할 타이틀 키워드
_NON_TECH_TITLE_KEYWORDS = frozenset([
    "engineering manager", "engineering director", "engineering program manager",
    "head of engineering", "vp of engineering", "vice president",
    "hardware engineer", "mechanical engineer", "electrical engineer",
    "civil engineer", "reliability engineer", "test engineer",
    "quality engineer", "qa engineer", "value engineering",
    # collect_muse.py의 is_relevant()가 제목에 "engineer"만 있으면 통과시켜서 실제로 섞여
    # 들어왔던 오탐 사례들 (배관·기계 계열, IT 헬프데스크성 지원 업무)
    "field engineer", "support engineer", "it support",
])


def is_tech_job(title: str) -> bool:
    """비기술 직군(관리직·하드웨어·QA 등)이면 False 반환."""
    t = title.lower()
    return not any(kw in t for kw in _NON_TECH_TITLE_KEYWORDS)
    # any(...)가 "제외 키워드 중 하나라도 제목에 있으면 True"를 계산하고,
    # 맨 앞의 not이 그 결과를 뒤집음 → "제외 키워드가 하나도 없어야(=기술 직군이어야) True"


def preprocess_file(
    input_path: str | Path,
    output_path: str | Path,
) -> list[dict]:
    """raw JSON 파일을 읽어 전처리 후 저장.

    중복 (title+company) 제거 및 비기술 직군 필터링 포함.
    """
    input_path = Path(input_path)
    output_path = Path(output_path)
    # 매개변수로 문자열이 들어와도 Path 객체로 통일 — 이미 Path였어도 Path()로 다시 감싸면 그대로 유지됨

    # ── 1단계: 원본 JSON 로드 ──────────────────────
    with open(input_path, encoding="utf-8") as f:
        raw_jobs: list[dict] = json.load(f)
        # json.load(파일객체)는 파일 안의 JSON 텍스트를 읽어서 파이썬 리스트/딕셔너리로 바꿔줌
        # 이 파일(jobs_raw_muse.json)은 최상위가 배열이므로 raw_jobs는 dict들의 리스트가 됨

    # ── 2단계: 공고 하나하나를 preprocess_job()으로 변환 ──
    processed_all = [preprocess_job(job) for job in raw_jobs]
    # 리스트 컴프리헨션: raw_jobs 안의 공고(job)를 하나씩 꺼내 preprocess_job()에 통과시킨 결과로 새 리스트를 만듦
    before = len(processed_all)  # 필터링 전 개수를 기록해둠 (나중에 몇 개가 걸러졌는지 계산하려고)

    # ── 3단계: 비기술 직군 제거 ─────────────────────
    processed_all = [j for j in processed_all if is_tech_job(j["title"])]
    filtered_non_tech = before - len(processed_all)

    # ── 4단계: (title+company) 중복 제거 — 먼저 나온 것 유지 ──
    # collect_muse.py는 id 기준으로 중복을 걸렀지만, id가 달라도
    # 같은 회사가 같은 제목의 공고를 재게시하는 경우가 있어 한 번 더 거름
    seen: set[tuple[str, str]] = set()
    # set 안의 항목이 튜플(제목, 회사) 쌍 — "이 조합을 이미 본 적 있는지"를 빠르게 확인하려고 집합을 씀
    processed: list[dict] = []
    for j in processed_all:
        key = (j["title"].strip().lower(), j["company"].lower())
        # (A, B) 형태로 값 두 개를 괄호로 묶으면 튜플이 만들어짐 — 이 튜플을 seen에 넣고 뺄 "고유 열쇠"로 씀
        if key not in seen:
            seen.add(key)
            processed.append(j)
        # key가 이미 seen에 있으면 (=이미 나온 제목+회사 조합) 아무것도 안 하고 그냥 넘어감 → 자동으로 걸러짐
    filtered_dup = len(processed_all) - len(processed)

    # ── 5단계: 결과 저장 ────────────────────────────
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(processed, f, ensure_ascii=False, indent=2)

    # ── 6단계: 처리 결과 요약 출력 (섹션 파싱 성공률 확인용) ──
    total = len(processed)
    with_req = sum(1 for j in processed if j["required_section"])
    # sum(1 for j in processed if 조건) → 조건을 만족하는 j가 나올 때마다 1을 더해서 개수를 세는 관용적인 패턴
    # (조건을 만족하는 j만 골라 리스트로 만든 뒤 len()을 쓰는 것과 결과는 같지만, 리스트를 안 만들어서 메모리를 아낌)
    with_pref = sum(1 for j in processed if j["preferred_section"])
    print(f"{before}개 → 비기술 -{filtered_non_tech} / 중복 -{filtered_dup} → {total}개")
    if total:   # 전량 필터링돼 0개면 ZeroDivisionError 방지
        print(f"  required 섹션 파싱: {with_req}/{total} ({with_req/total*100:.0f}%)")
        print(f"  preferred 섹션 파싱: {with_pref}/{total} ({with_pref/total*100:.0f}%)")
        # :.0f 는 f-string 포맷 문법 — 소수점 없이(0f) 정수 형태로 반올림해서 표시

    return processed
