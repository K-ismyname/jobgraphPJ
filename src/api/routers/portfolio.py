# 포트폴리오 엔드포인트 — 업로드 → v3 다중소스 분석 → 리포트 폴링
#
# 한 줄 요약: 이 프로젝트의 진짜 핵심 기능("이력서 올리면 갭 분석 + 코칭")이
# 실제 API로 연결되는 파일. 지금까지 본 supervisor.py(Layer 3) 전체를 실제로 실행시키는 곳.
#
# 이 파일의 API 흐름은 "한 번에 답이 안 나오는" 구조입니다:
# 1) 파일 업로드 → 2) 분석 시작 요청(바로 응답 옴, 아직 결과 아님) → 3) 결과가 나올 때까지 반복 조회(폴링)
# 왜 이렇게 하는가: gap_agent + coach_agent 그래프를 다 도는 데 시간이 꽤 걸려서(수십 초 단위),
# 브라우저가 그동안 멈춰서 기다리게 하는 대신 "일단 접수했다"고 바로 답하고, 나중에 따로 결과를 물어보게 함.

from __future__ import annotations

import asyncio
import logging
import os
import re
import secrets
import tempfile
import threading
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
# BackgroundTasks — "응답은 먼저 보내고, 이 작업은 응답 보낸 뒤에 이어서 해라"는 FastAPI 기능.
# run_in_threadpool — 시간이 걸리는 일반 함수를, 별도 작업자(스레드)에게 맡겨서 실행하는 도구.
# jobs.py에서 본 "def로 두면 자동으로 스레드풀에서 돈다"와 비슷한 목적인데, 여긴 async 함수 안에서
# "이 부분만" 콕 집어 스레드풀로 보내고 싶을 때 씀.

from src.api.deps import get_graph, get_neo4j, get_reports, get_uploads
from src.api.schemas import (
    AnalyzeAccepted,
    AnalyzeRequest,
    EvidenceCard,
    InterviewCoaching,
    LearningRecommendation,
    PortfolioUploadResponse,
    ProjectBrief,
    ProjectUnderstanding,
    ProjectSuggestion,
    RecommendedPosting,
    ReportResponse,
    RoadmapStep,
    UploadResponse,
    VerificationItem,
)
from src.agent.supervisor import run_supervisor
from src.portfolio.pdf_parser import extract_pdf_info
from src.storage.neo4j_client import Neo4jClient

router = APIRouter()
logger = logging.getLogger("jobgraph.api")

_MAX_PDF_BYTES = 10 * 1024 * 1024  # 10 MB
# 업로드 파일 크기 상한. 10 * 1024 * 1024 바이트 = 10 메가바이트를 이렇게 계산식으로 써둔 것 —
# "10485760"이라고 그냥 숫자로 쓰는 것보다 "10MB다"라는 의도가 코드만 봐도 바로 보임

_PDF_PARSE_TIMEOUT_SEC = 30
# 크기 제한을 통과했더라도 파싱에 지나치게 오래 걸리는 PDF(압축 폭탄 등)가 스레드를
# 무한 점유하는 것을 막는다 — 크기만으로는 CPU 소진을 막을 수 없다.

# 데모 비용 보호 — 방문자별(IP) 하루 분석 횟수 상한(메모리, 날짜 바뀌면 리셋). 기본 3회.
# DEMO_DAILY_LIMIT=0이면 무제한. 관리자(ACCESS_KEY 일치)는 이 상한을 타지 않음.
#
# 전역 카운터가 아니라 IP별로 세는 이유: 전역이면 방문자 한 명이 아침에 소진하는 순간
# 그날 하루 데모가 죽는다(채용담당자 포함). IP별이면 각자 몫이 보장된다.
_demo_usage: dict[str, dict] = {}   # {ip: {"date": "2026-07-12", "count": 2}}
_demo_usage_lock = threading.Lock()
# analyze_portfolio가 def(동기 함수)라 FastAPI가 여러 스레드에서 동시에 실행할 수 있음 —
# "확인 후 증가"를 이 락으로 감싸지 않으면, 두 요청이 거의 동시에 들어왔을 때 둘 다 상한 확인을
# 통과해버리는 경쟁 조건(race condition)이 생김. 락으로 "한 번에 한 스레드만" 이 블록을 실행하게 강제.

_MAX_TRACKED_IPS = 10_000
# IP 딕셔너리가 무한정 커지는 것(메모리 고갈 유발) 방지 — 넘치면 날짜 지난 항목부터 정리한다.

_ANALYSIS_TIMEOUT_SEC = 600   # 10분
# 이보다 오래 "processing"에 머물러 있으면 백그라운드 작업이 유실된 것으로 보고 error로 강등한다
# (BackgroundTasks는 프로세스가 재시작되면 함께 사라지는데, 그 흔적이 상태에 남지 않기 때문).
_DEFAULT_REPORT_TTL_SEC = 24 * 60 * 60
# 완료/실패 리포트 보관 시간. 인증 없는 링크 기반 조회라 데모 서버에서는 오래 들고 있지 않는다.

_URL_RE = re.compile(r"https?://[^\s)\]]+")


