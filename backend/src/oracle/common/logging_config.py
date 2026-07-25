import logging
import logging.config
import os
from typing import Any

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
DEFAULT_LEVEL = "INFO"

NOISY_LIBRARIES = (
    "asyncio",
    "chromadb",
    "filelock",
    "grpc",
    "httpcore",
    "httpx",
    "huggingface_hub",
    "opentelemetry",
    "PIL",
    "urllib3",
)


def build_config(level: str) -> dict[str, Any]:
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {"format": LOG_FORMAT, "datefmt": LOG_DATE_FORMAT},
        },
        "handlers": {
            "default": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stderr",
                "formatter": "default",
            },
        },
        "loggers": {name: {"level": "WARNING"} for name in NOISY_LIBRARIES},
        "root": {"handlers": ["default"], "level": level},
    }


def configure_logging(level: str | None = None) -> None:
    resolved = (level or os.environ.get("ORACLE_LOG_LEVEL") or DEFAULT_LEVEL).upper()
    unknown = resolved not in logging.getLevelNamesMapping()
    if unknown:
        resolved = DEFAULT_LEVEL

    logging.config.dictConfig(build_config(resolved))
    logging.captureWarnings(True)
    silence_library_handlers()

    if unknown:
        logging.getLogger(__name__).warning(
            "Unknown log level %r, using %s",
            level or os.environ["ORACLE_LOG_LEVEL"],
            resolved,
        )


def silence_library_handlers() -> None:
    for name in NOISY_LIBRARIES:
        logger = logging.getLogger(name)
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
