from app.providers.video_capabilities import (
    get_theoretical_single_generation_limit_seconds,
    resolve_requested_duration_seconds,
)


def test_resolve_requested_duration_seconds_keeps_raw_duration_for_wan2gp() -> None:
    resolved = resolve_requested_duration_seconds("wan2gp", "t2v_14B", "t2v", 5.37)

    assert resolved == 5.37


def test_resolve_requested_duration_seconds_rejects_wan2gp_duration_above_model_limit() -> None:
    resolved = resolve_requested_duration_seconds("wan2gp", "t2v_1.3B", "t2v", 22.0)

    assert resolved is None


def test_get_theoretical_single_generation_limit_seconds_for_wan2gp_ignores_sliding_window() -> (
    None
):
    limit = get_theoretical_single_generation_limit_seconds("wan2gp", "ltx2_22B", "t2v")

    assert limit == 30.0
