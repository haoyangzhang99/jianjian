"""Explainer animations over the talk (--animations), drawn in HTML and rendered with HyperFrames.

The pipeline doesn't decide *what* to animate; your coding agent (or you) writes animations.json
from the transcript, plus one HyperFrames HTML composition per animation:

    [{"html": "rag.html", "from": 125.4, "to": 133.0,
      "beats": {"retrieve": 126.8, "generate": 129.9}, "data": {"title": "RAG"}}]

`from`, `to` and `beats` are in SOURCE seconds (word times from work/transcript.json), like
cards, so an animation stays on the words it illustrates when pauses or fillers are cut, the edit
is sped up or a cold open moves things. jianjian maps them to the final timeline and puts them in
the page as `window.jianjian` before its scripts run:

    {duration, width, height, fps, beats: {name: seconds from the animation's start},
     words: [{w, t, end}], data}

so the GSAP timeline places each step on the word it belongs to. Each animation is rendered once
(cached) to a transparent ProRes 4444 MOV the size of the video, which goes on its own track above
the recording in the Jianying draft and is overlaid in the MP4. The talk plays on underneath.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from typing import List, Optional, Sequence

from .cuts import TimeMap
from .util import log, read_json, write_json

HYPERFRAMES = "hyperframes@0.8.183"  # pinned: a render must look the same next week
MIN_SECONDS = 1.0


def load_animations(path: str, tmap: TimeMap, words: Sequence[dict], fps: int, speed: float = 1.0) -> List[dict]:
    """Read animations.json and place each animation on the final timeline (frame grid).
    Returns [{id, html, f0, f1, beats, words, data}] sorted by position; f0/f1 are frames."""
    raw = read_json(path)
    base = os.path.dirname(os.path.abspath(path))
    end_f = int(round(tmap.edited_duration / speed * fps))

    def frame(t: float) -> int:  # source seconds -> frame on the final timeline
        return int(round(tmap.to_timeline(float(t)) / speed * fps))

    placed = []
    for i, a in enumerate(raw):
        if "html" not in a or "from" not in a or "to" not in a:
            raise ValueError(f"{path}: animation {i + 1} needs html, from and to")
        html = os.path.join(base, a["html"])
        if not os.path.isfile(html):
            raise FileNotFoundError(f"{path}: animation {i + 1}: {html} not found")
        f0, f1 = frame(a["from"]), min(frame(a["to"]), end_f)
        name = re.sub(r"[^\w-]+", "_", str(a.get("id") or os.path.splitext(os.path.basename(html))[0]))
        placed.append({"n": i + 1, "id": f"{i + 1:02d}_{name}", "html": html, "f0": f0, "f1": f1, "src": a})
    placed.sort(key=lambda p: p["f0"])
    out = []
    for p in placed:
        if out and p["f0"] < out[-1]["f1"]:  # one animation at a time: the earlier one ends first
            out[-1]["f1"] = p["f0"]
        out.append(p)
    res = []
    for p in out:
        if p["f1"] - p["f0"] < MIN_SECONDS * fps:
            log(f"animations: skipping {p['id']}: shorter than {MIN_SECONDS:.0f}s on the timeline")
            continue
        a, t0 = p["src"], p["f0"] / fps
        dur = (p["f1"] - p["f0"]) / fps

        def local(t: float) -> float:
            return round(min(max(tmap.to_timeline(float(t)) / speed - t0, 0.0), dur), 3)

        beats = {str(k): local(v) for k, v in (a.get("beats") or {}).items()}
        ws = [{"w": w["w"].strip(), "t": local(w["s"]), "end": local(w["e"])} for w in words
              if float(a["from"]) <= (w["s"] + w["e"]) / 2 < float(a["to"]) and _kept(tmap, (w["s"] + w["e"]) / 2)]
        res.append({"id": p["id"], "html": p["html"], "f0": p["f0"], "f1": p["f1"], "beats": beats,
                    "words": ws, "data": a.get("data", {})})
    return res


def _kept(tmap: TimeMap, t: float) -> bool:
    return any(k.src_start <= t < k.src_end for k in tmap.keeps)


def prepare_html(html: str, timing: dict) -> str:
    """The composition as rendered: the root's duration and size set to this placement, every
    data-duration="auto" set to the full length, and window.jianjian defined before any script."""
    dur = f"{timing['duration']:.3f}".rstrip("0").rstrip(".")

    def root(m: "re.Match") -> str:
        tag = m.group(0)
        for attr, val in (("data-duration", dur), ("data-width", timing["width"]),
                          ("data-height", timing["height"]), ("data-start", 0)):
            if re.search(rf"\s{attr}=", tag):
                tag = re.sub(rf'(\s{attr}=)("[^"]*"|\'[^\']*\')', rf'\g<1>"{val}"', tag)
            else:
                tag = tag[:-1] + f' {attr}="{val}">'
        return tag

    out, n = re.subn(r"<[a-zA-Z][^>]*\sdata-composition-id=[^>]*>", root, html, count=1)
    if not n:
        raise ValueError("no element with data-composition-id (the HyperFrames root)")
    out = re.sub(r'data-duration=(["\'])auto\1', f'data-duration="{dur}"', out)
    script = f"<script>window.jianjian = {json.dumps(timing, ensure_ascii=False)};</script>"
    m = re.search(r"<head[^>]*>", out, re.I) or re.search(r"<html[^>]*>", out, re.I)
    return out[:m.end()] + "\n" + script + out[m.end():] if m else script + "\n" + out


def find_npx() -> Optional[str]:
    return shutil.which("npx")


def render_animation(anim: dict, out: str, work: str, width: int, height: int, fps: int, npx: str) -> str:
    """Render one animation to <out>/animations/<id>_<hash>.mov (reused when nothing changed). The
    draft uses that file, so it lives next to the outputs; the page as rendered goes in work/animations."""
    timing = {"duration": round((anim["f1"] - anim["f0"]) / fps, 3), "width": width, "height": height,
              "fps": fps, "beats": anim["beats"], "words": anim["words"], "data": anim["data"]}
    with open(anim["html"], encoding="utf-8") as f:
        page = prepare_html(f.read(), timing)
    assets = os.path.join(os.path.dirname(anim["html"]), "assets")
    h = hashlib.sha256((HYPERFRAMES + page).encode())
    if os.path.isdir(assets):
        for dp, _dn, fn in sorted(os.walk(assets)):
            for x in sorted(fn):
                st = os.stat(os.path.join(dp, x))
                h.update(f"{os.path.relpath(os.path.join(dp, x), assets)}:{st.st_size}:{int(st.st_mtime)}".encode())
    key = h.hexdigest()
    # the name carries the key: a changed page gets a new file, and a draft made earlier keeps the
    # clip it was made with (overwriting it would change that draft behind Jianying's back)
    name = f"{anim['id']}_{key[:10]}"
    proj, mov = os.path.join(work, "animations", name), os.path.join(out, "animations", name + ".mov")
    side = mov + ".json"
    if os.path.exists(mov) and os.path.exists(side) and read_json(side).get("key") == key:
        log(f"animation: reusing {name}.mov")
        return mov
    if os.path.isdir(proj):
        shutil.rmtree(proj)
    os.makedirs(proj)
    os.makedirs(os.path.dirname(mov), exist_ok=True)
    with open(os.path.join(proj, "index.html"), "w", encoding="utf-8") as f:
        f.write(page)
    if os.path.isdir(assets):
        shutil.copytree(assets, os.path.join(proj, "assets"))
    env = dict(os.environ, HYPERFRAMES_NO_TELEMETRY="1", DO_NOT_TRACK="1")
    log(f"animation: rendering {anim['id']} ({timing['duration']:.1f}s) with {HYPERFRAMES} ...")
    proc = subprocess.run([npx, "--yes", HYPERFRAMES, "render", proj, "--format", "mov", "--fps", str(fps),
                           "-o", mov, "--strict"], capture_output=True, text=True, env=env)
    if proc.returncode != 0 or not os.path.exists(mov):
        # not --quiet: it hides the lint findings that explain a refused render
        lines = re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", (proc.stdout or "") + (proc.stderr or "")).splitlines()
        tail = "\n".join(x for x in lines if x.strip() and not x.startswith(("[initSession", "[static-dedup")))[-3000:]
        raise RuntimeError(f"HyperFrames failed on {anim['html']} ({proc.returncode}):\n{tail}")
    write_json(side, {"key": key, "html": anim["html"], "timing": timing})
    return mov
