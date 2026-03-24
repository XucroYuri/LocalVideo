from app.stages.prompts.custom import CONTENT_CUSTOM_USER
from app.stages.prompts.dialogue_script import (
    CONTENT_CUSTOM_DIALOGUE_SCRIPT_USER,
    CONTENT_DIALOGUE_SCRIPT_USER,
)


def test_custom_prompt_requires_preserving_distinct_forms() -> None:
    assert "不同形态/阶段/身份版本" in CONTENT_CUSTOM_USER
    assert "必须保留为不同角色" in CONTENT_CUSTOM_USER
    assert "不能为了简化而合并成一个泛称角色" in CONTENT_CUSTOM_USER


def test_dialogue_script_prompt_requires_preserving_distinct_forms() -> None:
    assert "若同一主体存在不同形态/阶段/身份版本" in CONTENT_DIALOGUE_SCRIPT_USER
    assert "必须保留为不同角色" in CONTENT_DIALOGUE_SCRIPT_USER
    assert "不能擅自合并成泛称角色" in CONTENT_DIALOGUE_SCRIPT_USER
    assert "dialogue_lines 必须持续使用这些精确名称" in CONTENT_DIALOGUE_SCRIPT_USER
    assert "例如“龙形态/人形态”" not in CONTENT_DIALOGUE_SCRIPT_USER
    assert "若“已有角色参考”为空：再根据素材自主创建角色。" not in CONTENT_DIALOGUE_SCRIPT_USER


def test_custom_dialogue_script_prompt_requires_preserving_distinct_forms() -> None:
    assert "若同一主体存在不同形态/阶段/身份版本" in CONTENT_CUSTOM_DIALOGUE_SCRIPT_USER
    assert "必须保留为不同角色" in CONTENT_CUSTOM_DIALOGUE_SCRIPT_USER
    assert "不能擅自合并成泛称角色" in CONTENT_CUSTOM_DIALOGUE_SCRIPT_USER
    assert "dialogue_lines 必须持续使用这些精确名称" in CONTENT_CUSTOM_DIALOGUE_SCRIPT_USER
    assert "例如“龙形态/人形态”" not in CONTENT_CUSTOM_DIALOGUE_SCRIPT_USER
    assert (
        "若“已有角色参考”为空：再根据素材与用户需求自主创建角色。"
        not in CONTENT_CUSTOM_DIALOGUE_SCRIPT_USER
    )
