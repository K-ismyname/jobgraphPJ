# 채용공고·이력서에서 기술스택을 LLM으로 추출하는 모듈
#
# 이 파일이 하는 일: pipeline.py의 Step 2(step_extract_skills)가 호출하는 실제 LLM 작업자.
# 전처리된 공고 텍스트(required_section 등)를 GPT에게 보여주고,
# "이 공고가 요구하는 기술명 리스트"를 JSON으로 뽑아오는 역할을 담당한다.
# 이력서 추출(extract_skills_from_resume)도 같은 파일에 있는데, 이건 포트폴리오 분석(Layer 4)에서 쓸 함수다.

import json  # LLM이 돌려준 JSON 문자열을 파이썬 dict로 변환할 때 사용
import os    # 환경변수(OPENAI_API_KEY)를 읽을 때 사용
from typing import Literal
# Literal["high", "medium", "low"] 처럼, "이 값은 반드시 이 몇 가지 문자열 중 하나여야 한다"고
# 타입 체커에게 알려주는 특수 타입. str이면 아무 문자열이나 되지만, Literal은 후보를 제한함.

from openai import OpenAI
from pydantic import BaseModel, Field
# pydantic은 "데이터가 정해진 형태(타입)를 따르는지 자동으로 검증해주는" 라이브러리.
# BaseModel을 상속한 클래스는 필드 타입이 안 맞으면 즉시 에러를 내는 "데이터 형식 검사기"가 됨.
# Field(description="...")는 그 필드가 무엇을 뜻하는지 설명을 붙이는 것 (문서화 + 나중에 스키마 생성에도 쓰일 수 있음).


# ── 이력서용 모델 ────────────────────────────────────────────────
# 아래 세 클래스는 "이력서에서 뽑아낸 결과가 이런 모양이어야 한다"는 틀(스키마)을 미리 정의해둔 것.
# class 이름(BaseModel): 형태로 정의하면, 나중에 ResumeExtraction(**딕셔너리)처럼 호출했을 때
# 그 딕셔너리가 이 틀과 안 맞으면 (예: candidate_name이 없거나 타입이 다르면) pydantic이 즉시 에러를 냄.

class DemonstratedSkill(BaseModel):
    """이력서 안에서 확인된 스킬 하나를 표현하는 모델. (스킬명, 카테고리, 근거 문장, 확신도)"""
    name: str = Field(description="정규화된 기술명")
    category: str = Field(description="language/framework/database/cloud/tool/concept")
    evidence: str = Field(description="이력서 원문 발췌 (1~2문장)")
    confidence: Literal["high", "medium", "low"]
    # confidence는 반드시 "high", "medium", "low" 셋 중 하나여야 함 — CLAUDE.md의 confidence 레벨 규칙과 일치


class PortfolioSection(BaseModel):
    """이력서의 한 섹션(프로젝트/경력/학력 등)과 그 안에서 발견된 스킬들."""
    section_type: str = Field(description="experience/project/education/skills")
    title: str
    skills: list[DemonstratedSkill]
    # list[DemonstratedSkill] → "DemonstratedSkill 모델 여러 개를 담은 리스트"라는 뜻.
    # pydantic이 이 리스트 안의 각 항목까지 재귀적으로 검증해줌 (중첩된 모델 검증)


class ResumeExtraction(BaseModel):
    """이력서 하나를 통째로 추출한 최종 결과. candidate_name + 섹션들의 리스트."""
    candidate_name: str
    sections: list[PortfolioSection]


def _get_client() -> OpenAI:
    """OpenAI 클라이언트 생성. pipeline.py의 _get_openai()와 거의 동일한 역할 — 이 파일 안에서 독립적으로 필요."""
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise EnvironmentError(
            "OPENAI_API_KEY 환경변수가 필요합니다. .env 파일을 확인하세요."
        )
    return OpenAI(api_key=key)


# 이력서 전체를 한 번에 처리 (gpt-4o-mini 128K 컨텍스트는 현실 이력서를 모두 수용)
_RESUME_TEXT_CAP = 100_000
# 100_000 은 100000과 완전히 같은 숫자 — 파이썬은 숫자 안에 언더스코어(_)를 넣어도 무시하고 읽음.
# 자릿수가 많은 숫자를 사람이 읽기 편하게(10만) 쓰려고 관례적으로 씀.

