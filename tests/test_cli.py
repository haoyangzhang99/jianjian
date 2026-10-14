import pytest

from jianjian.cli import main


def test_edit_refuses_to_run_without_a_preset(tmp_path, capsys):
    with pytest.raises(SystemExit):
        main(["edit", str(tmp_path / "video.mp4"), "--out", str(tmp_path / "out")])
    assert not (tmp_path / "out").exists()


def test_presets_command_lists_every_preset(capsys):
    assert main(["presets"]) == 0
    out = capsys.readouterr().out
    for name in ("shorts", "youtube", "conversation", "podcast", "interview"):
        assert name in out
