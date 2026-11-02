"""Kdenlive projects (the default editor project): the timeline matches the keep ranges, nothing is
overwritten, and MLT (Kdenlive's own renderer) plays it in sync."""
import subprocess

import numpy as np
import pytest

from jianjian import kdenlive as kd
from jianjian.cli import _pick_editor
from jianjian.cuts import apply_inserts, keep_ranges_from_cuts
from jianjian.media import MediaInfo
from jianjian.validate import check_project
from jianjian.util import find_ffmpeg

FF = find_ffmpeg()
MELT = kd.find_melt()


def build(tmp_path, keeps, speed=1.0, inserts=(), animations=(), ass=""):
    src = tmp_path / "src.mp4"
    src.write_bytes(b"")
    info = MediaInfo(str(src), 20.0, 1920, 1080, 30.0, True)
    return kd.build_project(str(tmp_path), "t", info, str(src), keeps, 30, ass_path=ass, speed=speed,
                            inserts=inserts, animations=animations)


@pytest.mark.parametrize("speed", [1.0, 1.05, 1.5])
def test_one_picture_and_one_sound_clip_per_keep_range(tmp_path, speed):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"")
    keeps = apply_inserts(keep_ranges_from_cuts([(2.0, 4.0), (7.3, 9.1)], 20.0, 30), [(5.0, 3.0)], 30)
    p = build(tmp_path, keeps, speed, inserts=[(str(clip), MediaInfo(str(clip), 3.0, 1920, 1080, 30.0, True))])
    a1, v1, v2 = kd.summarize_project(p)["tracks"]
    assert len(v1["spans"]) == len(a1["spans"]) == len(keeps) == 5  # the clip splits a keep range
    assert [s[:3] for s in a1["spans"]] == [s[:3] for s in v1["spans"]]  # sound under its picture
    assert sum(1 for s in v1["spans"] if s[3] == str(clip)) == 1
    pos = 0
    for start, n, *_ in v1["spans"]:  # no gaps, no overlaps
        assert start == pos
        pos += n
    assert check_project(p, keeps, 30, speed=speed)["ok"]


def test_speed_rounding_does_not_add_up(tmp_path):
    keeps = keep_ranges_from_cuts([(i + 0.5, i + 0.9) for i in range(0, 19, 1)], 20.0, 30)
    p = build(tmp_path, keeps, speed=1.07)
    s = kd.summarize_project(p)
    total = round(sum(round(k.src_end * 30) - round(k.src_start * 30) for k in keeps) / 1.07)
    assert s["duration_frames"] == s["tracks"][1]["end"] == total


def test_animations_go_on_v2_and_subtitles_next_to_the_project(tmp_path):
    anim, ass = tmp_path / "anim.mov", tmp_path / "subs.ass"
    anim.write_bytes(b"")
    ass.write_text("[Script Info]\n")
    keeps = keep_ranges_from_cuts([(2.0, 4.0)], 20.0, 30)
    p = build(tmp_path, keeps, animations=[(str(anim), MediaInfo(str(anim), 2.0, 1920, 1080, 30.0, False), 60, 120)],
              ass=str(ass))
    s = kd.summarize_project(p)
    assert s["tracks"][2]["spans"] == [(60, 60, 0, str(anim))]
    assert s["subtitles"] == [p + ".ass"] and open(p + ".ass").read() == "[Script Info]\n"
    chk = check_project(p, keeps, 30, animations=1, subtitles=True)
    assert chk["ok"], chk["problems"]
    assert not check_project(p, keeps[:1], 30, animations=1, subtitles=True)["ok"]


def test_never_overwrites_a_project(tmp_path):
    keeps = keep_ranges_from_cuts([], 20.0, 30)
    build(tmp_path, keeps)
    assert kd.free_name(str(tmp_path), "t") == "t_2"
    with pytest.raises(FileExistsError):
        build(tmp_path, keeps)


def test_crash_warning_only_for_new_kdenlive_on_macos_27():
    assert kd.crash_warning("26.08.2", "27.2")
    assert kd.crash_warning("26.04", "27.0")
    assert not kd.crash_warning("25.12", "27.2")
    assert not kd.crash_warning("26.08.2", "26.3")
    assert not kd.crash_warning("", "27.2")


def test_auto_falls_back_to_jianying_only_when_kdenlive_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(kd, "find_app", lambda *a: "")
    assert _pick_editor("auto", str(tmp_path)) == "jianying"   # Jianying's drafts folder exists
    assert _pick_editor("auto", str(tmp_path / "nope")) in ("kdenlive", "jianying")
    assert _pick_editor("kdenlive", str(tmp_path)) == "kdenlive"
    monkeypatch.setattr(kd, "find_app", lambda *a: "/Applications/kdenlive.app")
    assert _pick_editor("auto", str(tmp_path)) == "kdenlive"
    assert _pick_editor("jianying", str(tmp_path)) == "jianying"


@pytest.mark.skipif(not (FF and MELT), reason="needs ffmpeg and melt (Kdenlive)")
def test_melt_plays_the_cuts_in_sync(tmp_path):
    from faster_whisper import decode_audio

    from jianjian.media import probe

    src = str(tmp_path / "src.mp4")
    # bursts of a tone, so a misplaced cut shows up in the sound
    subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=320x180:r=30:d=6", "-f", "lavfi",
                    "-i", "aevalsrc='0.5*sin(2*PI*330*t)*gt(sin(2*PI*1.3*t),0)':s=48000:d=6", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", src], check=True)
    keeps = keep_ranges_from_cuts([(1.0, 2.5)], 6.0, 30)
    p = kd.build_project(str(tmp_path), "t", probe(src), src, keeps, 30)
    out = str(tmp_path / "out.mp4")
    subprocess.run([MELT, "-quiet", p, "-consumer", f"avformat:{out}", "vcodec=libx264", "acodec=aac", "ar=48000"],
                   check=True, timeout=120)
    assert abs(probe(out).duration - 4.5) < 0.1
    a, b = decode_audio(src, sampling_rate=16000), decode_audio(out, sampling_rate=16000)
    # 1 s after the cut: the output plays source time 3.5 s
    i, j, n = int(3.5 * 16000), int(2.0 * 16000), 8000
    lags = range(-800, 801, 10)
    corr = [float(np.dot(a[i:i + n], b[j + d:j + d + n])) for d in lags]
    assert abs(lags[int(np.argmax(corr))]) <= 160  # within 10 ms
