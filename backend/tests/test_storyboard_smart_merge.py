import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.project import Project
from app.models.stage import StageExecution, StageStatus, StageType
from app.providers.video_capabilities import get_recommended_single_generation_limit_seconds
from app.services.stage_service import StageService
from app.stages.prompts.storyboard import resolve_storyboard_prompt_config
from app.stages.storyboard import StoryboardHandler


def _shot(
    index: int,
    voice_content: str,
    *,
    speaker_id: str = "ref_01",
    speaker_name: str = "讲述者",
    reference_ids: list[str] | None = None,
) -> dict[str, object]:
    return {
        "shot_id": f"shot_{index + 1}",
        "shot_index": index,
        "voice_content": voice_content,
        "speaker_id": speaker_id,
        "speaker_name": speaker_name,
        "video_prompt": f"prompt-{index + 1}",
        "video_reference_slots": [
            {"order": ref_index + 1, "id": ref_id, "name": ref_id}
            for ref_index, ref_id in enumerate(reference_ids or [])
        ],
    }


def test_get_recommended_single_generation_limit_seconds_for_wan2gp_sliding_window() -> None:
    limit = get_recommended_single_generation_limit_seconds("wan2gp", "ltx2_22B", "t2v")
    assert limit is not None
    assert limit == pytest.approx(481 / 24, rel=1e-6)


def test_get_recommended_single_generation_limit_seconds_for_wan2gp_without_sliding_window() -> (
    None
):
    limit = get_recommended_single_generation_limit_seconds("wan2gp", "t2v_1.3B", "t2v")
    assert limit == 5.0


def test_build_prompt_dispatches_standard_mode_for_single_and_custom() -> None:
    handler = StoryboardHandler()
    prompt_config = resolve_storyboard_prompt_config(
        {"target_language": "zh", "prompt_complexity": "normal"}
    )

    single_prompt = handler._build_prompt(
        script_mode="single",
        title="标题",
        source_display="一段文案",
        reference_info="无可用参考；若不需要参考，video_reference_slots 返回 []。",
        shot_plan_note="建议 3 个分镜",
        only_shot_index=None,
        existing_shots=[],
        prompt_config=prompt_config,
    )
    custom_prompt = handler._build_prompt(
        script_mode="custom",
        title="标题",
        source_display="一段文案",
        reference_info="无可用参考；若不需要参考，video_reference_slots 返回 []。",
        shot_plan_note="建议 3 个分镜",
        only_shot_index=None,
        existing_shots=[],
        prompt_config=prompt_config,
    )

    assert "信息型口播短视频" in single_prompt
    assert "信息型口播短视频" in custom_prompt
    assert "左侧角色/右侧角色" not in single_prompt


def test_build_prompt_dispatches_mode_specific_guidance() -> None:
    handler = StoryboardHandler()
    prompt_config = resolve_storyboard_prompt_config(
        {"target_language": "zh", "prompt_complexity": "normal"}
    )

    duo_prompt = handler._build_prompt(
        script_mode="duo_podcast",
        title="标题",
        source_display="甲：你好。乙：你好。",
        reference_info="无可用参考；若不需要参考，video_reference_slots 返回 []。",
        shot_plan_note="建议 2 个分镜",
        only_shot_index=None,
        existing_shots=[],
        prompt_config=prompt_config,
    )
    dialogue_prompt = handler._build_prompt(
        script_mode="dialogue_script",
        title="标题",
        source_display="角色A：你好。角色B：别过来。",
        reference_info="无可用参考；若不需要参考，video_reference_slots 返回 []。",
        shot_plan_note="建议 2 个分镜",
        only_shot_index=None,
        existing_shots=[],
        prompt_config=prompt_config,
    )

    assert "左侧角色/右侧角色" in duo_prompt
    assert "动作层变化" in duo_prompt
    assert "分镜差异化" not in duo_prompt
    assert "同一种坐姿和同一类手势" in duo_prompt
    assert "剧情推进" in dialogue_prompt
    assert "当前说话角色必须在镜头中可辨识" in dialogue_prompt


def test_build_reference_info_for_duo_podcast_includes_seats_and_scene(tmp_path) -> None:
    ref_01 = tmp_path / "ref_01.png"
    ref_02 = tmp_path / "ref_02.png"
    ref_01.write_bytes(b"img")
    ref_02.write_bytes(b"img")

    reference_info, allowed_ids = StoryboardHandler._build_reference_info(
        {
            "references": [
                {"id": "ref_01", "name": "包拯", "setting": "冷静理性"},
                {"id": "ref_02", "name": "公孙策", "setting": "好奇敏锐"},
                {"id": "ref_03", "name": "播客场景", "setting": "双人播客录音间"},
            ],
            "reference_images": [
                {"id": "ref_01", "file_path": str(ref_01)},
                {"id": "ref_02", "file_path": str(ref_02)},
            ],
        },
        script_mode="duo_podcast",
        content_data={
            "roles": [
                {
                    "id": "ref_01",
                    "name": "包拯",
                    "description": "冷静理性",
                    "seat_side": "left",
                },
                {
                    "id": "ref_02",
                    "name": "公孙策",
                    "description": "好奇敏锐",
                    "seat_side": "right",
                },
                {
                    "id": "ref_03",
                    "name": "播客场景",
                    "description": "双人播客录音间",
                },
            ]
        },
    )

    assert allowed_ids == {"ref_01", "ref_02"}
    assert reference_info == (
        "- ref_01: 包拯 | 左侧座位 | 冷静理性\n- ref_02: 公孙策 | 右侧座位 | 好奇敏锐"
    )


