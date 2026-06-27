# Adzuna API에서 채용공고를 수집하는 클라이언트
import os

import httpx


def fetch_jobs(query: str, country: str = "gb", n: int = 50, pages: int = 1) -> list[dict]:
    """채용공고를 Adzuna API로 가져온다. pages만큼 페이지네이션."""
    app_id = os.getenv("ADZUNA_APP_ID")
    app_key = os.getenv("ADZUNA_APP_KEY")

    if not app_id or not app_key:
        raise EnvironmentError(
            "ADZUNA_APP_ID, ADZUNA_APP_KEY 환경변수가 필요합니다. "
            ".env 파일을 확인하세요."
        )

    results: list[dict] = []
    for page in range(1, pages + 1):
        url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"
        params = {
            "app_id": app_id,
            "app_key": app_key,
            "what": query,
            "results_per_page": n,
            "content-type": "application/json",
        }
        resp = httpx.get(url, params=params, timeout=15)
        resp.raise_for_status()
        batch = resp.json()["results"]
        results.extend(batch)
        if len(batch) < n:  # 마지막 페이지
            break
    return results


if __name__ == "__main__":
    jobs = fetch_jobs("ai engineer llm", n=3)
    for j in jobs:
        company = j.get("company", {})
        name = company.get("display_name", "?") if isinstance(company, dict) else company
        print(f"- {j['title']} @ {name}")