# 공고 섹션 잘림 상한 (현실 공고 최대 ~13K자를 넉넉히 수용 — 기존 2000/3000은 다수 공고를 잘랐음)
_POSTING_TEXT_CAP = 20_000
# 이 숫자가 왜 있는가: LLM에 보내는 텍스트가 너무 길면 비용이 늘고, 모델의 컨텍스트 한도를 넘을 수도 있어서
# "최대 이만큼까지만 보낸다"는 상한을 걸어둠. 주석에 적힌 대로 예전엔 이 값이 너무 작아서(2000/3000)
# 긴 공고가 중간에 잘려 정보 손실이 있었다는 과거 문제 이력이 있음.


def _chat_json(client: OpenAI, prompt: str, max_tokens: int = 1024) -> dict:
    """LLM에 JSON 응답을 요청하고 파싱해 dict로 반환한다.

    response_format=json_object로 비JSON·펜스 응답을 원천 차단하고, temperature=0으로
    결정성을 확보한다. 파싱/API 실패 시 1회 재시도한 뒤에도 실패하면 예외를 올린다
    (호출부 파이프라인이 실패 건수를 집계·스킵).
    """
    # 이 함수는 extract_skills_from_resume()와 extract_skills_from_posting() 둘 다에서 재사용하는
    # "LLM 호출 + JSON 파싱 + 재시도"의 공통 로직 — 중복 코드를 피하려고 별도 함수로 뽑아둔 것

    last_err: Exception | None = None
    # 마지막으로 발생한 에러를 기억해두는 변수. 처음엔 에러가 없으니 None으로 시작.
    for attempt in range(2):
        # range(2) → 0, 1 두 번 반복. 즉 "최대 2번까지 시도"(최초 시도 1번 + 재시도 1번)한다는 뜻
        try:
            resp = client.chat.completions.create(
                model="gpt-4o-mini",   # CLAUDE.md 확정 스택의 기본 모델
                temperature=0,
                # temperature는 "답변의 무작위성" 조절 값(보통 0~1+). 0으로 두면 매번 거의 같은 답이 나오도록
                # 최대한 결정적(deterministic)으로 만듦 — 스킬 추출은 창의성이 필요 없고 일관성이 중요하기 때문
                max_tokens=max_tokens,  # 응답으로 받을 최대 글자수(토큰 수) 제한
                response_format={"type": "json_object"},
                # 이 옵션을 주면 OpenAI가 "반드시 유효한 JSON 형식으로만 응답하도록" 강제해줌.
                # 이게 없으면 모델이 "```json ... ```" 코드 펜스를 붙이거나 설명 문장을 섞어서 응답할 수 있어서
                # 파싱이 실패하기 쉬운데, 이 옵션으로 그 문제를 원천 차단함
                messages=[{"role": "user", "content": prompt}],
                # OpenAI 채팅 API는 "역할(role)+내용(content)" 형태의 메시지 리스트를 받음.
                # 여기선 사용자(user) 역할로 프롬프트 하나만 보냄 (대화 기록 없이 단발성 요청)
            )
            raw = (resp.choices[0].message.content or "").strip()
            # resp.choices[0] → API가 여러 개의 답변 후보를 줄 수 있는데, 그중 첫 번째(기본값)만 사용
            # .message.content가 None일 가능성에 대비해 "or \"\""로 방어 후 앞뒤 공백 제거
            return json.loads(raw)
            # json.loads(문자열)은 JSON 형식의 "문자열"을 파이썬 dict/list로 변환 (파일이 아니라 문자열 대상이라 loads)
            # 성공하면 여기서 함수가 즉시 끝남 (재시도 루프를 더 돌지 않음)
        except Exception as e:  # API 오류·파싱 실패 모두 재시도 대상
            last_err = e
            # 에러가 나면 여기로 와서 last_err에 기록해두고, for 루프가 다음 시도(attempt=1)로 넘어감
    raise ValueError(f"LLM JSON 파싱 실패(재시도 후): {last_err}")
    # for 루프를 2번 다 돌았는데도 return으로 빠져나가지 못했다는 건 두 번 다 실패했다는 뜻
    # → 마지막에 기록해둔 에러 내용을 포함해서 진짜 예외를 발생시킴 (호출한 쪽이 이 예외를 잡아서 처리)