def test_storyboard_prompt_consumes_target_language_and_complexity() -> None:
    handler = StoryboardHandler()
    prompt_config = resolve_storyboard_prompt_config(
        {"target_language": "en", "prompt_complexity": "detailed"}
    )

    prompt = handler._build_prompt(
        script_mode="single",
        title="Title",
        source_display="Some content",
        reference_info="No references.",
        shot_plan_note="Keep around 3 shots",
        only_shot_index=None,
        existing_shots=[],
        prompt_config=prompt_config,
    )

    assert "视频描述目标语言：en（英文）" in prompt
    assert "视频描述目标复杂度：detailed（细节）" in prompt
    assert "约 110-220 词" in prompt


def test_parse_json_response_text_repairs_missing_comma() -> None:
    raw_text = """
这里有一些额外说明
{
  "shots": [
    {
      "shot_index": 0,
      "voice_content": "第一句"
      "speaker_id": "ref_01",
      "speaker_name": "讲述者",
      "video_prompt": "第一个镜头",
      "video_reference_slots": []
    }
  ]
}
"""

    parsed = StoryboardHandler._parse_json_response_text(raw_text)

    assert isinstance(parsed, dict)
    assert parsed["shots"][0]["voice_content"] == "第一句"
    assert parsed["shots"][0]["speaker_id"] == "ref_01"


def test_validate_and_normalize_snaps_minor_voice_drift_back_to_source_text() -> None:
    handler = StoryboardHandler()
    result = {
        "shots": [
            {
                "shot_index": 0,
                "voice_content": "今天下雨我们",
                "speaker_id": "ref_01",
                "speaker_name": "讲述者",
                "video_prompt": "第一个镜头",
                "video_reference_slots": [],
            },
            {
                "shot_index": 1,
                "voice_content": "去吃饭吧",
                "speaker_id": "ref_01",
                "speaker_name": "讲述者",
                "video_prompt": "第二个镜头",
                "video_reference_slots": [],
            },
        ]
    }

    normalized, error = handler._validate_and_normalize(
        result=result,
        source_reference="今天下雨了，我们去吃饭吧。",
        dialogue_lines=[],
        script_mode="single",
        allowed_reference_ids=set(),
        only_shot_index=None,
        existing_shots=[],
    )

    assert error is None
    assert normalized is not None
    assert [item["voice_content"] for item in normalized] == ["今天下雨了，我们", "去吃饭吧。"]


def test_validate_and_normalize_rejects_large_voice_drift() -> None:
    handler = StoryboardHandler()
    result = {
        "shots": [
            {
                "shot_index": 0,
                "voice_content": "完全不同的句子",
                "speaker_id": "ref_01",
                "speaker_name": "讲述者",
                "video_prompt": "错误镜头",
                "video_reference_slots": [],
            }
        ]
    }

    normalized, error = handler._validate_and_normalize(
        result=result,
        source_reference="今天下雨了，我们去吃饭吧。",
        dialogue_lines=[],
        script_mode="single",
        allowed_reference_ids=set(),
        only_shot_index=None,
        existing_shots=[],
    )

    assert normalized is None
    assert error == "voice_content 没有完整按顺序覆盖原文"


def test_validate_and_normalize_single_shot_regenerate_reuses_exact_existing_voice() -> None:
    handler = StoryboardHandler()
    existing_shots = [_shot(0, "今天下雨了，我们去吃饭吧。")]
    result = {
        "shots": [
            {
                "shot_index": 0,
                "voice_content": "今天下雨我们去吃饭吧",
                "speaker_id": "ref_01",
                "speaker_name": "讲述者",
                "video_prompt": "重新生成后的镜头",
                "video_reference_slots": [],
            }
        ]
    }

    normalized, error = handler._validate_and_normalize(
        result=result,
        source_reference="今天下雨了，我们去吃饭吧。",
        dialogue_lines=[],
        script_mode="single",
        allowed_reference_ids=set(),
        only_shot_index=0,
        existing_shots=existing_shots,
    )

    assert error is None
    assert normalized is not None
    assert normalized[0]["voice_content"] == "今天下雨了，我们去吃饭吧。"


