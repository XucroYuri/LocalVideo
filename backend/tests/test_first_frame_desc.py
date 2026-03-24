from app.stages.first_frame_desc import FirstFrameDescHandler


def test_parse_json_response_text_repairs_missing_comma() -> None:
    raw_text = """
这里有一些额外说明
{
  "frames": [
    {
      "shot_index": 0,
      "first_frame_prompt": "厨房中的创始人"
      "first_frame_reference_slots": []
    }
  ]
}
"""

    parsed = FirstFrameDescHandler._parse_json_response_text(raw_text)

    assert isinstance(parsed, dict)
    assert parsed["frames"][0]["shot_index"] == 0
    assert parsed["frames"][0]["first_frame_prompt"] == "厨房中的创始人"


def test_duo_template_reference_slot_ids_follow_scene_left_right_order() -> None:
    handler = FirstFrameDescHandler()

    slot_ids = handler._build_duo_podcast_template_reference_slot_ids(
        use_reference_consistency=True,
        allowed_reference_ids={"ref_03", "ref_01", "ref_02"},
        scene_role={"id": "ref_03"},
        role_1={"id": "ref_01"},
        role_2={"id": "ref_02"},
    )

    assert slot_ids == ["ref_03", "ref_01", "ref_02"]


def test_duo_template_uses_reference_markers_when_images_exist() -> None:
    handler = FirstFrameDescHandler()

    prompt = handler._build_duo_podcast_template_first_frame_description(
        reference_slot_ids=["ref_03", "ref_01", "ref_02"],
        raw_reference_by_id={
            "ref_03": {"appearance_description": "木质播客桌与暖色背景"},
            "ref_01": {"appearance_description": "黑衣侠客，眉峰高，束发"},
            "ref_02": {"appearance_description": "浅衣书生，半束长发"},
        },
        scene_role={"id": "ref_03"},
        role_1={"id": "ref_01"},
        role_2={"id": "ref_02"},
        allowed_reference_ids={"ref_03", "ref_01", "ref_02"},
    )

    assert "场景参考@图片1" in prompt
    assert "画面左侧角色参考@图片2" in prompt
    assert "画面右侧角色参考@图片3" in prompt


def test_duo_template_uses_english_template_when_target_language_is_en() -> None:
    handler = FirstFrameDescHandler()

    prompt = handler._build_duo_podcast_template_first_frame_description(
        reference_slot_ids=["ref_03", "ref_01", "ref_02"],
        raw_reference_by_id={
            "ref_03": {"appearance_description": "wood podcast desk and warm background"},
            "ref_01": {"appearance_description": "dark-robed swordsman with tied hair"},
            "ref_02": {"appearance_description": "light-robed scholar with long hair"},
        },
        scene_role={"id": "ref_03"},
        role_1={"id": "ref_01"},
        role_2={"id": "ref_02"},
        allowed_reference_ids={"ref_03", "ref_01", "ref_02"},
        target_language="en",
    )

    assert "Fixed front-facing two-host podcast frame" in prompt
    assert "scene references @image1" in prompt
    assert "The left-side host references @image2." in prompt
    assert "The right-side host references @image3." in prompt
    assert "Keep only subtle expression differences" in prompt


def test_duo_template_falls_back_to_appearance_description_without_images() -> None:
    handler = FirstFrameDescHandler()

    prompt = handler._build_duo_podcast_template_first_frame_description(
        reference_slot_ids=[],
        raw_reference_by_id={
            "ref_03": {"appearance_description": "木质播客桌与暖色背景。"},
            "ref_01": {"appearance_description": "黑衣侠客，眉峰高，束发。"},
            "ref_02": {"appearance_description": "浅衣书生，半束长发。"},
        },
        scene_role={"id": "ref_03"},
        role_1={"id": "ref_01", "seat_side": "left"},
        role_2={"id": "ref_02", "seat_side": "right"},
        allowed_reference_ids=set(),
    )

    assert "场景外观描述：木质播客桌与暖色背景" in prompt
    assert "画面左侧角色外观描述：黑衣侠客，眉峰高，束发" in prompt
    assert "画面右侧角色外观描述：浅衣书生，半束长发" in prompt
    assert "。。" not in prompt


def test_duo_template_falls_back_to_english_appearance_description_without_images() -> None:
    handler = FirstFrameDescHandler()

    prompt = handler._build_duo_podcast_template_first_frame_description(
        reference_slot_ids=[],
        raw_reference_by_id={
            "ref_03": {"appearance_description": "wood podcast desk and warm background."},
            "ref_01": {"appearance_description": "dark-robed swordsman with tied hair."},
            "ref_02": {"appearance_description": "light-robed scholar with long hair."},
        },
        scene_role={"id": "ref_03"},
        role_1={"id": "ref_01", "seat_side": "left"},
        role_2={"id": "ref_02", "seat_side": "right"},
        allowed_reference_ids=set(),
        target_language="en",
    )

    assert "scene appearance: wood podcast desk and warm background." in prompt
    assert "The left-side host appearance: dark-robed swordsman with tied hair." in prompt
    assert "The right-side host appearance: light-robed scholar with long hair." in prompt


def test_duo_template_omits_role_segment_when_image_and_description_absent() -> None:
    handler = FirstFrameDescHandler()

    prompt = handler._build_duo_podcast_template_first_frame_description(
        reference_slot_ids=[],
        raw_reference_by_id={},
        scene_role={},
        role_1={"id": "ref_01"},
        role_2={"id": "ref_02"},
        allowed_reference_ids=set(),
    )

    assert prompt == (
        "固定双人播客同框正面画面：无设定。"
        "两侧角色普通静坐并面向麦克风。"
        "仅保留轻微表情差异与极小幅度姿态变化，禁止明显手势或大幅动作。"
    )
