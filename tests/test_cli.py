import pytest

from jianjian.cli import _write_report_md, main


def test_edit_refuses_to_run_without_a_preset(tmp_path, capsys):
    with pytest.raises(SystemExit):
        main(["edit", str(tmp_path / "video.mp4"), "--out", str(tmp_path / "out")])
    assert not (tmp_path / "out").exists()


def test_presets_command_lists_every_preset(capsys):
    assert main(["presets"]) == 0
    out = capsys.readouterr().out
    for name in ("shorts", "youtube", "conversation", "podcast", "interview"):
        assert name in out


def test_report_says_no_cuts_for_no_cut(tmp_path):
    p = tmp_path / "report.md"
    _write_report_md(str(p), {"input": "v.mp4", "media": {"duration": 120.0},
                              "cuts": {"preset": "no cuts", "settings": {"max_pause": 0.9, "keep_pause": 0.45},
                                       "num_cuts": 0, "edited_duration": 120.0}})
    text = p.read_text()
    assert "Pause preset: no cuts" in text and "max_pause" not in text and "custom" not in text