def test_validate_and_normalize_rewrites_duo_podcast_speaker_ids_back_to_role_ids() -> None:
    handler = StoryboardHandler()
    result = {
        "shots": [
            {
                "shot_index": 0,
                "voice_content": "第一句。",
                "speaker_id": "bao_zheng",
                "speaker_name": "包拯",
                "video_prompt": "镜头一",
                "video_reference_slots": [],
            },
            {
                "shot_index": 1,
                "voice_content": "第二句。",
                "speaker_id": "gongsun_ce",
                "speaker_name": "公孙策",
                "video_prompt": "镜头二",
                "video_reference_slots": [],
            },
        ]
    }

    normalized, error = handler._validate_and_normalize(
        result=result,
        source_reference="第一句。第二句。",
        dialogue_lines=[
            {
                "id": "line_001",
                "speaker_id": "ref_01",
                "speaker_name": "包拯",
                "text": "第一句。",
                "order": 0,
            },
            {
                "id": "line_002",
                "speaker_id": "ref_02",
                "speaker_name": "公孙策",
                "text": "第二句。",
                "order": 1,
            },
        ],
        script_mode="duo_podcast",
        allowed_reference_ids=set(),
        only_shot_index=None,
        existing_shots=[],
    )

    assert error is None
    assert normalized is not None
    assert normalized[0]["speaker_id"] == "ref_01"
    assert normalized[0]["speaker_name"] == "包拯"
    assert normalized[1]["speaker_id"] == "ref_02"
    assert normalized[1]["speaker_name"] == "公孙策"


def test_validate_and_normalize_rewrites_single_speaker_ids_back_to_role_ids() -> None:
    handler = StoryboardHandler()
    result = {
        "shots": [
            {
                "shot_index": 0,
                "voice_content": "第一句。",
                "speaker_id": "ref_01",
                "speaker_name": "旁白",
                "video_prompt": "镜头一",
                "video_reference_slots": [],
            }
        ]
    }

    normalized, error = handler._validate_and_normalize(
        result=result,
        source_reference="第一句。",
        dialogue_lines=[
            {
                "id": "line_001",
                "speaker_id": "ref_01",
                "speaker_name": "讲述者",
                "text": "第一句。",
                "order": 0,
            }
        ],
        script_mode="single",
        allowed_reference_ids=set(),
        only_shot_index=None,
        existing_shots=[],
    )

    assert error is None
    assert normalized is not None
    assert normalized[0]["speaker_id"] == "ref_01"
    assert normalized[0]["speaker_name"] == "讲述者"


def test_validate_smart_merge_and_normalize_accepts_contiguous_same_speaker_merge() -> None:
    handler = StoryboardHandler()
    existing_shots = [
        _shot(0, "第一句", reference_ids=["ref_a", "ref_b"]),
        _shot(1, "第二句", reference_ids=["ref_a"]),
        _shot(2, "第三句", reference_ids=["ref_a"]),
    ]
    result = {
        "shots": [
            {
                "shot_index": 0,
                "source_shot_indices": [0, 1],
                "voice_content": "第一句第二句",
                "speaker_id": "ref_01",
                "speaker_name": "讲述者",
                "video_prompt": "覆盖前两句的连续镜头",
                "video_reference_slots": [{"order": 1, "id": "ref_a", "name": "ref_a"}],
            },
            {
                "shot_index": 1,
                "source_shot_indices": [2],
                "voice_content": "第三句",
                "speaker_id": "ref_01",
                "speaker_name": "讲述者",
                "video_prompt": "第三句单独镜头",
                "video_reference_slots": [{"order": 1, "id": "ref_a", "name": "ref_a"}],
            },
        ]
    }

    normalized, error = handler._validate_smart_merge_and_normalize(
        result=result,
        existing_shots=existing_shots,
        shot_durations={0: 2.0, 1: 2.2, 2: 1.8},
        allowed_reference_ids={"ref_a", "ref_b"},
        use_first_frame_ref=True,
        use_reference_image_ref=False,
    )

    assert error is None
    assert normalized is not None
    assert len(normalized) == 2
    assert normalized[0]["voice_content"] == "第一句第二句"
    assert normalized[0]["metadata"]["smart_merge"]["source_shot_indices"] == [0, 1]
    assert normalized[0]["metadata"]["smart_merge"]["merged_duration_seconds"] == pytest.approx(4.2)


def test_validate_smart_merge_and_normalize_rejects_cross_speaker_merge() -> None:
    handler = StoryboardHandler()
    existing_shots = [
        _shot(0, "甲说", speaker_id="ref_01", speaker_name="甲"),
        _shot(1, "乙说", speaker_id="ref_02", speaker_name="乙"),
    ]
    result = {
        "shots": [
            {
                "shot_index": 0,
                "source_shot_indices": [0, 1],
                "voice_content": "甲说乙说",
                "speaker_id": "ref_01",
                "speaker_name": "甲",
                "video_prompt": "错误合并",
                "video_reference_slots": [],
            }
        ]
    }

    normalized, error = handler._validate_smart_merge_and_normalize(
        result=result,
        existing_shots=existing_shots,
        shot_durations={0: 2.0, 1: 2.0},
        allowed_reference_ids=set(),
        use_first_frame_ref=False,
        use_reference_image_ref=False,
    )

    assert normalized is None
    assert error == "第 1 个合并分镜跨 speaker_id 合并"