def _report_ttl_sec() -> int:
    try:
        return int(os.getenv("REPORT_TTL_SEC", str(_DEFAULT_REPORT_TTL_SEC)) or _DEFAULT_REPORT_TTL_SEC)
    except ValueError:
        return _DEFAULT_REPORT_TTL_SEC


def _client_ip(request: Request) -> str:
    """클라이언트 IP — HF Spaces 등 리버스 프록시 뒤에서는 x-forwarded-for를 본다.

    주의: x-forwarded-for는 클라이언트가 위조할 수 있다. 여기서는 과금 보호(비용 상한)
    용도라 위조 시 상한 우회가 가능하지만, 인증·권한 판단에는 절대 쓰지 않는다.
    엄밀한 방어가 필요하면 신뢰 가능한 프록시 IP 화이트리스트가 필요하다.
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()   # 첫 항목이 최초 클라이언트
    return request.client.host if request.client else "unknown"


def _is_public_deploy() -> bool:
    """공개 배포 환경인지 — HF Spaces는 SPACE_ID를 자동 주입한다."""
    return bool(os.getenv("SPACE_ID") or os.getenv("ENV") == "production")


def _is_admin(key: str) -> bool:
    """관리자 여부 — ACCESS_KEY가 일치하면 일일 상한 면제.

    ACCESS_KEY 미설정 시:
      - 로컬 개발: 관리자로 취급(편의)
      - 공개 배포: 관리자 아님(fail-closed)
    시크릿 설정을 깜빡한 채 배포하면 방문자 전원이 관리자가 되어 상한이 무력화되고
    OpenAI 과금이 무제한 열린다. 보안 기본값은 fail-open이 아니라 fail-closed여야 한다.
    """
    expected = os.getenv("ACCESS_KEY")
    if not expected:
        if _is_public_deploy():
            logger.warning("ACCESS_KEY 미설정 상태로 공개 배포됨 — 관리자 없이 일일 상한만 적용")
            return False
        return True   # 로컬 개발 편의
    # 타이밍 세이프 비교 — 문자열 == 는 조기 종료로 키 길이·prefix가 새어나갈 수 있음
    return secrets.compare_digest(key or "", expected)
    # 왜 그냥 "key == expected"라고 안 쓰고 secrets.compare_digest()를 쓰는가:
    # 파이썬의 == 비교는 문자열 앞부분부터 비교하다가 다른 글자가 나오면 그 즉시 멈추고 False를 반환함.
    # 이 미세한 "얼마나 빨리 False가 나오는지" 시간 차이를 계속 관찰하면, 공격자가 "정답 키의 앞 글자가
    # 뭔지" 한 글자씩 추측해낼 수 있음(이걸 "타이밍 공격"이라 부름). compare_digest()는 항상 똑같은
    # 시간이 걸리게 비교해서 이 정보 유출을 막아줌 — 보안 관련 값을 비교할 땐 항상 이런 함수를 써야 함.


def _enforce_daily_limit(ip: str) -> None:
    """이 IP의 오늘 분석 횟수가 상한을 넘으면 429를 던지고, 아니면 카운트를 1 올린다."""
    limit = int(os.getenv("DEMO_DAILY_LIMIT", "3") or "3")
    if limit <= 0:
        return
        # 0 이하로 설정하면 "무제한"으로 취급 — 관리자가 필요하면 환경변수로 이 제한 자체를 끌 수 있음
    # 확인(현재 count가 상한 미만인가)과 증가(count += 1) 사이에 다른 스레드가 끼어들면
    # 둘 다 통과해버리는 경쟁 조건이 생기므로, 이 블록 전체를 락으로 묶어 한 번에 한 스레드만 실행하게 함
    with _demo_usage_lock:
        today = datetime.now(timezone.utc).date().isoformat()

        if len(_demo_usage) >= _MAX_TRACKED_IPS:
            # 날짜가 지난 항목을 청소 — 그래도 안 줄면(전부 오늘자) 전체를 비운다.
            # 상한 초기화가 되긴 하지만, 메모리 고갈로 서버가 죽는 것보다는 낫다.
            stale = [k for k, v in _demo_usage.items() if v["date"] != today]
            for k in stale:
                del _demo_usage[k]
            if len(_demo_usage) >= _MAX_TRACKED_IPS:
                logger.warning("데모 IP 추적 한도 초과 — 카운터 전체 리셋")
                _demo_usage.clear()

        entry = _demo_usage.get(ip)
        if entry is None or entry["date"] != today:
            entry = {"date": today, "count": 0}
            _demo_usage[ip] = entry
            # 날짜가 바뀌었으면(어제 카운트를 오늘까지 들고 있으면 안 되니까) 카운터를 0으로 리셋

        if entry["count"] >= limit:
            raise HTTPException(
                429,
                f"오늘 데모 분석 한도({limit}회)가 모두 사용되었습니다. "
                "공개 데모 비용 보호를 위한 제한이며, 내일 다시 시도해 주세요.",
            )
            # 429 = "Too Many Requests"라는 표준 HTTP 상태코드 — "너무 많이 요청했다"는 뜻
        entry["count"] += 1


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _is_report_expired(report: ReportResponse, now: datetime | None = None) -> bool:
    """완료/실패 리포트 TTL 만료 여부. processing은 별도 timeout 로직에서 처리한다."""
    if report.status == "processing":
        return False
    ttl = _report_ttl_sec()
    if ttl <= 0:
        return False
    stamped = _parse_iso(report.generated_at) or _parse_iso(report.started_at)
    if stamped is None:
        return False
    return ((now or datetime.now(timezone.utc)) - stamped).total_seconds() > ttl


def _purge_report(report_id: str, reports: dict, uploads: dict | None = None) -> None:
    """리포트와 같은 report_id의 이력서 텍스트를 메모리에서 제거한다."""
    reports.pop(report_id, None)
    if uploads is not None:
        uploads.pop(report_id, None)


def _delete_portfolio_upload(portfolio_report_id: str, uploads: dict) -> bool:
    """포트폴리오 업로드 항목과 실제 임시 PDF 파일을 삭제한다."""
    key = f"pf:{portfolio_report_id}"
    path = uploads.pop(key, None)
    if not path:
        return False
    tmp_dir = os.path.realpath(tempfile.gettempdir())
    real_path = os.path.realpath(path)
    if not real_path.startswith(tmp_dir + os.sep):
        logger.warning("임시 디렉터리 밖 포트폴리오 경로는 삭제하지 않음: %s", path)
        return True
    try:
        os.unlink(real_path)
    except FileNotFoundError:
        pass
    except OSError:
        logger.warning("포트폴리오 임시 파일 삭제 실패: %s", path, exc_info=True)
    return True


def _store_report_if_active(report_id: str, reports: dict, report: ReportResponse) -> None:
    """사용자가 삭제했거나 저장소에서 축출된 report_id에는 늦은 결과를 다시 쓰지 않는다."""
    if report_id not in reports:
        logger.info("이미 삭제되었거나 축출된 리포트 결과 저장 생략 (report_id=%s)", report_id)
        return
    reports[report_id] = report


def _normalize_url_inputs(values: list[str], allowed_host: str | None = None, limit: int = 5) -> list[str]:
    """입력칸 하나에 여러 URL/Markdown 링크가 붙어도 실제 URL 목록만 뽑는다."""
    out: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        raw = str(value or "").strip().replace("\\_", "_")
        candidates = _URL_RE.findall(raw) or ([raw] if raw else [])
        for url in candidates:
            cleaned = url.rstrip(".,;")
            if allowed_host and allowed_host not in cleaned:
                continue
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                out.append(cleaned)
            if len(out) >= limit:
                return out
    return out
_NODE_PHASE = {
    "resume_eval": "소스 평가 중", "github_eval": "소스 평가 중",
    "portfolio_eval": "소스 평가 중", "deploy_eval": "소스 평가 중",
    "consensus": "교차검증 합의 중",
    "seed_gap": "적합도 분석 중", "call_model": "적합도 분석 중", "tools": "적합도 분석 중",
    "synthesizer": "리포트 생성 중", "critic": "검증 중",
    "coach_call_model": "코칭 생성 중", "coach_tools": "코칭 생성 중",
    "finalize_coach": "코칭 생성 중",
}
# supervisor.py 그래프의 노드 이름(영어)을, 사용자에게 보여줄 한국어 진행 문구로 바꿔주는 표.
# "지금 어느 노드가 실행 중인지"를 그대로 보여주면 사용자는 무슨 뜻인지 모르니, 사람이 이해할 수 있는
# 4단계 정도로 뭉뚱그려서 보여줌 (예: consensus·seed_gap·gap_agent 여러 노드가 다 "적합도 분석 중"으로 통일)


async def _read_pdf_upload(file: UploadFile) -> bytes:
    """PDF 업로드를 청크 단위로 읽으며 크기·타입을 검증한 뒤 바이트를 반환한다.

    - 상한(_MAX_PDF_BYTES)을 넘으면 전부 읽기 전에 즉시 413 (거대 업로드가 RAM을 다 먹는 것 방지)
    - 확장자 + magic bytes(%PDF) 이중 확인 (확장자만으론 위조 가능)
    """
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(415, "PDF 파일만 업로드 가능합니다.")
        # 415 = "Unsupported Media Type" — 파일 형식이 안 맞다는 표준 상태코드
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)   # 1MB씩
        # 파일 전체를 한 번에 다 읽지 않고 1MB씩 "조금씩" 읽음. 왜 이렇게 하는가:
        # 만약 누군가 100GB짜리 가짜 PDF를 업로드하면, 한 번에 다 읽으려다 서버 메모리가 꽉 차서
        # 서버 전체가 죽을 수 있음. 조금씩 읽으면서 "상한 넘으면 그 즉시 중단"할 수 있어서 더 안전함.
        if not chunk:
            break
            # read()가 빈 바이트를 돌려주면 "파일 끝까지 다 읽었다"는 뜻
        total += len(chunk)
        if total > _MAX_PDF_BYTES:
            raise HTTPException(413, "파일 크기는 10MB 이하여야 합니다.")
            # 413 = "Payload Too Large" — 다 읽기 전에 이미 상한을 넘었으면 바로 멈추고 에러
        chunks.append(chunk)
    content = b"".join(chunks)
    # 조금씩 모아둔 조각들을 다시 하나로 합침 (b"".join → 문자열의 "".join()과 같은 방식, 바이트 버전)
    if content[:4] != b"%PDF":
        raise HTTPException(415, "유효한 PDF 파일이 아닙니다.")
        # "magic bytes" 검사 — 진짜 PDF 파일은 항상 맨 앞 4바이트가 "%PDF"로 시작함.
        # 파일 확장자(.pdf)는 이름만 바꾸면 누구나 위조할 수 있어서, 파일 내용 자체를 한 번 더 확인하는 것.
        # 확장자 검사(위)와 이 검사(magic bytes) 둘 다 통과해야 진짜 PDF로 인정하는 이중 확인.
    return content


@router.post("/upload", response_model=UploadResponse)
async def upload_resume(
    file: UploadFile = File(...),
    uploads: dict = Depends(get_uploads),
) -> UploadResponse:
    """PDF 이력서 업로드. 텍스트 추출 후 report_id 반환."""
    # file: UploadFile = File(...) → "업로드된 파일을 받겠다"는 FastAPI 문법. File(...)의 "..."은
    # "이 파라미터는 필수다"라는 뜻 (기본값이 없다는 표시).
    content = await _read_pdf_upload(file)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name
        # 업로드된 내용을 서버 디스크의 임시 파일로 잠깐 저장 — pdfplumber가 "파일 경로"를 받아서
        # 여는 라이브러리라서, 메모리에 있는 바이트만으로는 안 되고 실제 파일로 만들어줘야 함.
        # delete=False → with문이 끝나도 자동으로 안 지워짐 (아래서 우리가 직접 지울 것이기 때문)
    try:
        # pdfplumber는 CPU 바운드 블로킹 — 스레드풀로 오프로드해 이벤트 루프 보호
        # 타임아웃: 크기(10MB)는 통과하지만 파싱에 지나치게 오래 걸리는 PDF(압축 폭탄 등)가
        # 스레드를 무한 점유하는 것을 막는다. 크기 제한만으로는 CPU 소진을 못 막는다.
        text, page_count = await asyncio.wait_for(
            run_in_threadpool(extract_pdf_info, tmp_path), timeout=_PDF_PARSE_TIMEOUT_SEC
        )
        # run_in_threadpool(함수, 인자) → "이 함수(extract_pdf_info)를 별도 작업자에게 맡겨서 실행하고,
        # 끝나면 결과를 알려줘"라는 뜻. pdf_parser.py의 extract_pdf_info는 시간이 좀 걸리는 작업이라,
        # 이걸 그냥 직접 호출하면(await 없이) 그 시간 동안 서버가 다른 요청을 하나도 못 받게 됨.
    except asyncio.TimeoutError:
        raise HTTPException(422, "PDF 처리 시간이 초과되었습니다. 더 단순한 파일로 시도해 주세요.")
    except ValueError:
        raise HTTPException(422, "PDF를 처리할 수 없습니다. 파일이 손상되었거나 암호화되었을 수 있습니다.")
        # pdf_parser.py의 extract_pdf_info가 파싱 실패 시 ValueError를 던지던 게 여기서 잡혀서
        # 422("Unprocessable Entity" — 요청은 이해했지만 처리할 수 없다는 뜻)로 바뀜
    finally:
        os.unlink(tmp_path)
        # 성공하든 실패하든 임시 파일은 반드시 지움 — 안 지우면 서버 디스크가 계속 쌓여서 꽉 참

    # 병렬 평가자 4개가 동시에 이 텍스트를 LLM에 넘기므로 TPM 초과 방지
    _MAX_RESUME_CHARS = 12_000
    # TPM = "Tokens Per Minute" — OpenAI가 1분에 처리할 수 있는 토큰 수 제한. 이력서가 너무 길면
    # 4개 평가자가 동시에 이 긴 텍스트를 LLM에 보내다가 이 제한에 걸릴 수 있어서, 미리 앞부분만 자름.
    report_id = str(uuid.uuid4())
    # uuid.uuid4() → 전 세계에서 겹칠 확률이 거의 0인 무작위 고유 ID를 만들어줌.
    # 이 ID로 나중에 "이 사람의 분석 결과"를 찾아올 수 있게 함 (사용자 로그인 없이도 구분 가능)
    uploads[report_id] = text[:_MAX_RESUME_CHARS]
    # deps.py에서 본 BoundedDict(uploads)에 {report_id: 이력서텍스트} 형태로 저장
    name_hint = (text.split("\n")[0].strip()[:60]) if text else "Unknown"
    # 이력서 텍스트의 첫 줄을 "이름일 것 같은 힌트"로 대충 추측 — 정확한 파싱이 아니라 참고용
    return UploadResponse(
        report_id=report_id, candidate_name_hint=name_hint,
        page_count=page_count, text_length=len(text), status="uploaded",
    )


@router.post("/upload-portfolio", response_model=PortfolioUploadResponse)
async def upload_portfolio(
    file: UploadFile = File(...),
    uploads: dict = Depends(get_uploads),
) -> PortfolioUploadResponse:
    """포트폴리오 PDF 업로드. 경로를 임시 저장 후 portfolio_report_id 반환."""
    # 이력서 업로드(/upload)와 비슷한데 중요한 차이가 하나 있음 — 아래 주석 참고
    content = await _read_pdf_upload(file)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    def _page_count(path: str) -> int:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            return len(pdf.pages)
        # 여기선 페이지 수만 필요하고 텍스트는 지금 당장 뽑지 않음 — 왜냐하면 portfolio_eval.py(Layer 3)가
        # 나중에 스스로 이 PDF를 다시 열어서 "텍스트 페이지 vs 이미지 페이지"를 구분해가며 처리하기 때문.
        # 그래서 이력서(/upload)는 텍스트를 바로 뽑아 저장하지만, 포트폴리오는 "파일 경로"만 저장해둠.

    try:
        # 블로킹 PDF 파싱을 스레드풀로 오프로드 (타임아웃으로 CPU 소진 방어 — 위 /upload와 동일)
        page_count = await asyncio.wait_for(
            run_in_threadpool(_page_count, tmp_path), timeout=_PDF_PARSE_TIMEOUT_SEC
        )
    except asyncio.TimeoutError:
        os.unlink(tmp_path)
        raise HTTPException(422, "PDF 처리 시간이 초과되었습니다. 더 단순한 파일로 시도해 주세요.")
    except Exception:
        os.unlink(tmp_path)
        raise HTTPException(422, "PDF를 열 수 없습니다.")
    portfolio_id = str(uuid.uuid4())
    uploads[f"pf:{portfolio_id}"] = tmp_path   # 파일 경로 저장 (텍스트가 아님)
    # 키 앞에 "pf:"를 붙이는 이유 — 같은 uploads 딕셔너리 안에 이력서(report_id)와 포트폴리오(portfolio_id)가
    # 같이 저장되는데, 우연히 두 uuid가 같은 값처럼 헷갈리지 않도록 종류를 구분하는 접두어를 붙인 것
    return PortfolioUploadResponse(
        portfolio_report_id=portfolio_id, page_count=page_count, status="uploaded",
    )


# 동기 neo4j.list_job_families()를 호출하므로 def — 스레드풀 실행으로 이벤트 루프 보호.
# BackgroundTasks는 def 핸들러에서도 정상 동작한다.
@router.post("/analyze", response_model=AnalyzeAccepted)
def analyze_portfolio(
    req: AnalyzeRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    uploads: dict = Depends(get_uploads),
    reports: dict = Depends(get_reports),
    neo4j: Neo4jClient = Depends(get_neo4j),
    graph=Depends(get_graph),
) -> AnalyzeAccepted:
    """v3 다중소스 분석 시작. 즉시 반환 후 백그라운드 처리."""
    # 이 함수가 이 파일의 핵심 — "분석을 시작해줘"라는 요청을 받는 곳.
    # 중요한 점: 이 함수는 분석이 다 끝날 때까지 기다리지 않고, "접수했다"고 바로 응답을 돌려줌.
    if req.report_id not in uploads:
        raise HTTPException(404, "report_id를 찾을 수 없습니다. 먼저 /portfolio/upload를 호출하세요.")
        # 이력서를 먼저 /upload로 올려야만 그 report_id로 분석을 시작할 수 있음 — 순서를 강제하는 방어
    if graph is None:
        raise HTTPException(503, "분석 비활성화 — OPENAI_API_KEY가 필요합니다.")
        # main.py의 lifespan()에서 openai 키가 없으면 graph를 아예 None으로 뒀던 게 여기서 확인됨
    valid = neo4j.list_job_families()
    if valid and req.job_family not in valid:
        raise HTTPException(422, f"유효하지 않은 직군 '{req.job_family}'. 가능: {', '.join(valid)}")
        # supervisor.py의 run_supervisor()에도 같은 검증이 있었는데, 여기서도 한 번 더 확인 —
        # API 단에서 미리 걸러내면 백그라운드 작업까지 안 가고 사용자에게 더 빨리 알려줄 수 있음

    existing = reports.get(req.report_id)
    if existing and getattr(existing, "status", None) == "processing":
        raise HTTPException(409, "이미 분석 중입니다.")
        # 409 = "Conflict" — 같은 report_id로 분석을 두 번 동시에 돌리는 걸 막음
        # (같은 사람이 실수로 버튼을 두 번 눌러도 이중으로 비용이 안 나가게)

    # 공개 데모 비용 보호 — 관리자(키 일치)는 무제한, 방문자는 IP별 일일 상한(기본 3회)
    if not _is_admin(req.access_key):
        _enforce_daily_limit(_client_ip(request))

    portfolio_key = f"pf:{req.portfolio_report_id}" if req.portfolio_report_id else None
    portfolio_path = uploads.get(portfolio_key) if portfolio_key else None
    if portfolio_key and (portfolio_path is None or not os.path.exists(portfolio_path)):
        # portfolio_report_id를 줬는데 uploads에 없거나(만료/미업로드) 파일이 이미 삭제된 상태(같은
        # portfolio_report_id로 분석을 이미 한 번 완료해 임시 파일이 정리된 경우) — 조용히 포트폴리오
        # 없이 진행하는 대신, 여기서 명확하게 실패시켜 "다시 업로드하라"고 안내
        raise HTTPException(404, "포트폴리오를 찾을 수 없습니다. /portfolio/upload-portfolio를 다시 호출하세요.")

    reports[req.report_id] = ReportResponse(
        report_id=req.report_id, status="processing", phase="소스 평가 중",
        owner=req.owner_name or "분석 중", job_family=req.job_family,
        started_at=datetime.now(timezone.utc).isoformat(),
        # 조회 시점에 "언제부터 처리 중인지" 알아야 유실된 작업을 감지할 수 있다 (get_report 참고)
    )
    # 아직 진짜 분석은 시작도 안 했는데, 일단 "처리 중"이라는 상태를 먼저 저장해둠 —
    # 그래야 사용자가 바로 /report/{report_id}로 조회했을 때 "몰라요"가 아니라 "처리 중"이라고 답할 수 있음
    background_tasks.add_task(
        _run_analysis,
        report_id=req.report_id, resume_text=uploads[req.report_id],
        job_family=req.job_family, owner_name=req.owner_name,
        github_urls=_normalize_url_inputs(req.github_urls, allowed_host="github.com"),
        deploy_urls=_normalize_url_inputs(req.deploy_urls),
        portfolio_path=portfolio_path, portfolio_key=portfolio_key, uploads=uploads,
        graph=graph, neo4j=neo4j, reports=reports,
    )
    # background_tasks.add_task(함수, 인자들) → "이 함수를, 지금 말고 이 API 응답을 사용자에게
    # 보낸 다음에 이어서 실행해라"는 예약. 실제로 시간이 오래 걸리는 _run_analysis()는 여기서
    # "예약"만 되고, 진짜 실행은 아래 return 문 다음에 이뤄짐.
    return AnalyzeAccepted(report_id=req.report_id, status="processing")
    # 사용자는 이 응답을 몇 초 안에 즉시 받음 — 실제 분석 결과가 아니라 "접수됐다"는 확인일 뿐


@router.get("/report/{report_id}", response_model=ReportResponse)
async def get_report(
    report_id: str,
    reports: dict = Depends(get_reports),
) -> ReportResponse:
    """분석 결과 조회. status=processing이면 재시도 권장."""
    # 프론트엔드는 /analyze로 분석을 접수한 뒤, 이 API를 몇 초 간격으로 계속 호출해서
    # "아직 처리 중인지, 다 됐는지"를 확인함 — 이런 방식을 "폴링(polling)"이라고 부름
    report = reports.get(report_id)
    if report is None:
        raise HTTPException(404, "report_id를 찾을 수 없습니다.")
    if _is_report_expired(report):
        _purge_report(report_id, reports)
        raise HTTPException(404, "리포트 보관 시간이 만료되었습니다.")

    # 유실된 작업 감지 — BackgroundTasks는 프로세스 재시작 시 함께 사라지므로,
    # 그 경우 status가 "processing"에 영원히 머물러 프론트가 무한 폴링하게 된다.
    # 조회 시점에 경과 시간을 재서 상한을 넘은 건 실패로 강등한다.
    if report.status == "processing" and report.started_at:
        try:
            started = datetime.fromisoformat(report.started_at)
            if (datetime.now(timezone.utc) - started).total_seconds() > _ANALYSIS_TIMEOUT_SEC:
                logger.warning("분석 유실 감지 (report_id=%s) — error로 강등", report_id)
                report.status = "error"
                report.error_detail = "분석이 시간 내에 완료되지 않았습니다. 다시 시도해 주세요."
        except ValueError:
            pass   # started_at 형식이 깨져도 조회 자체가 실패하면 안 됨

    return report
    # status가 "processing"이면 프론트가 알아서 조금 뒤 다시 물어보고,
    # "done"이나 "error"면 그 결과를 화면에 보여줌 (이 판단은 프론트엔드 쪽 로직)


@router.delete("/report/{report_id}")
async def delete_report(
    report_id: str,
    reports: dict = Depends(get_reports),
    uploads: dict = Depends(get_uploads),
) -> dict:
    """분석 리포트와 업로드 이력서 텍스트를 메모리에서 삭제한다."""
    existed = report_id in reports or report_id in uploads
    _purge_report(report_id, reports, uploads)
    if not existed:
        raise HTTPException(404, "report_id를 찾을 수 없습니다.")
    return {"report_id": report_id, "status": "deleted"}


@router.delete("/upload-portfolio/{portfolio_report_id}")
async def delete_portfolio_upload(
    portfolio_report_id: str,
    uploads: dict = Depends(get_uploads),
) -> dict:
    """분석 전에 업로드된 포트폴리오 PDF 임시 파일을 삭제한다."""
    if not _delete_portfolio_upload(portfolio_report_id, uploads):
        raise HTTPException(404, "portfolio_report_id를 찾을 수 없습니다.")
    return {"portfolio_report_id": portfolio_report_id, "status": "deleted"}


# ── 매핑 (순수) ────────────────────────────────────────────────
def _map_final_report(report_id: str, owner: str, job_family: str, final: dict) -> ReportResponse:
    """run_supervisor의 final_report를 v3 ReportResponse로 매핑한다."""
    # "매핑(mapping)"이란: A 모양의 데이터를 B 모양의 데이터로 옮겨 담는 것.
    # supervisor.py가 만든 final_report(자유로운 dict)를, API가 약속한 정확한 모양(ReportResponse)으로 바꿈.
    # "(순수)"라는 표시는 이 함수가 DB나 네트워크를 안 건드리고 "입력 → 출력"만 하는 함수라는 뜻 —
    # 그래서 테스트하기 쉽고 부작용이 없음.
    gap = final.get("gap") or {}
    ver = final.get("verification") or {}
    coaching = final.get("coaching") if isinstance(final.get("coaching"), dict) else {}

    def _txt(value: object) -> str:
        return str(value or "").strip()

    def _txt_list(value: object, limit: int = 5) -> list[str]:
        if not isinstance(value, list):
            return []
        return [_txt(v) for v in value if _txt(v)][:limit]

    project_suggestions = [
        ProjectSuggestion(repo=_txt(s.get("repo")),
                          add_skill=_txt(s.get("add_skill") or s.get("skill")),
                          why=_txt(s.get("why")), how=_txt(s.get("how")))
        for s in (coaching.get("project_suggestions") or [])
        if isinstance(s, dict) and (s.get("add_skill") or s.get("skill"))
        # coaching_agent가 만든 dict 리스트를, schemas.py의 ProjectSuggestion 모델 리스트로 변환.
        # add_skill이나 skill 둘 중 하나라도 있어야 통과 — 둘 다 없으면 의미 없는 항목이라 걸러냄
    ]
    learning_recommendations = [
        LearningRecommendation(skill=_txt(s.get("skill")), reason=_txt(s.get("reason")), how=_txt(s.get("how")))
        for s in (coaching.get("learning_recommendations") or [])
        if isinstance(s, dict) and s.get("skill")
    ]
    # LLM이 낸 type이 strength/gap 밖 값이면 Pydantic ValidationError로 리포트 전체가
    # error로 전락 → 유효 Literal로 정규화(모르면 strength)해 한 항목 때문에 리포트가 죽지 않게
    def _coach_type(v: object) -> str:
        return v if v in ("strength", "gap") else "strength"
        # InterviewCoaching 모델의 type 필드는 "strength" 아니면 "gap"만 되게 정해뒀을 텐데,
        # LLM이 가끔 그 외의 값(오타나 다른 표현)을 낼 수 있음. 그럴 때 에러를 내는 대신
        # 그냥 "strength"로 안전하게 바꿔치기해서, 항목 하나 때문에 리포트 전체가 못 만들어지는 걸 방지

    interview_coaching = [
        InterviewCoaching(type=_coach_type(s.get("type")), title=s.get("title", ""),
                          coaching=s.get("coaching", ""))
        for s in (coaching.get("interview_coaching") or [])
        if isinstance(s, dict) and s.get("title") and s.get("coaching")
    ]
    understanding_raw = coaching.get("project_understanding")
    project_understanding = (
        ProjectUnderstanding(
            one_liner=_txt(understanding_raw.get("one_liner")),
            architecture=_txt(understanding_raw.get("architecture")),
            data_flow=_txt(understanding_raw.get("data_flow")),
            core_design_choices=_txt_list(understanding_raw.get("core_design_choices")),
        )
        if isinstance(understanding_raw, dict) and any(understanding_raw.values())
        else None
    )
    evidence_cards = [
        EvidenceCard(skill=_txt(s.get("skill")), evidence=_txt(s.get("evidence")),
                     what_it_shows=_txt(s.get("what_it_shows")),
                     interview_angle=_txt(s.get("interview_angle")))
        for s in (coaching.get("evidence_cards") or [])
        if isinstance(s, dict) and s.get("skill")
    ]
    project_roadmap = [
        RoadmapStep(step=_txt(s.get("step")), why=_txt(s.get("why")), how=_txt(s.get("how")))
        for s in (coaching.get("project_roadmap") or [])
        if isinstance(s, dict) and (s.get("step") or s.get("how"))
    ]
    portfolio_sentences = _txt_list(coaching.get("portfolio_sentences"))
    project_briefs = [
        ProjectBrief(
            repo=_txt(s.get("repo")),
            readme_summary=_txt(s.get("readme_summary")),
            architecture=_txt(s.get("architecture")),
            code_structure=_txt(s.get("code_structure")),
            confirmed_stack=_txt_list(s.get("confirmed_stack"), limit=12),
            key_files=_txt_list(s.get("key_files"), limit=10),
            coaching_angles=_txt_list(s.get("coaching_angles"), limit=8),
        )
        for s in (coaching.get("project_briefs") or [])
        if isinstance(s, dict) and s.get("repo")
    ]
    return ReportResponse(
        report_id=report_id, status="done", owner=owner, job_family=job_family,
        match_rate=gap.get("match_rate") or 0.0,
        confidence_level=gap.get("confidence_level"),
        advice=gap.get("advice"),
        verification_counts=ver.get("counts") or {},
        verified_skills=[VerificationItem(**s) for s in (ver.get("skills") or [])
                         if isinstance(s, dict) and s.get("skill")],
        coaching_summary=coaching.get("summary"),
        project_suggestions=project_suggestions,
        learning_recommendations=learning_recommendations,
        interview_coaching=interview_coaching,
        project_understanding=project_understanding,
        evidence_cards=evidence_cards,
        project_roadmap=project_roadmap,
        portfolio_sentences=portfolio_sentences,
        project_briefs=project_briefs,
        generated_at=datetime.now(timezone.utc).isoformat(),
        trace=final.get("trace"),
        capability_fit=final.get("capability_fit"),
        common_skill_fit=final.get("common_skill_fit"),
        recommended_families=final.get("recommended_families") or [],
        recommended_postings=[
            RecommendedPosting(title=p.get("title", ""), company=p.get("company", ""),
                               url=p.get("url", ""), job_family=p.get("job_family", ""),
                               match_pct=p.get("match_pct") or 0.0)
            for p in (final.get("recommended_postings") or []) if isinstance(p, dict)
        ],
    )
    # 이 함수가 반환하는 ReportResponse 하나가, 지금까지 우리가 본 Layer 1~5의 모든 결과물
    # (gap 분석, 신뢰도 검증, 코칭, capability_fit, 연봉과 무관하지만 추천 공고 등)이
    # 전부 하나로 합쳐지는 최종 지점입니다.


# ── 백그라운드 태스크 ──────────────────────────────────────────
def _run_analysis(
    report_id: str, resume_text: str, job_family: str, owner_name: str | None,
    github_urls: list[str], deploy_urls: list[str],
    graph, neo4j: Neo4jClient, reports: dict,
    portfolio_path: str | None = None,
    portfolio_key: str | None = None, uploads: dict | None = None,
    # portfolio_key/uploads — 분석이 끝나면 임시 파일뿐 아니라 uploads 딕셔너리의 해당 항목도
    # 같이 지우기 위해 추가된 매개변수 (finally 블록에서 사용, analyze_portfolio()가 넘겨줌)
) -> None:
    """업로드 이력서 + GitHub + 배포 URL + 포트폴리오 PDF → v3 그래프 → 2축·검증 리포트."""
    # 이 함수가 background_tasks.add_task()로 예약해뒀던 그 실제 작업 —
    # /analyze API 응답이 나간 "뒤에" 서버 안에서 조용히 실행됨 (사용자는 이 실행을 기다리지 않음)
    owner = owner_name or "지원자"

    def _progress(node: str) -> None:
        phase = _NODE_PHASE.get(node)
        if phase and report_id in reports:
            reports[report_id].phase = phase
        # supervisor.py의 run_supervisor(progress_cb=...)에 이 함수를 넘겨서, 그래프가 노드 하나
        # 끝낼 때마다 이게 호출됨. reports[report_id].phase를 그때그때 갱신해두면, 사용자가
        # /report/{report_id}로 폴링할 때 "지금 몇 단계 진행 중인지"를 실시간으로 보여줄 수 있음.

    try:
        out = run_supervisor(
            graph, job_family=job_family, owner=owner,
            resume_text=resume_text, github_urls=github_urls, deploy_urls=deploy_urls,
            portfolio_path=portfolio_path,
            neo4j=neo4j, progress_cb=_progress,
        )
        # supervisor.py에서 본 그 함수 — 여기서 실제로 Layer 3 전체 그래프가 실행됨
        if out.get("error"):
            _store_report_if_active(
                report_id,
                reports,
                ReportResponse(
                    report_id=report_id, status="error", owner=owner, job_family=job_family,
                    error_detail=out.get("message") or out.get("error"),
                    generated_at=datetime.now(timezone.utc).isoformat(),
                ),
            )
            return
            # run_supervisor()가 "no_input"이나 "invalid_job_family" 같은 안내를 반환했으면
            # (그래프를 아예 안 돌린 경우) 그걸 그대로 에러 리포트로 저장하고 끝
        _store_report_if_active(report_id, reports, _map_final_report(report_id, owner, job_family, out))
        # 성공하면 위에서 본 매핑 함수로 최종 결과를 예쁘게 정리해서 저장
    except Exception:
        logger.exception("분석 실패 (report_id=%s, job_family=%s)", report_id, job_family)
        _store_report_if_active(
            report_id,
            reports,
            ReportResponse(
                report_id=report_id, status="error", owner=owner, job_family=job_family,
                error_detail="분석 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.",
                generated_at=datetime.now(timezone.utc).isoformat(),
            ),
        )
        # 예상 못 한 에러가 나도(코드 버그, 네트워크 문제 등), 서버가 죽지 않고
        # "이 report_id는 실패했다"는 결과를 정상적으로 저장해서 사용자가 조회했을 때 알 수 있게 함
    finally:
        # 업로드된 포트폴리오 임시 PDF 정리 (분석 성공·실패 무관)
        if portfolio_path and os.path.exists(portfolio_path):
            try:
                os.unlink(portfolio_path)
            except OSError:
                pass
                # 파일 삭제가 실패해도(이미 지워졌거나 권한 문제) 이 단계에서 프로그램이 죽으면 안 되니
                # 조용히 넘어감 — 임시 파일 청소는 "되면 좋고 안 되도 치명적이지 않은" 부가 작업이라서
        if portfolio_key and uploads is not None:
            uploads.pop(portfolio_key, None)
            # 파일은 지워졌는데 uploads엔 그 경로가 계속 남아있으면, 같은 portfolio_report_id로
            # 다음에 또 분석을 요청했을 때 "존재하지 않는 경로"를 조용히 참조하게 됨 — analyze_portfolio()가
            # 그 상황을 "포트폴리오 없음"으로 명확히 감지할 수 있도록, 다 쓴 항목은 딕셔너리에서도 제거
