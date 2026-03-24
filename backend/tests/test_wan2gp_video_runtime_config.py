import json
import shutil
from pathlib import Path

from app.providers.video.wan2gp import Wan2GPVideoProvider


def test_prepare_runtime_config_dir_merges_defaults_with_partial_base_config(
    tmp_path: Path,
) -> None:
    wan2gp_root = tmp_path / "Wan2GP"
    wan2gp_root.mkdir()
    (wan2gp_root / "wgp_config.json").write_text(
        json.dumps(
            {
                "video_profile": 7,
                "checkpoints_paths": ["custom-ckpts"],
            }
        ),
        encoding="utf-8",
    )

    provider = Wan2GPVideoProvider(wan2gp_path=str(wan2gp_root), fit_canvas=2)
    runtime_config_dir = provider._prepare_runtime_config_dir()

    try:
        payload = json.loads((runtime_config_dir / "wgp_config.json").read_text(encoding="utf-8"))
        assert payload["attention_mode"] == "auto"
        assert payload["video_profile"] == 7
        assert payload["checkpoints_paths"] == ["custom-ckpts"]
        assert payload["fit_canvas"] == 2
    finally:
        shutil.rmtree(runtime_config_dir, ignore_errors=True)