def test_repair_smart_merge_result_splits_cross_speaker_merge() -> None:
    handler = StoryboardHandler()
    existing_shots = [
        _shot(0, "甲说", speaker_id="ref_01", speaker_name="甲"),
        _shot(1, "乙说", speaker_id="ref_02", speaker_name="乙"),
    ]
    result = {
        "shots": [
            {
                "shot_index": 0,
                "source_shot_indices": [0, 1],
                "voice_content": "甲说乙说",
                "speaker_id": "ref_01",
                "speaker_name": "甲",
                "video_prompt": "错误合并",
                "video_reference_slots": [],
            }
        ]
    }
    issue = handler._smart_merge_issue(
        code="cross_speaker_merge",
        message="第 1 个合并分镜跨 speaker_id 合并",
        shot_index=0,
        source_indices=[0, 1],
    )

    repaired, note = handler._repair_smart_merge_result(
        result=result,
        issue=issue,
        existing_shots=existing_shots,
        shot_durations={0: 2.0, 1: 2.0},
        allowed_reference_ids=set(),
        use_first_frame_ref=False,
        use_reference_image_ref=False,
    )

    assert note == "split cross-speaker segment"
    assert repaired is not None
    repaired_shots = repaired["shots"]
    assert len(repaired_shots) == 2
    assert repaired_shots[0]["source_shot_indices"] == [0]
    assert repaired_shots[1]["source_shot_indices"] == [1]
    assert repaired_shots[0]["speaker_id"] == "ref_01"
    assert repaired_shots[1]["speaker_id"] == "ref_02"


def test_validate_smart_merge_and_normalize_rejects_reference_growth_in_first_frame_mode() -> None:
    handler = StoryboardHandler()
    existing_shots = [
        _shot(0, "前句", reference_ids=["ref_a"]),
        _shot(1, "后句", reference_ids=["ref_a", "ref_b"]),
    ]
    result = {
        "shots": [
            {
                "shot_index": 0,
                "source_shot_indices": [0, 1],
                "voice_content": "前句后句",
                "speaker_id": "ref_01",
                "speaker_name": "讲述者",
                "video_prompt": "错误合并",
                "video_reference_slots": [{"order": 1, "id": "ref_a", "name": "ref_a"}],
            }
        ]
    }

    normalized, error = handler._validate_smart_merge_and_normalize(
        result=result,
        existing_shots=existing_shots,
        shot_durations={0: 2.0, 1: 2.0},
        allowed_reference_ids={"ref_a", "ref_b"},
        use_first_frame_ref=True,
        use_reference_image_ref=False,
    )

    assert normalized is None
    assert error == "第 1 个合并分镜违反首帧参考递减约束"


def test_build_smart_merge_prompt_dispatches_mode_and_conditional_reference_rule() -> None:
    handler = StoryboardHandler()
    shots = [
        _shot(0, "第一句", speaker_id="ref_01", speaker_name="讲述者1", reference_ids=["ref_a"]),
        _shot(1, "第二句", speaker_id="ref_01", speaker_name="讲述者1", reference_ids=["ref_a"]),
    ]
    prompt_config = resolve_storyboard_prompt_config(
        {"target_language": "zh", "prompt_complexity": "normal"}
    )

    duo_prompt = handler._build_smart_merge_prompt(
        title="标题",
        script_mode="duo_podcast",
        shots=shots,
        shot_durations={0: 2.0, 1: 2.1},
        reference_info="可用参考",
        video_provider="wan2gp",
        video_model="ltx2_22B",
        video_mode="i2v",
        max_duration_seconds=5.0,
        use_first_frame_ref=True,
        use_reference_image_ref=False,
        prompt_config=prompt_config,
    )
    standard_prompt = handler._build_smart_merge_prompt(
        title="标题",
        script_mode="single",
        shots=shots,
        shot_durations={0: 2.0, 1: 2.1},
        reference_info="可用参考",
        video_provider="wan2gp",
        video_model="ltx2_22B",
        video_mode="t2v",
        max_duration_seconds=5.0,
        use_first_frame_ref=False,
        use_reference_image_ref=False,
        prompt_config=prompt_config,
    )

    assert "同一位讲述者连续输出" in duo_prompt
    assert "后一个原分镜的参考集合只能与前一个相同或更少" in duo_prompt
    assert "后一个原分镜的参考集合只能与前一个相同或更少" not in standard_prompt
    assert "严禁出现跨分镜依赖表达" not in duo_prompt
    assert "5. 当前视频总时长约 4.100 秒，镜头数 2 个，平均每段时长约 2.050 秒" in duo_prompt
    assert "按照每个镜头不超过 5.000 秒计算，最大压缩到 1 个，比较合理的区间是 1-2 个" in duo_prompt


