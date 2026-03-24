"""StageService — composed from domain-specific mixins.

The actual method implementations live in:
- stage_base_mixin.py          — infrastructure (DB helpers, file ops, retry)
- stage_orchestration_mixin.py — run/stream/pipeline/cancel
- stage_content_mixin.py       — content domain logic + content↔reference bridge
- stage_reference_mixin.py     — reference domain logic
- stage_asset_mixin.py         — image/video/audio asset CRUD
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.stage_asset_mixin import StageAssetMixin
from app.services.stage_base_mixin import StageBaseMixin
from app.services.stage_content_mixin import StageContentMixin
from app.services.stage_orchestration_mixin import StageOrchestrationMixin
from app.services.stage_reference_mixin import StageReferenceMixin
from app.services.stage_shot_mixin import StageShotMixin


class StageService(
    StageOrchestrationMixin,
    StageContentMixin,
    StageReferenceMixin,
    StageShotMixin,
    StageAssetMixin,
    StageBaseMixin,
):
    """Unified stage service — all methods available via a single class."""

    def __init__(self, db: AsyncSession):
        self.db = db