# ── 이력서 기술 추출 ─────────────────────────────────────────────
def extract_skills_from_resume(
    text: str, client: OpenAI | None = None
) -> ResumeExtraction:
    """이력서 텍스트에서 섹션별 기술 추출."""
    # client: OpenAI | None = None → 클라이언트를 밖에서 만들어 넘겨줄 수도 있고, 안 넘기면 None이 기본값
    if client is None:
        client = _get_client()
        # 호출하는 쪽이 이미 만들어둔 클라이언트가 있으면 그걸 재사용하고,
        # 없으면(None) 이 함수가 직접 하나 만듦 — 매번 새로 만들지 않아도 되게 하는 유연한 설계

    if len(text) > _RESUME_TEXT_CAP:
        print(f"[skill_extractor] 이력서가 {len(text)}자 — 상한 {_RESUME_TEXT_CAP}자까지만 처리")
        text = text[:_RESUME_TEXT_CAP]
        # 이력서가 상한보다 길면, 앞부분 _RESUME_TEXT_CAP자까지만 잘라서 사용 (뒷부분은 버려짐)

    prompt = f"""다음은 이력서 텍스트입니다. 섹션별로 기술 스택을 추출하세요.

이력서:
{text}

규칙:
1. 각 프로젝트/경험을 별도 section으로 분리
2. 기술이 명시적으로 언급된 경우 confidence=high
3. 문맥상 사용했음을 알 수 있는 경우 confidence=medium
4. evidence는 이력서 원문에서 해당 기술을 사용했다는 문장을 그대로 발췌
5. 기술명은 표준 표기로 정규화 (React.js → React, 랭체인 → LangChain)

반드시 아래 JSON 형식으로만 응답하세요:
{{
  "candidate_name": "홍길동",
  "sections": [
    {{
      "section_type": "project",
      "title": "Agentic RAG 시스템",
      "skills": [
        {{
          "name": "LangGraph",
          "category": "framework",
          "evidence": "LangGraph를 활용한 멀티에이전트 파이프라인 구축",
          "confidence": "high"
        }}
      ]
    }}
  ]
}}"""
    # f-string(f"""...""")으로 여러 줄 프롬프트를 작성. 안의 {text}는 실제 이력서 텍스트로 치환됨.
    # {{ }} 이중 중괄호를 쓴 이유: f-string에서 { }는 "변수를 넣는 자리"라는 특수 의미가 있어서,
    # 프롬프트 안에 진짜 JSON 예시의 { } 기호를 그대로 보여주려면 이스케이프로 {{ }}처럼 두 번 써야 함.
    # 이렇게 "예시 응답 형식을 프롬프트에 미리 보여주는 방식"을 few-shot 예시라고 부름 — 모델이 형식을 따라하게 유도.

    return ResumeExtraction(**_chat_json(client, prompt, max_tokens=4096))
    # _chat_json()이 dict를 반환하면, **딕셔너리로 그 dict를 "키워드 인자들"로 풀어서 ResumeExtraction(...)에 넣음
    # 예: {"candidate_name": "홍길동", "sections": [...]} → ResumeExtraction(candidate_name="홍길동", sections=[...])
    # 이 시점에 pydantic이 실제로 이 dict가 ResumeExtraction 모델과 맞는 형태인지 검증함 (안 맞으면 에러)