def test_build_smart_merge_prompt_uses_ninety_percent_cap_for_recommended_minimum() -> None:
    handler = StoryboardHandler()
    shots = [
        _shot(0, "第一句", speaker_id="ref_01", speaker_name="讲述者1", reference_ids=["ref_a"]),
        _shot(1, "第二句", speaker_id="ref_01", speaker_name="讲述者1", reference_ids=["ref_a"]),
        _shot(2, "第三句", speaker_id="ref_01", speaker_name="讲述者1", reference_ids=["ref_a"]),
        _shot(3, "第四句", speaker_id="ref_01", speaker_name="讲述者1", reference_ids=["ref_a"]),
    ]
    prompt_config = resolve_storyboard_prompt_config(
        {"target_language": "zh", "prompt_complexity": "normal"}
    )

    prompt = handler._build_smart_merge_prompt(
        title="标题",
        script_mode="single",
        shots=shots,
        shot_durations={0: 2.3, 1: 2.3, 2: 2.3, 3: 2.3},
        reference_info="可用参考",
        video_provider="wan2gp",
        video_model="ltx2_22B",
        video_mode="t2v",
        max_duration_seconds=5.0,
        use_first_frame_ref=False,
        use_reference_image_ref=False,
        prompt_config=prompt_config,
    )

    assert "当前视频总时长约 9.200 秒，镜头数 4 个，平均每段时长约 2.300 秒" in prompt
    assert "按照每个镜头不超过 5.000 秒计算，最大压缩到 2 个，比较合理的区间是 3-3 个" in prompt


def test_resolve_smart_merge_prompt_duration_limit_caps_at_ten_seconds() -> None:
    assert StoryboardHandler._resolve_smart_merge_prompt_duration_limit(6.062) == pytest.approx(
        6.062, rel=1e-6
    )
    assert StoryboardHandler._resolve_smart_merge_prompt_duration_limit(14.5) == pytest.approx(
        10.0, rel=1e-6
    )


def test_resolve_smart_merge_video_context_returns_theoretical_duration(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.stages.storyboard.get_theoretical_single_generation_limit_seconds",
        lambda provider, model, mode: 30.0,
    )

    provider, model, mode, limit = StoryboardHandler._resolve_smart_merge_video_context(
        {
            "video_provider": "wan2gp",
            "use_first_frame_ref": False,
            "video_wan2gp_t2v_preset": "ltx2_23b_22b_distilled",
            "video_wan2gp_sliding_window_size": 97,
        }
    )

    assert provider == "wan2gp"
    assert model == "ltx2_23b_22b_distilled"
    assert mode == "t2v"
    assert limit == 30.0


def test_collect_smart_merge_duration_warnings_only_warns_when_far_over_theoretical_limit() -> None:
    shots = [
        {
            "metadata": {
                "smart_merge": {
                    "merged_duration_seconds": 10.272,
                }
            }
        },
        {
            "metadata": {
                "smart_merge": {
                    "merged_duration_seconds": 8.1,
                }
            }
        },
    ]

    warnings = StoryboardHandler._collect_smart_merge_duration_warnings(
        shots=shots,
        theoretical_max_duration_seconds=7.5,
    )

    assert warnings == [
        "第 1 个合并分镜时长 10.272s，超过了理论单次运行上限较多（理论上限 7.500s）"
    ]


@pytest.mark.asyncio
async def test_generate_smart_merge_with_retry_prefers_llm_local_repair(
    monkeypatch,
) -> None:
    handler = StoryboardHandler()
    stage = SimpleNamespace(progress=0, output_data={})

    class FakeProvider:
        def __init__(self) -> None:
            self.stream_calls = 0

        async def generate_stream(self, *, prompt: str, system_prompt: str, temperature: float):
            self.stream_calls += 1
            if self.stream_calls == 1:
                yield json.dumps(
                    {
                        "shots": [
                            {
                                "shot_index": 0,
                                "source_shot_indices": [0, 1],
                                "voice_content": "甲说乙说",
                                "speaker_id": "ref_01",
                                "speaker_name": "甲",
                                "video_prompt": "错误合并",
                                "video_reference_slots": [],
                            }
                        ]
                    },
                    ensure_ascii=False,
                )
                return
            yield json.dumps(
                {
                    "shots": [
                        {
                            "shot_index": 0,
                            "source_shot_indices": [0],
                            "voice_content": "甲说",
                            "speaker_id": "ref_01",
                            "speaker_name": "甲",
                            "video_prompt": "甲的修复镜头",
                            "video_reference_slots": [],
                        },
                        {
                            "shot_index": 1,
                            "source_shot_indices": [1],
                            "voice_content": "乙说",
                            "speaker_id": "ref_02",
                            "speaker_name": "乙",
                            "video_prompt": "乙的修复镜头",
                            "video_reference_slots": [],
                        },
                    ]
                },
                ensure_ascii=False,
            )

    async def fake_persist_stream_progress(*, db, stage, raw_text: str) -> None:
        return None

    monkeypatch.setattr(
        handler, "_persist_storyboard_stream_progress", fake_persist_stream_progress
    )

    provider = FakeProvider()
    existing_shots = [
        _shot(0, "甲说", speaker_id="ref_01", speaker_name="甲"),
        _shot(1, "乙说", speaker_id="ref_02", speaker_name="乙"),
    ]

    shots, error = await handler._generate_smart_merge_with_retry(
        db=None,  # type: ignore[arg-type]
        stage=stage,  # type: ignore[arg-type]
        provider=provider,
        provider_name="test",
        provider_type="test",
        model="test",
        prompt="prompt",
        existing_shots=existing_shots,
        shot_durations={0: 2.0, 1: 2.0},
        allowed_reference_ids=set(),
        reference_info="可用参考",
        title="标题",
        script_mode="single",
        prompt_config=resolve_storyboard_prompt_config(
            {"target_language": "zh", "prompt_complexity": "normal"}
        ),
        max_duration_seconds=5.0,
        use_first_frame_ref=False,
        use_reference_image_ref=False,
    )

    assert error is None
    assert shots is not None
    assert provider.stream_calls == 2
    assert len(shots) == 2
    assert shots[0]["speaker_id"] == "ref_01"
    assert shots[1]["speaker_id"] == "ref_02"
    assert shots[0]["video_prompt"] == "甲的修复镜头"
    assert shots[1]["video_prompt"] == "乙的修复镜头"


