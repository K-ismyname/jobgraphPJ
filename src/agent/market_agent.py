# 직무 수요·연봉·트렌드를 조사해 market_result를 채우는 Market 노드
from __future__ import annotations

from typing import TYPE_CHECKING

from src.agent.state import AppState

if TYPE_CHECKING:
    from src.storage.neo4j_client import Neo4jClient


def create_market_node(neo4j: "Neo4jClient"):
    """Market 노드 팩토리. 직무 분포·상위 요구스킬·지역 분포를 모은다."""

    def market_node(state: AppState) -> dict:
        job_family = state["job_family"]
        try:
            result = {
                "job_distribution": neo4j.get_job_distribution(),
                "top_required_skills": neo4j.get_top_skills(job_family, limit=10),
                "location_distribution": neo4j.get_location_distribution(job_family, limit=5),
            }
        except Exception as e:
            print(f"[market] 시장 인사이트 조회 실패: {e}")
            result = {"error": str(e)}
        return {"market_result": result}

    return market_node