# ── 전처리된 채용공고 스킬 추출 ──────────────────────────────────────
def extract_skills_from_posting(
    job: dict, client: OpenAI | None = None
) -> dict[str, list[str]]:
    """전처리된 공고에서 required/preferred 스킬명 추출.

    Returns:
        {"required": ["Python", "RAG", ...], "preferred": ["Docker", ...]}
    """
    # 이 함수가 바로 pipeline.py의 step_extract_skills()가 각 공고마다 호출하는 그 함수
    if client is None:
        client = _get_client()

    required_text = job.get("required_section") or job.get("bullet_section") or ""
    # "A or B or C" 패턴: A가 있으면(빈 문자열이 아니면) A를 쓰고, A가 없으면 B, B도 없으면 C(빈 문자열)
    # 즉 우선순위대로 값을 고르는 방식 — preprocessor.py가 만든 required_section이 최우선,
    # 없으면 fallback으로 만들어둔 bullet_section, 그것도 없으면 빈 문자열
    preferred_text = job.get("preferred_section") or ""

    if required_text:
        # required_text(또는 fallback)가 하나라도 있으면 → "섹션이 잘 나뉜 공고"용 프롬프트 사용
        context_req = required_text[:_POSTING_TEXT_CAP]
        # [:_POSTING_TEXT_CAP] → 문자열 슬라이싱으로 앞에서부터 그 글자수까지만 자름 (너무 길면 자름)
        context_pref = preferred_text[:_POSTING_TEXT_CAP] if preferred_text else "(없음)"
        # 삼항 표현식: preferred_text가 있으면 잘라서 쓰고, 없으면 LLM에게 "(없음)"이라고 명시적으로 알려줌
        # (빈 문자열을 그냥 보내는 것보다, "없다"고 명시하는 게 모델이 헷갈리지 않게 하는 데 도움)
        prompt = f"""다음 채용공고 섹션에서 기술명만 추출하세요.

공고 제목: {job.get('title', '')}

[필수 자격 요건]
{context_req}

[우대 사항]
{context_pref}

아래 JSON 형식으로만 응답하세요. 다른 텍스트 없이:
{{
  "required": ["스킬A", "스킬B"],
  "preferred": ["스킬C"]
}}

규칙:
- 기술명은 표준 표기로 정규화 (React.js → React, LangChain → LangChain)
- 연차·학위·소프트스킬(커뮤니케이션 등)은 제외
- 기술이 아닌 도메인 지식(금융, 의료 등)도 제외
- 공고에 명시되지 않은 기술은 절대 추가하지 마세요"""
        # 마지막 규칙("절대 추가하지 마세요")이 중요 — LLM이 공고에 없는 기술을 "그럴듯하게 추측"해서
        # 지어내는 환각(hallucination)을 막기 위한 명시적 지시. CLAUDE.md의 "Agentic RAG" 핵심 문제의식과 연결됨.
    else:
        # required_text도 bullet_section도 다 없으면 → 최후의 수단으로 본문 전체(text_clean)를 통째로 사용
        full_text = (job.get("text_clean") or "")[:_POSTING_TEXT_CAP]
        prompt = f"""다음 채용공고에서 요구하는 기술명만 추출하세요.

공고 제목: {job.get('title', '')}
내용:
{full_text}

아래 JSON 형식으로만 응답하세요. 다른 텍스트 없이:
{{
  "required": ["스킬A", "스킬B"],
  "preferred": ["스킬C"]
}}

규칙:
- 기술명은 표준 표기로 정규화 (React.js → React)
- 명시적 필수 조건은 required, 우대/선호는 preferred
- 연차·학위·소프트스킬·도메인 지식은 제외"""
        # 이 분기는 required/preferred 구분이 안 된 상태라, "필수/우대를 네가(LLM이) 알아서 나눠봐"라고 요청하는
        # 좀 더 어려운(느슨한) 버전의 프롬프트 — preprocessor.py의 섹션 분리가 실패했을 때의 최후 대비책

    result = _chat_json(client, prompt, max_tokens=1500)
    # 위에서 만든 두 프롬프트 중 하나를 실제로 LLM에 보내고 JSON dict로 받음
    return {
        "required": result.get("required", []),
        "preferred": result.get("preferred", []),
    }
    # LLM이 혹시 "required" 또는 "preferred" 키를 빠뜨리고 응답해도, .get(키, [])로 안전하게 빈 리스트로 처리
    # 이 반환값이 pipeline.py의 step_extract_skills()에서 _normalize_skills()로 바로 넘겨짐