@pytest.mark.asyncio
async def test_generate_smart_merge_with_retry_falls_back_to_programmatic_repair(
    monkeypatch,
) -> None:
    handler = StoryboardHandler()
    stage = SimpleNamespace(progress=0, output_data={})

    class FakeProvider:
        def __init__(self) -> None:
            self.stream_calls = 0

        async def generate_stream(self, *, prompt: str, system_prompt: str, temperature: float):
            self.stream_calls += 1
            yield json.dumps(
                {
                    "shots": [
                        {
                            "shot_index": 0,
                            "source_shot_indices": [0, 1],
                            "voice_content": "甲说乙说",
                            "speaker_id": "ref_01",
                            "speaker_name": "甲",
                            "video_prompt": "错误合并",
                            "video_reference_slots": [],
                        }
                    ]
                },
                ensure_ascii=False,
            )

    async def fake_persist_stream_progress(*, db, stage, raw_text: str) -> None:
        return None

    monkeypatch.setattr(
        handler, "_persist_storyboard_stream_progress", fake_persist_stream_progress
    )

    provider = FakeProvider()
    existing_shots = [
        _shot(0, "甲说", speaker_id="ref_01", speaker_name="甲"),
        _shot(1, "乙说", speaker_id="ref_02", speaker_name="乙"),
    ]

    shots, error = await handler._generate_smart_merge_with_retry(
        db=None,  # type: ignore[arg-type]
        stage=stage,  # type: ignore[arg-type]
        provider=provider,
        provider_name="test",
        provider_type="test",
        model="test",
        prompt="prompt",
        existing_shots=existing_shots,
        shot_durations={0: 2.0, 1: 2.0},
        allowed_reference_ids=set(),
        reference_info="可用参考",
        title="标题",
        script_mode="single",
        prompt_config=resolve_storyboard_prompt_config(
            {"target_language": "zh", "prompt_complexity": "normal"}
        ),
        max_duration_seconds=5.0,
        use_first_frame_ref=False,
        use_reference_image_ref=False,
    )

    assert error is None
    assert shots is not None
    assert provider.stream_calls == 2
    assert len(shots) == 2
    assert shots[0]["speaker_id"] == "ref_01"
    assert shots[1]["speaker_id"] == "ref_02"


@pytest.mark.asyncio
async def test_storyboard_stream_empty_response_retries_then_succeeds(monkeypatch) -> None:
    handler = StoryboardHandler()
    stage = SimpleNamespace(progress=0, output_data={})
    fallback_messages: list[str] = []

    class FakeProvider:
        def __init__(self) -> None:
            self.stream_calls = 0

        async def generate_stream(self, *, prompt: str, system_prompt: str, temperature: float):
            self.stream_calls += 1
            if self.stream_calls == 1:
                if False:  # pragma: no cover
                    yield ""
                return
            yield '{"shots":[]}'

    provider = FakeProvider()

    async def fake_persist_fallback_progress(*, db, stage, fallback_message: str) -> None:
        fallback_messages.append(fallback_message)

    monkeypatch.setattr(
        handler,
        "_persist_storyboard_stream_fallback_progress",
        fake_persist_fallback_progress,
    )

    response_text = await handler._generate_response_text_with_stream_retry(
        db=None,  # type: ignore[arg-type]
        stage=stage,  # type: ignore[arg-type]
        provider=provider,
        prompt="prompt",
        system_prompt="system",
        temperature=0.2,
        log_prefix="[Storyboard][Test]",
    )

    assert response_text == '{"shots":[]}'
    assert provider.stream_calls == 2
    assert fallback_messages == ["流式中断，正在重试流式生成..."]


