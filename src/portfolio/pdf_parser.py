# PDF 이력서에서 텍스트를 추출하는 파서
import pdfplumber


def extract_pdf_info(pdf_path: str) -> tuple[str, int]:
    """텍스트와 페이지 수를 함께 반환."""
    text_blocks: list[str] = []
    page_count = 0
    try:
        with pdfplumber.open(pdf_path) as pdf:
            page_count = len(pdf.pages)
            for page in pdf.pages:
                text = page.extract_text(layout=True)
                if text:
                    text_blocks.append(text)
    except Exception as e:
        raise ValueError(f"PDF 파싱 실패: {pdf_path} — {e}") from e
    return "\n\n".join(text_blocks), page_count


def extract_pdf_text(pdf_path: str) -> str:
    """PDF에서 텍스트 추출. 레이아웃 기반으로 섹션 구조 최대한 보존."""
    text_blocks: list[str] = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text(layout=True)
                if text:
                    text_blocks.append(text)
    except Exception as e:
        raise ValueError(f"PDF 파싱 실패: {pdf_path} — {e}") from e
    return "\n\n".join(text_blocks)
