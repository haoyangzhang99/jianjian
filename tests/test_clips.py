"""jianjian clips: clip specs, edges moved into pauses, and a real cut of a generated video."""
import json
import shutil
import subprocess

import numpy as np
import pytest

from jianjian.clips import SR, parse_spec, plan, snap


def test_parse_spec():
    assert parse_spec("big question=12:03.5-13:10") == ("big-question", [(723.5, 790.0)])
    assert parse_spec("story=4:10-4:31.5,4:41-5:20")[1] == [(250.0, 271.5), (281.0, 320.0)]
    assert parse_spec("long=1:05:00-1:06:00")[1] == [(3900.0, 3960.0)]
    for bad in ("no-equals", "x=10", "x=20-10", "x=0-30,20-40"):
        with pytest.raises(ValueError):
            parse_spec(bad)


def speechy(seconds=10.0, quiet=((2.0, 2.4), (6.5, 7.0))):
    """Loud noise with a few quiet gaps (the pauses between sentences)."""
    rng = np.random.default_rng(0)
    a = (0.3 * rng.standard_normal(int(seconds * SR))).astype(np.float32)
    for s, e in quiet:
        a[int(s * SR):int(e * SR)] *= 0.001
    return a


def test_edges_move_into_the_nearest_pause():
    a = speechy()
    t = snap(a, 2.5, fps=30, window=0.25)
    assert 2.0 < t < 2.4 and abs(t * 30 - round(t * 30)) < 1e-9  # in the gap, on the frame grid
    assert plan([(0.0, 6.6)], a, duration=10.0) [0][0] == 0.0  # the start of the video stays put
    s, e = plan([(2.3, 6.8)], a, duration=10.0)[0]
    assert 2.0 < s < 2.4 and 6.5 < e < 7.0


def test_cut_a_generated_video(tmp_path):
    pytest.importorskip("faster_whisper")
    from jianjian.util import ffmpeg_caps, find_ffmpeg
    ff = find_ffmpeg()
    if not ff or not shutil.which("ffprobe"):
        pytest.skip("no ffmpeg")
    src = tmp_path / "talk.mp4"
    subprocess.run([ff, "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=30:duration=12",
                    "-f", "lavfi", "-i", "sine=frequency=300:duration=12", "-af", "volume=enable='between(t,4,5)':volume=0",
                    "-c:v", "libx264" if ffmpeg_caps(ff).get("libx264") else "mpeg4", "-c:a", "aac", "-shortest", str(src)],
                   check=True)
    from jianjian.cli import main
    out = tmp_path / "clips"
    assert main(["clips", str(src), "first=0-4.2", "joined=1-3,6-8", "--out", str(out), "--prefix", "ep01_"]) == 0
    p = json.loads((out / "plan.json").read_text())
    names = [c["file"] for c in p["clips"]]
    assert names == ["ep01_1_first.mp4", "ep01_2_joined.mp4"]
    first, joined = p["clips"]
    assert 4.0 <= first["spans"][0][1] <= 4.45  # moved into the silent second
    assert abs(joined["seconds"] - sum(b - a for a, b in joined["spans"])) < 0.15  # both pieces, joined
    assert all(abs(x - y) <= 0.25 + 1e-6 for s, r in zip(joined["spans"], joined["requested"]) for x, y in zip(s, r))
    assert all(c["ok"] for c in p["clips"])
