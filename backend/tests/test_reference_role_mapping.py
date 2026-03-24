from app.services.stage_content_mixin import StageContentMixin


def test_stabilize_role_reference_mapping_keeps_existing_reference_ids() -> None:
    references = [
        {"id": "ref_01", "name": "老张", "appearance_description": "黑色夹克"},
        {"id": "ref_02", "name": "老李", "appearance_description": "灰色西装"},
    ]
    roles = [
        {"id": "ref_01", "name": "画外音"},
        {"id": "ref_02", "name": "老张"},
        {"id": "ref_03", "name": "老李"},
    ]

    StageContentMixin._stabilize_role_reference_mapping(roles, references)

    assert roles[0]["id"] == ""
    assert roles[1]["id"] == "ref_01"
    assert roles[2]["id"] == "ref_02"


def test_stabilize_role_reference_mapping_allows_true_rename() -> None:
    references = [
        {"id": "ref_01", "name": "老张"},
    ]
    roles = [
        {"id": "ref_01", "name": "老板"},
    ]

    StageContentMixin._stabilize_role_reference_mapping(roles, references)

    assert roles[0]["id"] == "ref_01"


def test_reorder_reference_payloads_by_role_order_keeps_image_binding() -> None:
    references = [
        {"id": "ref_01", "name": "老张"},
        {"id": "ref_02", "name": "老李"},
        {"id": "ref_03", "name": "画外音"},
    ]
    reference_images = [
        {"id": "ref_01", "file_path": "/tmp/ref_01.png"},
        {"id": "ref_02", "file_path": "/tmp/ref_02.png"},
    ]
    roles = [
        {"id": "ref_03", "name": "画外音"},
        {"id": "ref_01", "name": "老张"},
        {"id": "ref_02", "name": "老李"},
    ]

    ordered_references, ordered_reference_images = (
        StageContentMixin._reorder_reference_payloads_by_role_order(
            references,
            reference_images,
            roles,
        )
    )

    assert [item["id"] for item in ordered_references] == ["ref_03", "ref_01", "ref_02"]
    assert [item["id"] for item in ordered_reference_images] == ["ref_01", "ref_02"]


def test_realign_dialogue_lines_with_roles_repairs_stale_speaker_ids() -> None:
    roles = [
        {"id": "ref_03", "name": "蓝绒小龙A"},
        {"id": "ref_04", "name": "蓝绒小龙B"},
        {"id": "ref_01", "name": "小男孩"},
        {"id": "ref_02", "name": "小女孩"},
        {"id": "ref_05", "name": "画外音"},
    ]
    dialogue_lines = [
        {"speaker_id": "ref_01", "speaker_name": "蓝绒小龙A", "text": "别找我，我只是只小龙。"},
        {"speaker_id": "ref_02", "speaker_name": "蓝绒小龙B", "text": "你不是认错，是不敢认。"},
        {"speaker_id": "ref_01", "speaker_name": "小男孩", "text": "三年藏锋够了。"},
        {"speaker_id": "ref_05", "speaker_name": "画外音", "text": "旧钟在海底再次响起。"},
    ]

    StageContentMixin._realign_dialogue_lines_with_roles(dialogue_lines, roles)

    assert dialogue_lines[0]["speaker_id"] == "ref_03"
    assert dialogue_lines[0]["speaker_name"] == "蓝绒小龙A"
    assert dialogue_lines[1]["speaker_id"] == "ref_04"
    assert dialogue_lines[1]["speaker_name"] == "蓝绒小龙B"
    assert dialogue_lines[2]["speaker_id"] == "ref_01"
    assert dialogue_lines[2]["speaker_name"] == "小男孩"
    assert dialogue_lines[3]["speaker_id"] == "ref_05"
    assert dialogue_lines[3]["speaker_name"] == "画外音"


def test_stabilize_role_reference_mapping_avoids_ambiguous_form_merges() -> None:
    references = [
        {"id": "ref_01", "name": "龙王（人形态）", "appearance_description": "男孩形态"},
        {"id": "ref_02", "name": "龙王（龙形态）", "appearance_description": "小龙形态"},
        {"id": "ref_03", "name": "三妹（人形态）", "appearance_description": "女孩形态"},
        {"id": "ref_04", "name": "三妹（龙形态）", "appearance_description": "小龙形态"},
    ]
    roles = [
        {"id": "ref_01", "name": "龙王"},
        {"id": "ref_02", "name": "三妹"},
        {"id": "ref_03", "name": "画外音"},
    ]

    StageContentMixin._stabilize_role_reference_mapping(roles, references)

    assert roles[0]["id"] == ""
    assert roles[1]["id"] == ""
    assert roles[2]["id"] == ""
