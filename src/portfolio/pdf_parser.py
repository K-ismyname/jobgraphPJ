# PDF 이력서에서 텍스트를 추출하는 파서
#
# 한 줄 요약: PDF 파일을 열어서 안에 있는 글자를 전부 뽑아내는 파일.
# resume_eval.py가 pdf_path(이력서 PDF 경로)를 받았을 때 이 파일의 extract_pdf_text()를 불러 씀.

import pdfplumber
# CLAUDE.md에서 "레이아웃 보존, 표 추출 안정적"이라 확정 스택으로 정해둔 PDF 라이브러리.


def extract_pdf_info(pdf_path: str) -> tuple[str, int]:
    """텍스트와 페이지 수를 함께 반환."""
    text_blocks: list[str] = []   # 페이지마다 뽑은 텍스트를 담을 리스트
    page_count = 0
    try:
        with pdfplumber.open(pdf_path) as pdf:
            # PDF 파일을 염. with문이라 함수가 끝나면 자동으로 파일이 닫힘.
            page_count = len(pdf.pages)
            # pdf.pages는 이 PDF의 모든 페이지를 담은 리스트 — 개수를 세서 페이지 수를 구함
            for page in pdf.pages:
                # 페이지를 하나씩 순회
                text = page.extract_text(layout=True)
                # layout=True → 원본 PDF의 줄바꿈·띄어쓰기 배치를 최대한 그대로 살려서 텍스트를 뽑음.
                # 이걸 안 하면 표나 여러 단으로 나뉜 글이 뒤죽박죽 섞여 나올 수 있음.
                if text:
                    text_blocks.append(text)
                    # 페이지가 이미지만 있고 글자가 없으면 text가 None이나 빈 문자열일 수 있어서,
                    # 그런 페이지는 그냥 건너뜀 (리스트에 안 넣음)
    except Exception as e:
        raise ValueError(f"PDF 파싱 실패: {pdf_path} — {e}") from e
        # 파일이 손상됐거나 암호가 걸려있는 등 이유로 못 열면, 여기서 우리가 만든 에러 메시지로 바꿔서 다시 던짐.
        # "from e" → 원래 에러(e)를 "원인"으로 같이 남겨둠. 나중에 문제 생기면 진짜 원인(e)까지 같이 보임.
    return "\n\n".join(text_blocks), page_count
    # 페이지별 텍스트들을 빈 줄 하나씩 사이에 두고 이어붙여서 하나의 큰 문자열로 만듦.
    # 페이지 수(page_count)도 같이 반환 — 이 정보를 쓰고 싶은 곳이 있을 수 있어서


def extract_pdf_text(pdf_path: str) -> str:
    """PDF에서 텍스트 추출. 레이아웃 기반으로 섹션 구조 최대한 보존."""
    return extract_pdf_info(pdf_path)[0]
    # extract_pdf_info()가 (텍스트, 페이지수) 두 개를 주는데, 여기선 텍스트만 필요해서 [0]으로 첫 번째 것만 꺼냄.
    # resume_eval.py는 텍스트만 필요하니 이 더 간단한 함수를 씀
