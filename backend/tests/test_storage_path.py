from app.core.storage_path import resolve_existing_path_for_io


def test_resolve_existing_path_for_io_falls_back_to_same_stem_variant(
    tmp_path, monkeypatch
) -> None:
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    frames_dir = storage_root / "demo" / "frames"
    frames_dir.mkdir(parents=True)
    actual_file = frames_dir / "frame_000.jpg"
    actual_file.write_bytes(b"jpg")

    monkeypatch.setattr("app.core.storage_path.settings.storage_path", str(storage_root))

    resolved = resolve_existing_path_for_io("/storage/demo/frames/frame_000.png")

    assert resolved == actual_file.resolve()


def test_resolve_existing_path_for_io_keeps_original_when_variant_missing(
    tmp_path,
    monkeypatch,
) -> None:
    storage_root = tmp_path / "storage"
    storage_root.mkdir()

    monkeypatch.setattr("app.core.storage_path.settings.storage_path", str(storage_root))

    resolved = resolve_existing_path_for_io("/storage/demo/videos/shot_000.mp4")

    assert resolved == (storage_root / "demo" / "videos" / "shot_000.mp4").resolve()
