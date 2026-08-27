from src.common.skill_groups import (
    alternative_group_id,
    alternative_skill_groups,
    collapse_alternatives,
)


def test_seeded_alternative_groups_include_frontend_and_cloud():
    groups = [set(g) for g in alternative_skill_groups()]
    assert {"React", "Vue.js", "Angular"} in groups
    assert {"AWS", "Azure", "GCP"} in groups
    assert {"Tableau", "Power BI", "Looker"} in groups
    assert {"PyTorch", "TensorFlow"} in groups
    assert {"Pandas", "Polars"} in groups
    assert {"Jest", "Vitest"} in groups
    assert {"Playwright", "Cypress"} in groups


def test_alternative_group_id_normalizes_aliases():
    assert alternative_group_id("react.js") == alternative_group_id("Vue")
    assert alternative_group_id("amazon web services") == alternative_group_id("GCP")
    assert alternative_group_id("powerbi") == alternative_group_id("Looker")
    assert alternative_group_id("torch") == alternative_group_id("tf")


def test_collapse_alternatives_prefers_owned_skill():
    collapsed = collapse_alternatives(["React", "Vue.js", "HTML"], owned_skills=["Vue"])
    assert collapsed == ["Vue.js", "HTML"]


def test_collapse_alternatives_keeps_one_bi_requirement():
    collapsed = collapse_alternatives(["Tableau", "Power BI", "SQL"], owned_skills=["powerbi"])
    assert collapsed == ["Power BI", "SQL"]


def test_collapse_alternatives_keeps_first_when_none_owned():
    collapsed = collapse_alternatives(["PyTorch", "TensorFlow", "Docker"], owned_skills=[])
    assert collapsed == ["PyTorch", "Docker"]