@pytest.mark.asyncio
async def test_replace_storyboard_and_clear_downstream(tmp_path, monkeypatch) -> None:
    output_dir = tmp_path / "project-output"
    output_dir.mkdir(parents=True, exist_ok=True)
    audio_file = output_dir / "audio" / "shot_000.mp3"
    audio_source = output_dir / "audio" / "shot_000_raw.wav"
    frame_file = output_dir / "frames" / "frame_000.png"
    video_file = output_dir / "videos" / "shot_000.mp4"
    subtitle_file = output_dir / "subtitles" / "shot_000.srt"
    burned_file = output_dir / "burned.mp4"
    compose_file = output_dir / "compose.mp4"
    merged_file = output_dir / "merged_000.mp4"
    final_file = output_dir / "final_video.mp4"

    for file_path in [
        audio_file,
        audio_source,
        frame_file,
        video_file,
        subtitle_file,
        burned_file,
        compose_file,
        merged_file,
        final_file,
    ]:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(b"data")

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        project = Project(
            title="smart-merge",
            video_type="single",
            output_dir=str(output_dir),
            config={},
        )
        session.add(project)
        await session.flush()

        session.add_all(
            [
                StageExecution(
                    project_id=project.id,
                    project=project,
                    stage_type=StageType.CONTENT,
                    stage_number=2,
                    status=StageStatus.COMPLETED,
                    output_data={
                        "content": "原文甲。原文乙。",
                        "dialogue_lines": [
                            {
                                "id": "line_1",
                                "speaker_id": "ref_01",
                                "speaker_name": "甲",
                                "text": "原文甲。原文乙。",
                                "order": 0,
                            }
                        ],
                        "shots_locked": True,
                    },
                ),
                StageExecution(
                    project_id=project.id,
                    project=project,
                    stage_type=StageType.STORYBOARD,
                    stage_number=3,
                    status=StageStatus.COMPLETED,
                    output_data={"shots": [_shot(0, "原句")], "shot_count": 1},
                ),
                StageExecution(
                    project_id=project.id,
                    project=project,
                    stage_type=StageType.AUDIO,
                    stage_number=4,
                    status=StageStatus.COMPLETED,
                    output_data={
                        "audio_assets": [
                            {
                                "shot_index": 0,
                                "file_path": str(audio_file),
                                "source_file_path": str(audio_source),
                                "duration": 2.0,
                            }
                        ]
                    },
                ),
                StageExecution(
                    project_id=project.id,
                    project=project,
                    stage_type=StageType.FIRST_FRAME_DESC,
                    stage_number=5,
                    status=StageStatus.COMPLETED,
                    output_data={"items": [1]},
                ),
                StageExecution(
                    project_id=project.id,
                    project=project,
                    stage_type=StageType.FRAME,
                    stage_number=6,
                    status=StageStatus.COMPLETED,
                    output_data={"frame_images": [{"shot_index": 0, "file_path": str(frame_file)}]},
                ),
                StageExecution(
                    project_id=project.id,
                    project=project,
                    stage_type=StageType.VIDEO,
                    stage_number=7,
                    status=StageStatus.COMPLETED,
                    output_data={"video_assets": [{"shot_index": 0, "file_path": str(video_file)}]},
                ),
                StageExecution(
                    project_id=project.id,
                    project=project,
                    stage_type=StageType.COMPOSE,
                    stage_number=8,
                    status=StageStatus.COMPLETED,
                    output_data={
                        "master_video_path": str(compose_file),
                        "merged_files": [{"file_path": str(merged_file)}],
                    },
                ),
                StageExecution(
                    project_id=project.id,
                    project=project,
                    stage_type=StageType.SUBTITLE,
                    stage_number=9,
                    status=StageStatus.COMPLETED,
                    output_data={"subtitle_file_path": str(subtitle_file)},
                ),
                StageExecution(
                    project_id=project.id,
                    project=project,
                    stage_type=StageType.BURN_SUBTITLE,
                    stage_number=10,
                    status=StageStatus.COMPLETED,
                    output_data={"burned_video_path": str(burned_file)},
                ),
                StageExecution(
                    project_id=project.id,
                    project=project,
                    stage_type=StageType.FINALIZE,
                    stage_number=11,
                    status=StageStatus.COMPLETED,
                    output_data={"video_path": str(final_file)},
                ),
            ]
        )
        await session.commit()

        service = StageService(session)
        new_storyboard = {
            "script_mode": "single",
            "shots": [
                {
                    "shot_id": "merged_1",
                    "shot_index": 0,
                    "voice_content": "合并后",
                    "speaker_id": "ref_01",
                    "speaker_name": "讲述者",
                    "video_prompt": "新的合并描述",
                    "video_reference_slots": [],
                    "metadata": {
                        "smart_merge": {
                            "source_shot_indices": [0],
                            "source_shot_ids": ["shot_1"],
                            "source_duration_seconds": [2.0],
                            "merged_duration_seconds": 2.0,
                        }
                    },
                }
            ],
            "shot_count": 1,
            "references": [],
        }

        merged_audio_file = output_dir / "audio" / "shot_000.wav"

        async def fake_build_smart_merged_audio_assets(
            *,
            storyboard_payload,
            existing_audio_output,
            output_dir,
        ):
            merged_audio_file.parent.mkdir(parents=True, exist_ok=True)
            merged_audio_file.write_bytes(b"merged-audio")
            return [
                {
                    "shot_index": 0,
                    "voice_content": "合并后",
                    "file_path": str(merged_audio_file),
                    "source_file_path": str(merged_audio_file),
                    "duration": 2.0,
                    "updated_at": 123,
                    "audio_provider": "edge_tts",
                }
            ]

        monkeypatch.setattr(
            service, "_build_smart_merged_audio_assets", fake_build_smart_merged_audio_assets
        )

        await service.replace_storyboard_and_clear_downstream(
            project.id,
            storyboard_payload=new_storyboard,
        )

        result = await session.execute(
            select(StageExecution).where(StageExecution.project_id == project.id)
        )
        stages = {stage.stage_type: stage for stage in result.scalars().all()}

        assert stages[StageType.STORYBOARD].output_data["shot_count"] == 1
        assert stages[StageType.STORYBOARD].output_data["shots"][0]["voice_content"] == "合并后"
        assert stages[StageType.CONTENT].output_data["shots_locked"] is True
        assert stages[StageType.CONTENT].output_data["content"] == "原文甲。原文乙。"
        assert stages[StageType.CONTENT].output_data["dialogue_lines"] == [
            {
                "id": "line_1",
                "speaker_id": "ref_01",
                "speaker_name": "甲",
                "text": "原文甲。原文乙。",
                "order": 0,
            }
        ]
        assert stages[StageType.AUDIO].output_data["audio_assets"] == [
            {
                "shot_index": 0,
                "voice_content": "合并后",
                "file_path": str(merged_audio_file),
                "source_file_path": str(merged_audio_file),
                "duration": 2.0,
                "updated_at": 123,
                "audio_provider": "edge_tts",
            }
        ]
        assert stages[StageType.FRAME].output_data["frame_images"] == []
        assert stages[StageType.VIDEO].output_data["video_assets"] == []
        assert stages[StageType.FIRST_FRAME_DESC].output_data == {}
        assert stages[StageType.COMPOSE].output_data == {}
        assert stages[StageType.SUBTITLE].output_data == {}
        assert stages[StageType.BURN_SUBTITLE].output_data == {}
        assert stages[StageType.FINALIZE].output_data == {}

        for file_path in [
            frame_file,
            video_file,
            subtitle_file,
            burned_file,
            compose_file,
            merged_file,
            final_file,
        ]:
            assert not file_path.exists()
        assert merged_audio_file.exists()
        assert not audio_file.exists()
        assert not audio_source.exists()

    await engine.dispose()


