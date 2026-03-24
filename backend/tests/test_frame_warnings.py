from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.project import Project
from app.models.stage import StageExecution, StageStatus, StageType
from app.providers.base.image import ImageResult
from app.stages.frame import (
    FrameImageTaskAdapter,
    _resolve_wan2gp_preset_default_inference_steps,
)
from app.stages.image_task_engine import ImageTaskRunSettings, ImageTaskSpec, run_image_tasks


def test_frame_stage_output_includes_wan2gp_fallback_warning() -> None:
    adapter = FrameImageTaskAdapter(
        shots=[{"shot_index": 0}],
        provider_name="wan2gp",
        task_warnings_by_key={
            "0": [
                "分镜 1 未找到可用参考图，已从 i2i 自动回退到 t2i 模型 `qwen_image_2512` 继续生成。"
            ],
        },
    )

    output = adapter.build_stage_output(
        current_items=[],
        generating_shots={"0": {"status": "pending", "progress": 0}},
        provider_name="wan2gp",
        progress_message="准备中...",
    )

    result = adapter.build_success_result(
        ImageTaskSpec(
            index=0,
            key="0",
            prompt="test",
            output_path=None,  # type: ignore[arg-type]
            payload={"shot_index": 0, "prompt": "test"},
        ),
        "/tmp/frame_000.png",
    )

    assert output["warnings"] == [
        "分镜 1 未找到可用参考图，已从 i2i 自动回退到 t2i 模型 `qwen_image_2512` 继续生成。"
    ]
    assert "warnings" not in result


def test_frame_stage_output_includes_same_preset_t2i_warning() -> None:
    adapter = FrameImageTaskAdapter(
        shots=[{"shot_index": 0}],
        provider_name="wan2gp",
        task_warnings_by_key={
            "0": ["分镜 1 未找到可用参考图，当前模型 `flux2_klein_4b` 将按 t2i 方式继续生成。"],
        },
    )

    output = adapter.build_stage_output(
        current_items=[],
        generating_shots={"0": {"status": "pending", "progress": 0}},
        provider_name="wan2gp",
        progress_message="准备中...",
    )

    assert output["warnings"] == [
        "分镜 1 未找到可用参考图，当前模型 `flux2_klein_4b` 将按 t2i 方式继续生成。"
    ]


def test_frame_final_data_does_not_persist_runtime_warnings() -> None:
    adapter = FrameImageTaskAdapter(
        shots=[{"shot_index": 0}],
        provider_name="wan2gp",
        task_warnings_by_key={
            "0": ["分镜 1 未找到可用参考图，当前模型 `flux2_klein_4b` 将按 t2i 方式继续生成。"],
        },
    )

    data = adapter.build_final_data(
        final_items=[{"shot_index": 0, "generated": True, "file_path": "/tmp/frame_000.png"}],
        failed_items=[],
    )

    assert "warnings" not in data


def test_frame_stage_output_ignores_historical_item_warnings() -> None:
    adapter = FrameImageTaskAdapter(
        shots=[{"shot_index": 0}, {"shot_index": 1}],
        provider_name="wan2gp",
        task_warnings_by_key={},
    )

    output = adapter.build_stage_output(
        current_items=[
            {
                "shot_index": 0,
                "generated": True,
                "warnings": ["历史 warning，不应在本次运行再次提示"],
            }
        ],
        generating_shots={"1": {"status": "pending", "progress": 0}},
        provider_name="wan2gp",
        progress_message="准备中...",
    )

    assert "warnings" not in output


def test_resolve_wan2gp_fallback_preset_default_inference_steps() -> None:
    assert _resolve_wan2gp_preset_default_inference_steps("flux2_klein_4b") == 4
    assert _resolve_wan2gp_preset_default_inference_steps("qwen_image_2512") == 30


class _ImageTaskAdapter:
    def build_missing_prompt_result(self, spec: ImageTaskSpec) -> dict:
        return {"shot_index": spec.index, "generated": False}

    def build_success_result(self, spec: ImageTaskSpec, file_path: str) -> dict:
        return {"shot_index": spec.index, "generated": True, "file_path": file_path}

    def build_error_result(self, spec: ImageTaskSpec, error: str) -> dict:
        return {"shot_index": spec.index, "generated": False, "error": error}

    def build_stage_output(
        self,
        current_items: list[dict],
        generating_shots: dict[str, dict[str, int | str]],
        provider_name: str,
        progress_message: str | None,
    ) -> dict:
        return {
            "frame_images": current_items,
            "generating_shots": generating_shots,
            "runtime_provider": provider_name,
            "progress_message": progress_message,
        }

    def build_final_data(self, final_items: list[dict], failed_items: list[dict]) -> dict:
        return {"frame_images": final_items, "failed_items": failed_items}

    def build_partial_failure_error(self, failed_items: list[dict]) -> str:
        return str(failed_items)


@pytest.mark.asyncio
async def test_run_image_tasks_uses_fallback_preset_default_steps_for_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    captured_kwargs: dict[str, object] = {}

    class _FakeProvider:
        async def generate(self, **kwargs) -> ImageResult:
            output_path = Path(kwargs["output_path"])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"fake")
            return ImageResult(file_path=output_path, width=1088, height=1920)

    def _fake_get_image_provider(name: str, **kwargs):
        captured_kwargs.clear()
        captured_kwargs.update(kwargs)
        return _FakeProvider()

    monkeypatch.setattr("app.stages.image_task_engine.get_image_provider", _fake_get_image_provider)

    async with session_factory() as session:
        project = Project(
            title="frame-override",
            video_type="custom",
            output_dir=str(tmp_path),
            config={},
        )
        session.add(project)
        await session.flush()

        stage = StageExecution(
            project_id=project.id,
            project=project,
            stage_type=StageType.FRAME,
            stage_number=7,
            status=StageStatus.RUNNING,
        )
        session.add(stage)
        await session.commit()

        result = await run_image_tasks(
            db=session,
            stage=stage,
            task_specs=[
                ImageTaskSpec(
                    index=0,
                    key="0",
                    prompt="test",
                    output_path=tmp_path / "frame_000.png",
                    payload={
                        "shot_index": 0,
                        "wan2gp_image_preset_override": "flux2_klein_4b",
                        "wan2gp_image_inference_steps_override": 4,
                    },
                )
            ],
            all_results=[None],
            adapter=_ImageTaskAdapter(),
            settings=ImageTaskRunSettings(
                provider_name="wan2gp",
                image_provider=_FakeProvider(),
                provider_kwargs={
                    "wan2gp_path": "/tmp/Wan2GP",
                    "python_executable": "/usr/bin/python3",
                    "image_preset": "flux2_dev_nvfp4",
                    "image_inference_steps": 30,
                },
                max_concurrency=1,
                image_resolution="1088x1920",
                allow_wan2gp_batch=False,
            ),
        )

    await engine.dispose()

    assert result.success is True
    assert captured_kwargs["image_preset"] == "flux2_klein_4b"
    assert captured_kwargs["image_inference_steps"] == 4
