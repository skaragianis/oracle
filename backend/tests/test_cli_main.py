from oracle.cli.main import main


def test_main_runs(capsys):
    main()
    captured = capsys.readouterr()
    assert captured.out == "oracle cli\n"
