"""Write a NEW, editable Kdenlive project (MLT XML, Kdenlive document version 1.1).

The project sits in the job's output folder as <name>.kdenlive, with its subtitles next to it in
<name>.kdenlive.ass, the file name Kdenlive itself uses for a project's subtitle track. We never
overwrite a project: the user may have edited it in Kdenlive.

Timeline (MLT tracks, bottom to top): A1 = the sound of every kept range, V1 = its picture (each
pair grouped, so they move together), V2 = the transparent explainer animations. Each kept range
is one clip; with --speed the clips are timewarp producers with the pitch kept. The bilingual
subtitles (and cards, on a second subtitle layer) are the same .ass file the MP4 burns in.
"""
from __future__ import annotations

import json
import os
import shutil
import uuid
import xml.etree.ElementTree as ET
from typing import List, Sequence, Tuple

from .cuts import KeepRange
from .media import MediaInfo
from .util import log

DOC_VERSION = "1.1"
KDENLIVE_VERSION = "25.12.2"  # the version the generated projects were opened in
FADE_FRAMES = 1  # audio fade-out at every join, so cuts inside speech (removed fillers) don't click
FOLDER_ID, SEQUENCE_ID, FIRST_CLIP_ID = 2, 3, 4  # Kdenlive ids: folders and clips share one space
DEFAULT_APP = "/Applications/kdenlive.app"


def find_app(explicit: str = "") -> str:
    """The Kdenlive app (or binary) if installed, else ""."""
    for p in ([explicit] if explicit else []) + [DEFAULT_APP, os.path.expanduser("~" + DEFAULT_APP)]:
        if p and os.path.exists(p):
            return p
    return shutil.which("kdenlive") or ""


def app_version(app: str) -> str:
    """"25.12" / "26.08.2" from a Kdenlive.app bundle, else ""."""
    try:
        import plistlib
        with open(os.path.join(app, "Contents", "Info.plist"), "rb") as f:
            d = plistlib.load(f)
        return d.get("CFBundleVersion") or d.get("CFBundleShortVersionString") or ""
    except (OSError, ValueError):
        return ""


def crash_warning(version: str, macos: str) -> str:
    """Kdenlive 26.04 and later (Qt 6.11) crash at startup on macOS 27 (in Qt's cursor code)."""
    try:
        kd = tuple(int(x) for x in version.split(".")[:2])
        mac = int(macos.split(".")[0])
    except ValueError:
        return ""
    if mac >= 27 and kd >= (26, 4):
        return (f"Kdenlive {version} crashes at startup on macOS {macos}; install Kdenlive 25.12.2 from "
                "https://download.kde.org/Attic/kdenlive/25.12/macOS/ (README → Pitfalls)")
    return ""


def find_melt(app: str = "") -> str:
    """MLT's command-line player/renderer: the copy inside Kdenlive.app, else one on the PATH."""
    app = app or find_app()
    inner = os.path.join(app, "Contents", "MacOS", "melt") if app.endswith(".app") else ""
    return inner if inner and os.path.exists(inner) else (shutil.which("melt") or "")


def clip_frames(tl_f: int, n: int, fa: int, speed: float) -> Tuple[int, int, int]:
    """(timeline position, length, in point) of a kept range of n frames that starts at source
    frame fa and at frame tl_f of the edit before --speed. With --speed the clip is a timewarp
    producer, whose frames are source frames / speed."""
    pos = int(round(tl_f / speed))
    length = int(round((tl_f + n) / speed)) - pos
    return pos, length, (int(round(fa / speed)) if speed != 1.0 else fa)


def free_name(out_dir: str, name: str) -> str:
    base, n = name, 2
    while os.path.exists(os.path.join(out_dir, name + ".kdenlive")):
        name, n = f"{base}_{n}", n + 1
    return name


def _props(el: ET.Element, props) -> ET.Element:
    for k, v in props:
        p = ET.SubElement(el, "property", name=k)
        if v is not None and v != "":
            p.text = str(v)
    return el


def _builtin_filters(el: ET.Element, audio: bool) -> None:
    """The disabled volume / pan (/ level meter) filters Kdenlive puts on tracks and the sequence."""
    for props in ([("window", 75), ("max_gain", "20dB"), ("mlt_service", "volume")],
                  [("channel", -1), ("mlt_service", "panner"), ("start", 0.5)]):
        _props(ET.SubElement(el, "filter"), props + [("internal_added", 237), ("disable", 1)])
    if audio:
        _props(ET.SubElement(el, "filter"), [("iec_scale", 0), ("mlt_service", "audiolevel"), ("dbpeak", 1),
                                             ("disable", 1)])


