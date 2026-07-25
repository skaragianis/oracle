import logging
from collections.abc import Iterator

import pytest

from oracle.common.logging_config import (
    DEFAULT_LEVEL,
    NOISY_LIBRARIES,
    build_config,
    configure_logging,
    silence_library_handlers,
)


@pytest.fixture(autouse=True)
def restore_root_logging() -> Iterator[None]:
    """configure_logging owns the root logger, so put it back for other tests."""
    handlers = logging.root.handlers[:]
    level = logging.root.level
    yield
    logging.root.handlers[:] = handlers
    logging.root.setLevel(level)


def test_configure_logging_does_not_accumulate_handlers() -> None:
    configure_logging()
    configure_logging()
    configure_logging()

    assert len(logging.root.handlers) == 1


def test_configure_logging_rebinds_the_stream_each_call(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Entry points call configure_logging on every invocation, and the CLI tests
    # call main() repeatedly. A cached handler would stay bound to the stderr
    # captured by whichever test ran first.
    configure_logging("INFO")
    capsys.readouterr()

    configure_logging("INFO")
    logging.getLogger("oracle.test").info("after reconfigure")

    assert "after reconfigure" in capsys.readouterr().err


def test_configure_logging_takes_an_explicit_level() -> None:
    configure_logging("DEBUG")

    assert logging.root.level == logging.DEBUG


def test_configure_logging_reads_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ORACLE_LOG_LEVEL", "debug")

    configure_logging()

    assert logging.root.level == logging.DEBUG


def test_configure_logging_falls_back_on_an_unknown_level(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ORACLE_LOG_LEVEL", "chatty")

    configure_logging()

    assert logging.root.level == logging.getLevelNamesMapping()[DEFAULT_LEVEL]
    assert "Unknown log level" in capsys.readouterr().err


def test_configured_output_carries_level_and_logger_name(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO")

    logging.getLogger("oracle.test").warning("something happened")

    err = capsys.readouterr().err
    assert "WARNING" in err
    assert "oracle.test: something happened" in err


def test_noisy_libraries_are_quiet_at_info(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO")

    logging.getLogger("chromadb.segment").info("chatty startup detail")
    logging.getLogger("oracle.test").info("ours")

    err = capsys.readouterr().err
    assert "chatty startup detail" not in err
    assert "ours" in err


def test_noisy_libraries_still_report_warnings(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO")

    logging.getLogger("chromadb.segment").warning("something went wrong")

    assert "something went wrong" in capsys.readouterr().err


def test_silence_library_handlers_removes_a_librarys_own_handler(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # huggingface_hub attaches a stderr handler while leaving propagate True, so
    # its records would otherwise print once through it and once through ours.
    hub = logging.getLogger("huggingface_hub")
    hub.addHandler(logging.StreamHandler())
    configure_logging("INFO")

    silence_library_handlers()

    assert hub.handlers == []
    assert hub.propagate is True
    hub.warning("model download detail")
    assert capsys.readouterr().err.count("model download detail") == 1


def test_build_config_leaves_existing_loggers_enabled() -> None:
    # uvicorn configures its loggers before our entry point runs in some
    # orderings; disabling them would silence the access log.
    assert build_config("INFO")["disable_existing_loggers"] is False


def test_build_config_covers_every_noisy_library() -> None:
    loggers = build_config("INFO")["loggers"]

    assert set(loggers) == set(NOISY_LIBRARIES)
    assert all(config["level"] == "WARNING" for config in loggers.values())
