from app.models.stage import StageType
from app.workflow.stage_registry import stage_registry

from .base import StageHandler, StageResult


def register_stage(stage_type: StageType):
    def decorator(cls: type[StageHandler]) -> type[StageHandler]:
        stage_registry.register_handler(stage_type, cls)
        return cls

    return decorator


def get_stage_handler(stage_type: StageType) -> StageHandler | None:
    return stage_registry.create_handler(stage_type)


# Import stage modules to trigger registration decorators
from . import audio as audio  # noqa: F401, E402
from . import burn_subtitle as burn_subtitle  # noqa: F401, E402
from . import compose as compose  # noqa: F401, E402
from . import content as content  # noqa: F401, E402
from . import finalize as finalize  # noqa: F401, E402
from . import first_frame_desc as first_frame_desc  # noqa: F401, E402
from . import frame as frame  # noqa: F401, E402
from . import reference as reference  # noqa: F401, E402
from . import research as research  # noqa: F401, E402
from . import storyboard as storyboard  # noqa: F401, E402
from . import subtitle as subtitle  # noqa: F401, E402
from . import video as video  # noqa: F401, E402
from .vision import generate_description_from_image  # noqa: F401, E402

__all__ = [
    "register_stage",
    "get_stage_handler",
    "StageHandler",
    "StageResult",
    "generate_description_from_image",
]
