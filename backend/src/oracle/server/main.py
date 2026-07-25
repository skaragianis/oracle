from types import FrameType
from typing import override

import uvicorn

from oracle.common.logging_config import configure_logging
from oracle.server import app


class _Server(uvicorn.Server):
    @override
    def handle_exit(self, sig: int, frame: FrameType | None) -> None:
        app.request_shutdown()
        super().handle_exit(sig, frame)


def main() -> None:
    configure_logging()
    config = uvicorn.Config(
        "oracle.server.app:app",
        host="127.0.0.1",
        port=8000,
        log_config=None,
        timeout_graceful_shutdown=app.SHUTDOWN_INGEST_TIMEOUT_SECONDS,
    )
    try:
        _Server(config).run()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
