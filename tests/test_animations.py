"""Explainer animations (--animations): placed on the final timeline, timing handed to the page,
overlaid in the MP4 and put on their own track in the draft."""
import json
import os
import subprocess

import pytest

from conftest import words
from jianjian.animations import load_animations, prepare_html
from jianjian.cuts import TimeMap, keep_ranges_from_cuts
from jianjian.util import ffmpeg_caps, find_ffmpeg

PAGE = """<!doctype html>
<html><head><meta charset="UTF-8" /><script src="gsap.min.js"></script></head>
<body><div id="root" data-composition-id="main" data-start="0" data-duration="10" data-width="1920">
<div class="clip" data-start="0" data-duration="auto"></div></div>
<script>gsap.timeline({paused: true});</script></body></html>"""


def tmap():
    return TimeMap(keep_ranges_from_cuts([(2.0, 4.0)], 20.0, 30))  # keeps 0-2 and 4-20


def write_spec(tmp_path, anims):
    for a in anims:
        (tmp_path / a["html"]).write_text(PAGE)
    p = tmp_path / "animations.json"
    p.write_text(json.dumps(anims))
    return str(p)


def test_times_follow_the_cuts_and_the_speed(tmp_path):
    spec = write_spec(tmp_path, [{"html": "a.html", "from": 5.0, "to": 8.0, "beats": {"x": 6.0}}])
    a, = load_animations(spec, tmap(), [], 30)
    assert (a["f0"], a["f1"], a["beats"]) == (90, 180, {"x": 1.0})  # 2 s cut before it
    a, = load_animations(spec, tmap(), [], 30, speed=2.0)
    assert (a["f0"], a["f1"], a["beats"]) == (45, 90, {"x": 0.5})


def test_words_are_local_and_cut_words_left_out(tmp_path):
    spec = write_spec(tmp_path, [{"html": "a.html", "from": 1.0, "to": 6.0}])
    ws = words(("hello", 1.0, 1.5), ("gone", 2.5, 3.0), ("world", 4.5, 5.0))
    a, = load_animations(spec, tmap(), ws, 30)
    assert a["words"] == [{"w": "hello", "t": 0.0, "end": 0.5}, {"w": "world", "t": 1.5, "end": 2.0}]


def test_one_animation_at_a_time_and_short_ones_dropped(tmp_path):
    spec = write_spec(tmp_path, [{"html": "b.html", "from": 9.0, "to": 12.0},
                                 {"html": "a.html", "from": 5.0, "to": 10.0},
                                 {"html": "c.html", "from": 15.0, "to": 15.5}])
    got = load_animations(spec, tmap(), [], 30)
    assert [(a["id"], a["f0"], a["f1"]) for a in got] == [("02_a", 90, 210), ("01_b", 210, 300)]


def test_missing_page_is_an_error(tmp_path):
    p = tmp_path / "animations.json"
    p.write_text(json.dumps([{"html": "nope.html", "from": 1, "to": 3}]))
    with pytest.raises(FileNotFoundError):
        load_animations(str(p), tmap(), [], 30)


def test_prepared_page_gets_the_placement():
    page = prepare_html(PAGE, {"duration": 3.5, "width": 1280, "height": 720, "beats": {"x": 1.0}})
    root = page[page.index('<div id="root"'):]
    root = root[:root.index(">")]
    assert 'data-duration="3.5"' in root and 'data-width="1280"' in root and 'data-height="720"' in root
    assert 'data-duration="auto"' not in page and page.count('data-duration="3.5"') == 2
    # defined before the page's own scripts run
    assert page.index("window.jianjian = ") < page.index("gsap.min.js")
    assert '"beats": {"x": 1.0}' in page


def test_page_without_a_root_is_refused():
    with pytest.raises(ValueError):
        prepare_html("<html><body><div></div></body></html>", {"duration": 1, "width": 1, "height": 1})


FF = find_ffmpeg()


@pytest.mark.skipif(not FF, reason="needs ffmpeg")
def test_render_overlays_the_animation_only_while_it_plays(tmp_path):
    from jianjian.media import probe
    from jianjian.render import render

    def run(*args):
        subprocess.run([FF, "-v", "error", "-y", *args], check=True)

    src, anim = str(tmp_path / "src.mp4"), str(tmp_path / "anim.mov")
    run("-f", "lavfi", "-i", "color=c=black:s=320x180:r=30:d=6", "-f", "lavfi", "-i", "sine=f=440:d=6",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", src)
    # a white box over the left half, transparent elsewhere
    run("-f", "lavfi", "-i", "color=c=white:s=320x180:r=30:d=1,format=rgba,"
        "geq=r=255:g=255:b=255:a='if(lt(X,160),255,0)'", "-c:v", "prores_ks", "-profile:v", "4444",
        "-pix_fmt", "yuva444p10le", anim)
    keeps = keep_ranges_from_cuts([(1.0, 2.0)], 6.0, 30)
    out = str(tmp_path / "out.mp4")
    render(src, out, keeps, probe(src), ffmpeg_caps(FF), fps=30, encoder="libx264", speed=1.0,
           animations=[(anim, 2.0)])

    def luma(t, x):
        raw = subprocess.run([FF, "-v", "error", "-ss", f"{t}", "-i", out, "-frames:v", "1", "-vf",
                              f"crop=8:8:{x}:86,format=gray", "-f", "rawvideo", "-"], capture_output=True).stdout
        return sum(raw) / len(raw)

    assert luma(1.5, 40) < 30                        # before: just the recording
    assert luma(2.5, 40) > 220 and luma(2.5, 260) < 30  # during: the box, and the frame shows through
    assert luma(3.5, 40) < 30                        # after: gone again
    assert abs(probe(out).duration - 5.0) < 0.1      # the overlay doesn't change the length


def test_draft_puts_animations_on_their_own_track_above_the_recording(tmp_path):
    from jianjian.draft import build_draft, summarize_draft
    from jianjian.media import MediaInfo
    from jianjian.validate import check_draft

    src, anim = tmp_path / "src.mp4", tmp_path / "anim.mov"
    src.write_bytes(b"")
    anim.write_bytes(b"")
    info = MediaInfo(str(src), 20.0, 1920, 1080, 30.0, True)
    keeps = keep_ranges_from_cuts([(2.0, 4.0)], 20.0, 30)
    staged = build_draft(str(tmp_path / "staging"), "t", info, str(src), keeps, [], 30, final_root="/x",
                         speed=1.5, animations=[(str(anim), MediaInfo(str(anim), 2.0, 1920, 1080, 30.0, False), 60, 120)])
    tracks = summarize_draft(staged)["tracks"]
    assert [(t["type"], t["name"]) for t in tracks][:2] == [("video", "main"), ("video", "animations")]
    assert tracks[1]["spans"][0][:4] == (2_000_000, 2_000_000, 0, 2_000_000)  # plays at normal speed
    chk = check_draft(staged, keeps, 30, str(src), speed=1.5, animations=[str(anim)])
    assert chk["ok"], chk["problems"]
