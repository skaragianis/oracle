import sys

from oracle.cli.main import main


def test_main_runs_with_no_args_prints_usage(capsys, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["oracle-cli"])
    main()
    captured = capsys.readouterr()
    assert captured.out.startswith("usage: oracle-cli")