def _track_tractor(root: ET.Element, tid: str, name: str, audio: bool, entries_pl: ET.Element) -> None:
    second = ET.SubElement(root, "playlist", id=tid + "_b")  # Kdenlive tracks have two playlists
    if audio:
        _props(entries_pl, [("kdenlive:audio_track", 1)])
        _props(second, [("kdenlive:audio_track", 1)])
    tr = ET.SubElement(root, "tractor", id=tid)
    _props(tr, ([("kdenlive:audio_track", 1)] if audio else []) +
           [("kdenlive:track_name", name), ("kdenlive:trackheight", 67), ("kdenlive:timeline_active", 1),
            ("kdenlive:collapsed", 0), ("kdenlive:thumbs_format", ""), ("kdenlive:audio_rec", "")])
    hide = "video" if audio else "audio"
    ET.SubElement(tr, "track", hide=hide, producer=entries_pl.get("id"))
    ET.SubElement(tr, "track", hide=hide, producer=second.get("id"))
    _builtin_filters(tr, audio)


def build_project(out_dir: str, name: str, info: MediaInfo, media_path: str, keeps: Sequence[KeepRange],
                  fps: int, ass_path: str = "", speed: float = 1.0,
                  inserts: Sequence[Tuple[str, MediaInfo]] = (),
                  animations: Sequence[Tuple[str, MediaInfo, int, int]] = ()) -> str:
    """Write out_dir/name.kdenlive (and name.kdenlive.ass from ass_path) and return its path.
    inserts: (path, MediaInfo) of the clips keep ranges with media 1, 2, ... play; animations:
    (path, MediaInfo, first and end frame on the final timeline) of the transparent clips."""
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, name + ".kdenlive")
    if os.path.exists(path):
        raise FileExistsError(f"a project named {name!r} already exists; refusing to overwrite")
    doc_uuid = "{%s}" % uuid.uuid4()
    root = ET.Element("mlt", LC_NUMERIC="C", producer="main_bin", version="7.36.0", root=out_dir)
    ET.SubElement(root, "profile", description=f"{info.width}x{info.height} {fps}fps", width=str(info.width),
                  height=str(info.height), progressive="1", sample_aspect_num="1", sample_aspect_den="1",
                  display_aspect_num=str(info.width), display_aspect_den=str(info.height),
                  frame_rate_num=str(fps), frame_rate_den="1", colorspace="709")

    def frames(seconds: float) -> int:
        return int(round(seconds * fps))

    # media: the recording, the inserted clips, the animations; each a bin clip plus the copies
    # Kdenlive keeps per track type (set.test_image=1: sound only, set.test_audio=1: picture only)
    media = [(media_path, info, True)] + [(p, m, True) for p, m in inserts] + [(p, m, False) for p, m, *_ in animations]
    ids = {}

    def chain(cid: str, p: str, m: MediaInfo, kid: int, extra=()):
        ch = ET.SubElement(root, "chain", id=cid, out=str(max(frames(m.duration) - 1, 0)))
        _props(ch, [("length", frames(m.duration)), ("eof", "pause"), ("resource", p),
                    ("mlt_service", "avformat-novalidate"), ("seekable", 1),
                    ("kdenlive:clipname", os.path.basename(p)), ("kdenlive:clip_type", 3 if m.has_audio else 2),
                    ("kdenlive:folderid", -1), ("kdenlive:id", kid), ("mute_on_pause", 0)] + list(extra))
        return cid

    def timewarp(cid: str, p: str, m: MediaInfo, kid: int, extra=()):
        # warp_pitch stays 0: MLT keeps the pitch with Rubber Band, which delays the sound by about
        # 110 ms and doesn't compensate (tested with melt 7.43). Voices are ~0.8 semitone higher at 1.05x.
        n = int(frames(m.duration) / speed)
        pr = ET.SubElement(root, "producer", id=cid, out=str(max(n - 1, 0)))
        _props(pr, [("length", n), ("eof", "pause"), ("resource", f"{speed:g}:{p}"), ("mlt_service", "timewarp"),
                    ("warp_speed", f"{speed:g}"), ("warp_resource", p), ("warp_pitch", 0), ("seekable", 1),
                    ("kdenlive:clipname", os.path.basename(p)), ("kdenlive:clip_type", 3 if m.has_audio else 2),
                    ("kdenlive:folderid", -1), ("kdenlive:id", kid)] + list(extra))
        return cid

    for i, (p, m, sped) in enumerate(media):
        kid = FIRST_CLIP_ID + i
        make = timewarp if sped and speed != 1.0 else chain
        ids[i] = {"kid": kid, "bin": chain(f"chain{i}", p, m, kid),
                  "video": make(f"clip{i}_video", p, m, kid, [("set.test_audio", 1), ("set.test_image", 0)])}
        if m.has_audio:
            ids[i]["audio"] = make(f"clip{i}_audio", p, m, kid, [("set.test_audio", 0), ("set.test_image", 1)])
    black = ET.SubElement(root, "producer", id="black_track", out="2147483646")
    _props(black, [("length", 2147483647), ("eof", "continue"), ("resource", "black"), ("aspect_ratio", 1),
                   ("mlt_service", "color"), ("kdenlive:playlistid", "black_track"), ("mlt_image_format", "rgba"),
                   ("set.test_audio", 0)])

    # A1 / V1: one clip per kept range. Positions on the final timeline are rounded from the
    # running total, so --speed rounding never adds up over hundreds of cuts.
    a1, v1 = ET.Element("playlist", id="playlist_a1"), ET.Element("playlist", id="playlist_v1")
    groups, tl_f = [], 0
    for i, k in enumerate(keeps):
        fa, fb = frames(k.src_start), frames(k.src_end)
        n = fb - fa
        if n <= 0:
            continue
        pos, length, cin = clip_frames(tl_f, n, fa, speed)
        clip = ids[k.media]
        for pl, which in ((v1, "video"), (a1, "audio")):
            if which not in clip:
                continue
            e = ET.SubElement(pl, "entry", producer=clip[which], **{"in": str(cin), "out": str(cin + length - 1)})
            _props(e, [("kdenlive:id", clip["kid"])])
            if which == "audio" and i < len(keeps) - 1:
                # Kdenlive's fade-out: the volume falls to 0 over the clip's last frame. A fade-in
                # would silence the clip's whole first frame (MLT applies volume per frame).
                out = cin + length - 1
                f = ET.SubElement(e, "filter", **{"in": str(out - FADE_FRAMES), "out": str(out)})
                _props(f, [("mlt_service", "volume"), ("kdenlive_id", "fadeout"), ("gain", 1), ("end", 0)])
        if "audio" in clip:
            groups.append({"type": "AVSplit", "children": [
                {"leaf": "clip", "data": f"0:{pos}:-1", "type": "Leaf"},
                {"leaf": "clip", "data": f"1:{pos}:-1", "type": "Leaf"}]})
        tl_f += n
    total = int(round(tl_f / speed))

    v2, last = ET.Element("playlist", id="playlist_v2"), 0
    for j, (_p, m, f0, f1) in enumerate(animations):
        clip = ids[1 + len(inserts) + j]
        a, b = max(f0, last), min(f1, total, f0 + frames(m.duration))
        if b <= a:
            continue
        if a > last:
            ET.SubElement(v2, "blank", length=str(a - last))
        e = ET.SubElement(v2, "entry", producer=clip["video"], **{"in": "0", "out": str(b - a - 1)})
        _props(e, [("kdenlive:id", clip["kid"])])
        last = b

    for pl in (a1, v1, v2):
        root.append(pl)
    _track_tractor(root, "track_a1", "", True, a1)
    _track_tractor(root, "track_v1", "", False, v1)
    _track_tractor(root, "track_v2", "animations", False, v2)

    seq = ET.SubElement(root, "tractor", id="sequence", out=str(max(total - 1, 0)))
    ass_dest = path + ".ass"
    seq_props = [
        ("kdenlive:duration", total), ("kdenlive:maxduration", total), ("kdenlive:clipname", name),
        ("kdenlive:description", ""), ("kdenlive:uuid", doc_uuid), ("kdenlive:producer_type", 17),
        ("kdenlive:id", SEQUENCE_ID), ("kdenlive:clip_type", 0), ("kdenlive:folderid", FOLDER_ID),
        ("kdenlive:sequenceproperties.activeTrack", 1), ("kdenlive:sequenceproperties.audioChannels", 2),
        ("kdenlive:sequenceproperties.audioTarget", 0), ("kdenlive:sequenceproperties.disablepreview", 0),
        ("kdenlive:sequenceproperties.documentuuid", doc_uuid), ("kdenlive:sequenceproperties.hasAudio", 1),
        ("kdenlive:sequenceproperties.hasVideo", 1), ("kdenlive:sequenceproperties.position", 0),
        ("kdenlive:sequenceproperties.scrollPos", 0), ("kdenlive:sequenceproperties.tracks", 3),
        ("kdenlive:sequenceproperties.tracksCount", 3), ("kdenlive:sequenceproperties.verticalzoom", 1),
        ("kdenlive:sequenceproperties.videoTarget", 1), ("kdenlive:sequenceproperties.zonein", 0),
        ("kdenlive:sequenceproperties.zoneout", 75), ("kdenlive:sequenceproperties.zoom", 8),
        ("kdenlive:sequenceproperties.groups", json.dumps(groups, indent=1)),
        ("kdenlive:sequenceproperties.guides", "[]")]
    if ass_path:
        seq_props.append(("kdenlive:sequenceproperties.subtitlesList", json.dumps(
            [{"name": "Subtitles", "id": 0, "file": ass_dest}])))
    _props(seq, seq_props)
    for tid in ("black_track", "track_a1", "track_v1", "track_v2"):
        ET.SubElement(seq, "track", producer=tid)
    _props(ET.SubElement(seq, "transition"), [  # sound of A1 mixed into the output
        ("a_track", 0), ("b_track", 1), ("mlt_service", "mix"), ("kdenlive_id", "mix"), ("internal_added", 237),
        ("always_active", 1), ("accepts_blanks", 1), ("sum", 1)])
    for b in (2, 3):  # V1, V2 composited over the tracks below (V2 keeps its transparency)
        _props(ET.SubElement(seq, "transition"), [
            ("a_track", 0), ("b_track", b), ("compositing", 0), ("distort", 0), ("rotate_center", 0),
            ("mlt_service", "qtblend"), ("always_active", 1), ("internal_added", 237)])
    _builtin_filters(seq, False)
    if ass_path:
        # Kdenlive reads <project>.kdenlive.ass into its subtitle track; melt draws it with this filter
        shutil.copyfile(ass_path, ass_dest)
        _props(ET.SubElement(seq, "filter"), [("mlt_service", "avfilter.subtitles"), ("internal_added", 237),
                                             ("av.filename", ass_dest), ("av.alpha", 1)])

    bin_pl = ET.SubElement(root, "playlist", id="main_bin")
    docprops = {
        "activetimeline": doc_uuid, "opensequences": doc_uuid, "uuid": doc_uuid,
        "documentid": str(uuid.uuid4().int % 10 ** 13), "version": DOC_VERSION,
        "kdenliveversion": KDENLIVE_VERSION, "compositing": 1, "enableproxy": 0, "generateproxy": 0,
        "enableTimelineZone": 0, "seekOffset": 30000}
    _props(bin_pl, [("kdenlive:folder.-1.%d" % FOLDER_ID, "Sequences")] +
           [("kdenlive:docproperties." + k, v) for k, v in docprops.items()] +
           [("kdenlive:expandedFolders", ""), ("kdenlive:documentnotes", ""), ("xml_retain", 1)])
    for i, (_p, m, _s) in enumerate(media):
        ET.SubElement(bin_pl, "entry", producer=ids[i]["bin"], **{"in": "0", "out": str(max(frames(m.duration) - 1, 0))})
    ET.SubElement(bin_pl, "entry", producer="sequence", **{"in": "0", "out": str(max(total - 1, 0))})
    final = ET.SubElement(root, "tractor", id="project", out=str(max(total - 1, 0)))
    _props(final, [("kdenlive:projectTractor", 1)])
    ET.SubElement(final, "track", producer="sequence", **{"in": "0", "out": str(max(total - 1, 0))})

    ET.indent(root, " ")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    log(f"Kdenlive project written: {path} ({sum(1 for _ in v1)} clips, {total / fps:.1f}s)")
    return path


