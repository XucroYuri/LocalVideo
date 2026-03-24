from __future__ import annotations

import logging

STAGE_SEPARATOR = "=" * 80


def log_stage_separator(logger: logging.Logger) -> None:
    logger.info(STAGE_SEPARATOR)
