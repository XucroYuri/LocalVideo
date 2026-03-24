import json

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.models.base import Base
from app.models.voice_library import (
    VoiceItemFieldStatus,
    VoiceLibraryItem,
    VoiceSourceChannel,
)
from app.services.voice_library_service import VoiceLibraryService


@pytest.mark.asyncio
async def test_ensure_builtin_seeded_replaces_manifest_and_preserves_order(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_root = tmp_path / "storage"
    builtin_dir = storage_root / "voice-library" / "builtin"
    builtin_dir.mkdir(parents=True, exist_ok=True)

    manifest = [
        {
            "builtin_key": "builtin:yf-001",
            "name": "星航冷声",
            "reference_text": "第一条",
            "audio_file_path": "/storage/voice-library/builtin/星航冷声.wav",
        },
        {
            "builtin_key": "builtin:yf-002",
            "name": "清亮行旅播客",
            "reference_text": "第二条",
            "audio_file_path": "/storage/voice-library/builtin/清亮行旅播客.wav",
        },
    ]
    (builtin_dir / "星航冷声.wav").write_bytes(b"wav-a")
    (builtin_dir / "清亮行旅播客.wav").write_bytes(b"wav-b")
    (builtin_dir / "builtin_voices.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(settings, "storage_path", str(storage_root), raising=False)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        session.add(
            VoiceLibraryItem(
                name="用户语音",
                reference_text="custom",
                audio_file_path=None,
                is_enabled=True,
                is_builtin=False,
                builtin_key=None,
                source_channel=VoiceSourceChannel.AUDIO_FILE,
                auto_parse_text=True,
                name_status=VoiceItemFieldStatus.READY,
                reference_text_status=VoiceItemFieldStatus.READY,
            )
        )
        session.add(
            VoiceLibraryItem(
                name="旧内置语音",
                reference_text="legacy",
                audio_file_path="/storage/voice-library/builtin/legacy.wav",
                is_enabled=True,
                is_builtin=True,
                builtin_key="aigei:1",
                source_channel=VoiceSourceChannel.BUILTIN,
                auto_parse_text=False,
                name_status=VoiceItemFieldStatus.READY,
                reference_text_status=VoiceItemFieldStatus.READY,
            )
        )
        await session.commit()

        service = VoiceLibraryService(session)
        items, total = await service.list()

        assert total == 3
        assert [item["name"] for item in items] == [
            "用户语音",
            "星航冷声",
            "清亮行旅播客",
        ]

        builtin_result = await session.execute(
            select(VoiceLibraryItem)
            .where(VoiceLibraryItem.is_builtin.is_(True))
            .order_by(VoiceLibraryItem.id.asc())
        )
        builtin_items = list(builtin_result.scalars().all())

        assert [item.name for item in builtin_items] == ["星航冷声", "清亮行旅播客"]
        assert [item.builtin_key for item in builtin_items] == [
            "builtin:yf-001",
            "builtin:yf-002",
        ]
        assert all(item.builtin_key and "aigei" not in item.builtin_key for item in builtin_items)

    await engine.dispose()