def summarize_project(path: str) -> dict:
    """Re-read a generated project and return the structural facts the checks use."""
    root = ET.parse(path).getroot()
    fps = int(root.find("profile").get("frame_rate_num"))
    res = {}
    for el in root:
        if el.tag in ("chain", "producer"):
            props = {p.get("name"): p.text or "" for p in el.findall("property")}
            res[el.get("id")] = props.get("warp_resource") or props.get("resource", "")
    tracks = []
    for tid in ("playlist_a1", "playlist_v1", "playlist_v2"):
        pl = root.find(f"playlist[@id='{tid}']")
        pos, spans = 0, []
        for e in pl:
            if e.tag == "blank":
                pos += int(e.get("length"))
            elif e.tag == "entry":
                n = int(e.get("out")) - int(e.get("in")) + 1
                spans.append((pos, n, int(e.get("in")), res.get(e.get("producer"), "")))
                pos += n
        tracks.append({"name": tid[len("playlist_"):], "segments": len(spans), "spans": spans, "end": pos})
    seq = root.find("tractor[@id='sequence']")
    subs = [p.text for f in seq.findall("filter") for p in f.findall("property") if p.get("name") == "av.filename"]
    return {"fps": fps, "duration_frames": int(seq.get("out")) + 1, "tracks": tracks, "subtitles": subs,
            "media": sorted(set(res.values()) - {"black"})}
