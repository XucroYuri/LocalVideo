"""Stage metadata manifest generated from stage registry."""

from app.workflow.stage_registry import stage_registry


def build_stage_manifest() -> list[dict]:
    return stage_registry.build_manifest()
