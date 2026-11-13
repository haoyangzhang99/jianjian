"""Assemble the source for a scripted solo talk: drop the takes the speaker deleted and swap in the
sentences they re-recorded. The result is a normal recording for `jianjian edit` (pauses, speed).

    .venv/bin/python tools/assemble_takes.py plan.json assembled.mov [--dry-run]

plan.json:
    {"source": "talk.mov",
     "ops": [
       {"drop": [43.1, 50.5], "note": "false start"},
       {"drop": [517.2, 520.3], "clip": "fix.mov", "say": [0.8, 3.4], "note": "re-recorded sentence"},
       {"cut": [966.985, 967.255], "note": "one extra word, between two dips"}
     ]}

`drop`: [about where the unwanted take starts, about where the next wanted words start]. The real cut
points are found on the level envelope: the first in the silence before the take (keeping at most
0.30 s of the pause), the second just before the next speech starts (keeping at most 0.22 s). With
`clip`, that file's sentence (`say`: about where it starts and ends) goes in at the same place,
levelled to the recording's speech. `cut` removes exactly that span (frame-snapped); use it for a
single word and only between two dips.

Word times from a transcript are good enough for `drop` (they are only a hint) and not for `cut`.
Always check the result word by word against what should remain (transcribe it with
tools/words_by_pause.py): a cut can leave half a word or take the neighbour with it. --dry-run prints
the plan table without encoding.
"""
import argparse
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _audio import HOP, SR, envelope, load_audio, offset_before, onset_after, quiet, speech_level, threshold  # noqa: E402

from jianjian.util import find_ffmpeg  # noqa: E402

TAIL, LEAD = 0.30, 0.22  # most silence kept after the last wanted word / before the next one


def drop_points(e, thr, a, b):
    """Envelope cut points for dropping [a, b): (cut_start, cut_end, previous speech end, next onset)."""
    if a <= 0.01:
        cs = prev_end = 0.0
    else:
        cs = quiet(e, a - 0.45, a + 0.06)
        prev_end = offset_before(e, cs, thr)
        cs = min(cs, prev_end + TAIL)
    on = onset_after(e, quiet(e, b - 0.5, b + 0.04), thr)
    ce = max(quiet(e, max(cs, on - 0.45), on), on - LEAD)
    return cs, ce, prev_end, on


def clip_span(e, say):
    """The sentence inside a re-recorded clip, with a little air on both sides."""
    thr = threshold(e)
    on = onset_after(e, quiet(e, max(0, say[0] - 0.6), say[0] + 0.05), thr)
    off = offset_before(e, quiet(e, say[1], say[1] + 0.6), thr)
    return max(0.0, on - LEAD), off + 0.28


def plan_segments(ops, e_main, duration, clip_envs, fps):
    """ops -> ([{"src", "s", "e", "gain_db"}], report rows). clip_envs: {path: envelope}."""
    thr = threshold(e_main)
    ref = speech_level(e_main)
    snap = lambda t: round(round(t * fps) / fps, 5)
    segs, rows, cur = [], [], 0.0
    for op in sorted(ops, key=lambda o: (o.get("drop") or o.get("cut"))[0]):
        note = op.get("note", "")
        if "cut" in op:
            cs, ce = op["cut"]
            rows.append(f"cut   {cs:8.2f}-{ce:8.2f} ({ce - cs:5.2f}s) exact  {note}")
        else:
            cs, ce, prev_end, on = drop_points(e_main, thr, *op["drop"])
            rows.append(f"drop  {cs:8.2f}-{ce:8.2f} ({ce - cs:5.1f}s) pause kept {cs - prev_end:.2f}+{on - ce:.2f}s  {note}")
        if cs < cur - 1e-6:
            raise SystemExit(f"operations overlap near {cs:.2f}s ({note})")
        if cs > cur:
            segs.append({"src": "source", "s": snap(cur), "e": snap(cs), "gain_db": 0.0})
        if op.get("clip"):
            ec = clip_envs[op["clip"]]
            s, e = clip_span(ec, op["say"])
            gain = round(ref - speech_level(ec), 1)
            segs.append({"src": op["clip"], "s": snap(s), "e": snap(e), "gain_db": gain})
            rows.append(f"      + {os.path.basename(op['clip'])} {s:.2f}-{e:.2f}, {gain:+.1f} dB")
        cur = ce
    segs.append({"src": "source", "s": snap(cur), "e": snap(duration), "gain_db": 0.0})
    return [s for s in segs if s["e"] - s["s"] > 0.5 / fps], rows


def source_fps(path):
    out = subprocess.run([find_ffmpeg(), "-hide_banner", "-i", path], capture_output=True, text=True).stderr
    m = re.search(r"([\d.]+) fps", out)
    return round(float(m.group(1))) if m else 30


def encode(segs, source, out, fps):
    """One ffmpeg run: each segment is its own seeked input, concatenated, re-encoded once (PCM sound)."""
    cmd, fc = [find_ffmpeg(), "-hide_banner", "-loglevel", "warning", "-stats", "-y"], []
    for i, s in enumerate(segs):
        d = s["e"] - s["s"]
        cmd += ["-ss", f"{s['s']:.5f}", "-t", f"{d:.5f}", "-i", source if s["src"] == "source" else s["src"]]
        fc.append(f"[{i}:v]setpts=PTS-STARTPTS,fps={fps},format=yuv420p[v{i}]")
        fc.append(f"[{i}:a]asetpts=PTS-STARTPTS,aresample=48000,volume={s['gain_db']}dB,afade=t=in:d=0.006,afade=t=out:st={d - 0.006:.5f}:d=0.006[a{i}]")
    fc.append("".join(f"[v{i}][a{i}]" for i in range(len(segs))) + f"concat=n={len(segs)}:v=1:a=1[v][a]")
    cmd += ["-filter_complex", ";".join(fc), "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "fast", "-crf", "14",
            "-g", str(fps), "-c:a", "pcm_s16le", out]
    subprocess.run(cmd, check=True)


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("plan"); p.add_argument("out"); p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    plan = json.load(open(a.plan, encoding="utf-8"))
    base = os.path.dirname(os.path.abspath(a.plan))
    full = lambda f: f if os.path.isabs(f) else os.path.join(base, f)
    source = full(plan["source"])
    for op in plan["ops"]:
        if op.get("clip"):
            op["clip"] = full(op["clip"])
    audio = load_audio(source)
    clip_envs = {op["clip"]: envelope(load_audio(op["clip"])) for op in plan["ops"] if op.get("clip")}
    fps = source_fps(source)
    segs, rows = plan_segments(plan["ops"], envelope(audio), len(audio) / SR, clip_envs, fps)
    print("\n".join(rows))
    print(f"{len(segs)} segments, {sum(s['e'] - s['s'] for s in segs):.2f}s of {len(audio) / SR:.2f}s, {fps} fps")
    json.dump(segs, open(os.path.splitext(a.out)[0] + ".segments.json", "w", encoding="utf-8"), indent=1)
    if not a.dry_run:
        encode(segs, source, a.out, fps)
        print("wrote", a.out)


if __name__ == "__main__":
    main()
