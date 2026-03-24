from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.models.stage import StageType
from app.workflow.dag import DagNode, StageDag

if TYPE_CHECKING:
    from app.stages.base import StageHandler


@dataclass(frozen=True)
class StageDefinition:
    stage_type: StageType
    name: str
    icon: str
    description: str
    optional: bool = False
    deps: tuple[StageType, ...] = ()


class StageRegistry:
    def __init__(self, definitions: list[StageDefinition]):
        self._definitions = definitions
        self._by_type: dict[StageType, StageDefinition] = {
            one.stage_type: one for one in definitions
        }
        self._handler_types: dict[StageType, type[StageHandler]] = {}
        dag_nodes = [
            DagNode(stage_type=one.stage_type, deps=one.deps, optional=one.optional)
            for one in definitions
        ]
        self._dag = StageDag(dag_nodes)

    def register_handler(self, stage_type: StageType, handler_cls: type[StageHandler]) -> None:
        self._handler_types[stage_type] = handler_cls

    def create_handler(self, stage_type: StageType) -> StageHandler | None:
        handler_cls = self._handler_types.get(stage_type)
        if handler_cls is None:
            return None
        return handler_cls()

    def get_stage_number(self, stage_type: StageType) -> int:
        order = self._dag.topological_order()
        return order.index(stage_type) + 1

    def list_stage_types(self) -> list[StageType]:
        return self._dag.topological_order()

    def is_optional(self, stage_type: StageType) -> bool:
        definition = self._by_type.get(stage_type)
        return bool(definition and definition.optional)

    def get_stage_type_by_number(self, stage_number: int) -> StageType | None:
        if stage_number <= 0:
            return None
        order = self._dag.topological_order()
        if stage_number > len(order):
            return None
        return order[stage_number - 1]

    def resolve_execution_subset(
        self,
        *,
        from_stage: StageType | None = None,
        to_stage: StageType | None = None,
    ) -> list[StageType]:
        return self._dag.resolve_execution_subset(from_stage=from_stage, to_stage=to_stage)

    def build_manifest(self) -> list[dict]:
        stages = self._dag.topological_order()
        return [
            {
                "type": stage_type.value,
                "number": idx + 1,
                "name": self._by_type[stage_type].name,
                "icon": self._by_type[stage_type].icon,
                "description": self._by_type[stage_type].description,
                "is_optional": self._by_type[stage_type].optional,
            }
            for idx, stage_type in enumerate(stages)
        ]


STAGE_DEFINITIONS: list[StageDefinition] = [
    StageDefinition(
        stage_type=StageType.RESEARCH,
        name="信息搜集",
        icon="🔍",
        description="根据关键词搜索网络信息",
        deps=(),
    ),
    StageDefinition(
        stage_type=StageType.CONTENT,
        name="文案生成",
        icon="✍️",
        description="LLM 生成完整口播文案",
        deps=(StageType.RESEARCH,),
    ),
    StageDefinition(
        stage_type=StageType.STORYBOARD,
        name="分镜生成",
        icon="📝",
        description="LLM 规划分镜并生成视频描述",
        deps=(StageType.CONTENT,),
    ),
    StageDefinition(
        stage_type=StageType.AUDIO,
        name="音频生成",
        icon="🔊",
        description="TTS 语音合成",
        deps=(StageType.STORYBOARD,),
    ),
    StageDefinition(
        stage_type=StageType.REFERENCE,
        name="参考图生成",
        icon="👤",
        description="生成参考图 (I2V)",
        optional=True,
        deps=(StageType.AUDIO,),
    ),
    StageDefinition(
        stage_type=StageType.FIRST_FRAME_DESC,
        name="首帧描述",
        icon="🧾",
        description="逐分镜生成首帧提示词",
        optional=True,
        deps=(StageType.REFERENCE,),
    ),
    StageDefinition(
        stage_type=StageType.FRAME,
        name="首帧生成",
        icon="🖼️",
        description="生成首帧图像 (I2V)",
        optional=True,
        deps=(StageType.FIRST_FRAME_DESC,),
    ),
    StageDefinition(
        stage_type=StageType.VIDEO,
        name="视频生成",
        icon="🎬",
        description="AI 生成分镜视频",
        deps=(StageType.FRAME,),
    ),
    StageDefinition(
        stage_type=StageType.COMPOSE,
        name="母版合成",
        icon="🎥",
        description="FFmpeg 合成无字幕母版视频",
        deps=(StageType.VIDEO,),
    ),
    StageDefinition(
        stage_type=StageType.SUBTITLE,
        name="字幕生成",
        icon="💬",
        description="基于最终视频生成完整字幕",
        optional=True,
        deps=(StageType.COMPOSE,),
    ),
    StageDefinition(
        stage_type=StageType.BURN_SUBTITLE,
        name="字幕烧录",
        icon="📝",
        description="将字幕烧录到最终视频",
        optional=True,
        deps=(StageType.COMPOSE, StageType.SUBTITLE),
    ),
    StageDefinition(
        stage_type=StageType.FINALIZE,
        name="最终成片",
        icon="✅",
        description="统一选择最终交付视频",
        deps=(StageType.COMPOSE, StageType.BURN_SUBTITLE),
    ),
]


stage_registry = StageRegistry(STAGE_DEFINITIONS)