@pytest.mark.asyncio
async def test_storyboard_stream_failure_retries_stream_before_non_stream(monkeypatch) -> None:
    handler = StoryboardHandler()
    stage = SimpleNamespace(progress=0, output_data={})
    fallback_messages: list[str] = []

    class FakeProvider:
        def __init__(self) -> None:
            self.stream_calls = 0
            self.generate_calls = 0

        async def generate_stream(self, *, prompt: str, system_prompt: str, temperature: float):
            self.stream_calls += 1
            if self.stream_calls == 1:
                raise RuntimeError("stream disconnected")
            yield '{"shots":[]}'

        async def generate(self, *, prompt: str, system_prompt: str, temperature: float):
            self.generate_calls += 1
            return SimpleNamespace(content='{"shots":[]}')

    provider = FakeProvider()

    async def fake_persist_fallback_progress(*, db, stage, fallback_message: str) -> None:
        fallback_messages.append(fallback_message)

    monkeypatch.setattr(
        handler,
        "_persist_storyboard_stream_fallback_progress",
        fake_persist_fallback_progress,
    )

    response_text = await handler._generate_response_text_with_stream_retry(
        db=None,  # type: ignore[arg-type]
        stage=stage,  # type: ignore[arg-type]
        provider=provider,
        prompt="prompt",
        system_prompt="system",
        temperature=0.2,
        log_prefix="[Storyboard][Test]",
    )

    assert response_text == '{"shots":[]}'
    assert provider.stream_calls == 2
    assert provider.generate_calls == 0
    assert fallback_messages == ["流式中断，正在重试流式生成..."]


@pytest.mark.asyncio
async def test_storyboard_stream_failure_twice_then_abort(monkeypatch) -> None:
    handler = StoryboardHandler()
    stage = SimpleNamespace(progress=0, output_data={})
    fallback_messages: list[str] = []

    class FakeProvider:
        def __init__(self) -> None:
            self.stream_calls = 0
            self.generate_calls = 0

        async def generate_stream(self, *, prompt: str, system_prompt: str, temperature: float):
            self.stream_calls += 1
            raise RuntimeError(f"stream disconnected {self.stream_calls}")
            yield  # pragma: no cover

        async def generate(self, *, prompt: str, system_prompt: str, temperature: float):
            self.generate_calls += 1
            return SimpleNamespace(content='{"shots":[]}')

    provider = FakeProvider()

    async def fake_persist_fallback_progress(*, db, stage, fallback_message: str) -> None:
        fallback_messages.append(fallback_message)

    monkeypatch.setattr(
        handler,
        "_persist_storyboard_stream_fallback_progress",
        fake_persist_fallback_progress,
    )

    with pytest.raises(RuntimeError, match="流式生成连续中断 2 次"):
        await handler._generate_response_text_with_stream_retry(
            db=None,  # type: ignore[arg-type]
            stage=stage,  # type: ignore[arg-type]
            provider=provider,
            prompt="prompt",
            system_prompt="system",
            temperature=0.2,
            log_prefix="[Storyboard][Test]",
        )

    assert provider.stream_calls == 2
    assert provider.generate_calls == 0
    assert fallback_messages == [
        "流式中断，正在重试流式生成...",
        "流式再次中断，已停止生成，请重试。",
    ]
