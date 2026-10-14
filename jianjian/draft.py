"""Write a NEW, editable Jianying Pro draft (macOS layout) using the vendored pyJianYingDraft.

Jianying 6+ encrypts drafts it saves, so we never read or modify existing drafts. We generate a
fresh plaintext draft; Jianying opens it and upgrades it in place.

Layout written (macOS): <drafts_root>/<name>/{draft_info.json, draft_content.json,
draft_meta_info.json}. The draft is first built in a staging folder inside the job's output
directory, validated, and only then copied into Jianying's drafts folder (never overwriting).
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import time
import types
import uuid
from typing import List, Sequence

from .cuts import KeepRange
from .media import MediaInfo
from .subs import Cue
from .util import log, read_json, write_json

VENDOR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vendor")

DEFAULT_DRAFT_ROOTS = [
    "~/Movies/JianyingPro/User Data/Projects/com.lveditor.draft",
    "~/Movies/CapCut/User Data/Projects/com.lveditor.draft",
]


def _import_pyjy():
    if VENDOR not in sys.path:
        sys.path.insert(0, VENDOR)
    try:
        import pymediainfo  # noqa: F401
    except ImportError:  # we never let the library probe media itself
        stub = types.ModuleType("pymediainfo")
        stub.MediaInfo = type("MediaInfo", (), {"can_parse": staticmethod(lambda: False)})
        sys.modules["pymediainfo"] = stub
    import pyJianYingDraft as jy
    return jy


def find_drafts_root(explicit: str = "") -> str:
    for p in ([explicit] if explicit else []) + DEFAULT_DRAFT_ROOTS:
        p = os.path.expanduser(p)
        if os.path.isdir(p):
            return p
    raise FileNotFoundError("Jianying drafts folder not found; pass --drafts-root")


def _video_material(jy, info: MediaInfo, media_path: str):
    m = object.__new__(jy.VideoMaterial)
    m.material_name = os.path.basename(media_path)
    m.material_id = uuid.uuid4().hex
    m.path = media_path
    m.crop_settings = jy.CropSettings()
    m.local_material_id = ""
    m.material_type = "video"
    m.duration = int(round(info.duration * 1_000_000))
    m.width, m.height = info.width, info.height
    return m


LINE_STYLES = {  # per-language line style inside a subtitle box
    "zh": dict(size=7.0, color=(1.0, 1.0, 1.0)),
    "en": dict(size=5.0, color=(0.9, 0.9, 0.9)),
}
SUBTITLE_Y = -0.74  # centre of the subtitle box (-1 = bottom edge of the frame)
FADE_US = 10_000    # audio fade at every cut, in microseconds


def _subtitle_segment(jy, lines, timerange):
    """One text box with one line per language, e.g. [("你好", zh_style), ("Hello", en_style)]."""
    text = "\n".join(t for t, _ in lines)
    first = lines[0][1]
    seg = jy.TextSegment(
        text, timerange,
        style=jy.TextStyle(size=first["size"], color=first["color"], align=1, auto_wrapping=True,
                           max_line_width=0.86),
        clip_settings=jy.ClipSettings(transform_y=SUBTITLE_Y),
        border=jy.TextBorder(color=(0.0, 0.0, 0.0), width=40.0),
    )
    if len(lines) == 1:
        return seg
    export = seg.export_material

    def export_material():
        # pyJianYingDraft writes one style for the whole text; split it into one range per line.
        # Ranges count UTF-16 units, like Jianying (the same as len() for Chinese and English).
        mat = export()
        content = json.loads(mat["content"])
        base = content["styles"][0]
        styles, pos = [], 0
        for i, (t, st) in enumerate(lines):
            n = len(t.encode("utf-16-le")) // 2 + (1 if i < len(lines) - 1 else 0)  # + the "\n"
            s = copy.deepcopy(base)
            s["range"] = [pos, pos + n]
            s["size"] = st["size"]
            s["fill"]["content"]["solid"]["color"] = list(st["color"])
            styles.append(s)
            pos += n
        content["styles"] = styles
        mat["content"] = json.dumps(content, ensure_ascii=False)
        return mat

    seg.export_material = export_material
    return seg


def build_draft(staging_root: str, name: str, info: MediaInfo, media_path: str,
                keeps: Sequence[KeepRange], cues: Sequence[Cue], fps: int,
                final_root: str, tracks=("zh", "en"), cards: Sequence[dict] = (), speed: float = 1.0) -> str:
    """Build the draft in staging_root/name. media_path is the absolute path Jianying will use."""
    jy = _import_pyjy()
    os.makedirs(staging_root, exist_ok=True)
    folder = jy.DraftFolder(staging_root)
    script = folder.create_draft(name, info.width, info.height, fps=fps, allow_replace=True)
    draft_dir = os.path.join(staging_root, name)

    specs = [jy.TrackSpec(jy.TrackType.video, "main")]
    names = {"zh": "字幕-中文", "en": "subtitles-en"}
    tracks = [t for t in tracks if any((c.zh if t == "zh" else c.en) for c in cues)]
    if tracks:
        specs.append(jy.TrackSpec(jy.TrackType.text, names[tracks[0]] if len(tracks) == 1 else "字幕-双语"))
    if cards:
        specs.append(jy.TrackSpec(jy.TrackType.text, "cards"))
    script.append_tracks(specs)

    def us(frames: int) -> int:
        return int(round(frames * 1_000_000 / fps))

    def tus(frames: int) -> int:  # position on the final (sped-up) timeline
        return int(round(frames * 1_000_000 / fps / speed))

    mat = _video_material(jy, info, media_path)
    script.add_material(mat)
    tl_f = 0
    for i, k in enumerate(keeps):
        fa, fb = int(round(k.src_start * fps)), int(round(k.src_end * fps))
        n = fb - fa
        if n <= 0:
            continue
        src = jy.Timerange(us(fa), min(us(tl_f + n) - us(tl_f), mat.duration - us(fa)))
        # with --speed the clip is shorter on the timeline than in the source; pyJianYingDraft sets the
        # clip speed from the two lengths, and change_pitch stays off (voices keep their pitch)
        seg = jy.VideoSegment(mat, jy.Timerange(tus(tl_f), tus(tl_f + n) - tus(tl_f)), source_timerange=src)
        # a 10-ms audio fade at each join, so cuts inside speech (removed fillers) don't click
        seg.add_fade(FADE_US if i > 0 else 0, FADE_US if i < len(keeps) - 1 else 0)
        script.add_segment(seg, "main")
        tl_f += n
    total_us = tus(tl_f)

    # Both languages share one text box per cue (first language on top, larger), each line with its
    # own size and colour. Two tracks pinned at fixed heights overlapped whenever a line wrapped,
    # because Jianying grows a box both up and down from its centre; inside one box Jianying lays
    # the lines out itself.
    sub_track = names[tracks[0]] if len(tracks) == 1 else "字幕-双语"
    last_end = 0
    for c in cues:
        lines = [(c.zh if t == "zh" else c.en, LINE_STYLES[t]) for t in tracks]
        lines = [(txt, st) for txt, st in lines if txt]
        if not lines:
            continue
        a = max(int(round(c.tl_start * 1_000_000)), last_end)
        b = min(int(round(c.tl_end * 1_000_000)), total_us)
        if b - a < 100_000:
            continue
        script.add_segment(_subtitle_segment(jy, lines, jy.Timerange(a, b - a)), sub_track)
        last_end = b
    for c in cards:
        a, b = int(round(c["tl_start"] * 1_000_000)), int(round(c["tl_end"] * 1_000_000))
        body = c["title"] + ("\n" + c["text"] if c["text"] else "")
        seg = jy.TextSegment(
            body, jy.Timerange(a, min(b, total_us) - a),
            style=jy.TextStyle(size=4.5, align=0, auto_wrapping=True, max_line_width=0.38, line_spacing=2),
            clip_settings=jy.ClipSettings(transform_x=0.5, transform_y=0.62),
            background=jy.TextBackground(color="#000000", alpha=0.6, round_radius=0.15,
                                         height=0.4, width=0.25),
        )
        script.add_segment(seg, "cards")
    script.save()  # -> draft_content.json

    # macOS Jianying reads draft_info.json; keep draft_content.json too for older builds/tools.
    content_path = os.path.join(draft_dir, "draft_content.json")
    content = read_json(content_path)
    now_s = int(time.time())
    for key in ("platform", "last_modified_platform"):
        if isinstance(content.get(key), dict):
            content[key]["os"] = "mac"
    content["create_time"] = now_s
    content["update_time"] = now_s
    content["name"] = name
    content["id"] = str(uuid.uuid4()).upper()
    write_json(content_path, content)
    shutil.copyfile(content_path, os.path.join(draft_dir, "draft_info.json"))

    meta_path = os.path.join(draft_dir, "draft_meta_info.json")
    meta = read_json(meta_path)
    now_us = int(time.time() * 1_000_000)
    meta.update({
        "draft_id": str(uuid.uuid4()).upper(),
        "draft_name": name,
        "draft_fold_path": os.path.join(final_root, name),
        "draft_root_path": final_root,
        "tm_duration": total_us,
        "tm_draft_create": now_us,
        "tm_draft_modified": now_us,
    })
    write_json(meta_path, meta)
    log(f"draft built: {len(keeps)} video segments, {sum(1 for c in cues if c.zh)} zh / "
        f"{sum(1 for c in cues if c.en)} en subtitle segments, {total_us / 1e6:.1f}s")
    return draft_dir


def install_draft(staged_dir: str, drafts_root: str) -> str:
    name = os.path.basename(staged_dir.rstrip("/"))
    dest = os.path.join(drafts_root, name)
    if os.path.exists(dest):
        raise FileExistsError(f"a draft named {name!r} already exists; refusing to overwrite")
    shutil.copytree(staged_dir, dest)
    log(f"draft installed: {dest}")
    return dest


def summarize_draft(draft_dir: str) -> dict:
    """Re-read a generated draft and return structural facts used by validation."""
    d = read_json(os.path.join(draft_dir, "draft_info.json"))
    vids = {m["id"]: m for m in d["materials"].get("videos", [])}
    out = {"duration_us": d.get("duration"), "fps": d.get("fps"), "canvas": d.get("canvas_config"),
           "tracks": []}
    for tr in d["tracks"]:
        segs = tr["segments"]
        out["tracks"].append({
            "type": tr["type"], "name": tr.get("name"), "segments": len(segs),
            "spans": [(s["target_timerange"]["start"], s["target_timerange"]["duration"],
                       (s.get("source_timerange") or {}).get("start"),
                       (s.get("source_timerange") or {}).get("duration"),
                       s.get("material_id")) for s in segs],
        })
    out["video_materials"] = [{"path": m.get("path"), "duration": m.get("duration")} for m in vids.values()]
    return out
