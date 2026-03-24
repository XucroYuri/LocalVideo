from app.stages._visual_prompt import (
    NO_TEXT_OVERLAY_REQUIREMENT_EN,
    NO_TEXT_OVERLAY_REQUIREMENT_ZH,
    ensure_duo_podcast_speaking_requirement,
    ensure_no_text_overlay_requirement,
)


def test_ensure_no_text_overlay_requirement_appends_chinese_rule() -> None:
    prompt = "教室傍晚，男生坐在窗边课桌前。"

    result = ensure_no_text_overlay_requirement(prompt)

    assert result == f"{prompt}\n\n{NO_TEXT_OVERLAY_REQUIREMENT_ZH}"


def test_ensure_no_text_overlay_requirement_appends_english_rule() -> None:
    prompt = "A teenage boy sits by the classroom window at dusk."

    result = ensure_no_text_overlay_requirement(prompt)

    assert result == f"{prompt}\n\n{NO_TEXT_OVERLAY_REQUIREMENT_EN}"


def test_ensure_no_text_overlay_requirement_does_not_duplicate_existing_rule() -> None:
    prompt = (
        "教室傍晚，男生坐在窗边课桌前。\n\n"
        "严禁出现任何字幕、标题条、角标、UI浮层、对话框、贴纸文案或水印说明内容。"
    )

    result = ensure_no_text_overlay_requirement(prompt)

    assert result == prompt


def test_ensure_duo_podcast_speaking_requirement_appends_chinese_rule() -> None:
    prompt = "固定双人播客画面，左侧角色抬手解释观点，右侧角色认真倾听。"

    result = ensure_duo_podcast_speaking_requirement(prompt, "left")

    assert result.startswith(prompt)
    assert "整个片段里左侧角色需全程说话" in result
    assert "并保持嘴部开合与口型变化" in result
    assert "口型变化" in result
    assert "右侧角色保持安静倾听" in result


def test_ensure_duo_podcast_speaking_requirement_appends_english_rule() -> None:
    prompt = "A fixed two-host podcast frame with both speakers seated at microphones."

    result = ensure_duo_podcast_speaking_requirement(prompt, "right")

    assert result.startswith(prompt)
    assert "Throughout the entire shot, the right-side role should keep speaking" in result
    assert "maintain visible lip movement and mouth shape changes" in result


def test_ensure_duo_podcast_speaking_requirement_is_idempotent() -> None:
    prompt = (
        "固定双人播客画面。\n\n"
        "当前分镜为双人播客固定同框。"
        "整个片段里左侧角色需全程说话，并保持嘴部开合与口型变化。"
        "右侧角色保持安静倾听，仅允许自然的微表情、轻微点头或目光反馈，"
        "禁止出现说话口型、明显插话感等任意发声动作。"
    )

    result = ensure_duo_podcast_speaking_requirement(prompt, "left")

    assert result == prompt
