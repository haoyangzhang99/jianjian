"""jianjian — podcast -> Jianying pipeline.

    jianjian edit VIDEO [options]     full job: pauses, bilingual subtitles, Jianying draft, MP4
    jianjian doctor                   check the environment
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

from . import __version__
from .cuts import (PRESET_ALIASES, PRESETS, CutSettings, TimeMap, apply_hooks, keep_ranges_from_cuts, plan,
                   preset_table, stats)
from .subs import Cue, CueSettings, build_cues, remap, write_ass, write_srt
from .util import (die, find_ffmpeg, ffmpeg_caps, fmt_dur, is_mac, log, mac_ram_gb, read_json,
                   set_log_file, write_json)


def _default_font() -> str:
    return "PingFang SC" if is_mac() else "Noto Sans CJK SC"


def _parse_glossary(path: str) -> dict:
    if not path:
        return {}
    if path.endswith(".json"):
        return read_json(path)
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def _map_path(p: str, maps) -> str:
    """Translate a local path to the path Jianying will see (only needed when running in a VM)."""
    for m in maps or []:
        frm, to = m.split("=", 1)
        if p.startswith(frm):
            return to + p[len(frm):]
    return p


def _seconds(t: str) -> float:
    """"312.4", "5:12.4" or "1:05:12.4" -> seconds."""
    v = 0.0
    for part in t.strip().split(":"):
        v = v * 60 + float(part)
    return v


def parse_span(text: str):
    """--hook value "START-END" (source time, seconds or m:ss) -> (start, end)."""
    a, sep, b = text.partition("-")
    try:
        span = (_seconds(a), _seconds(b))
    except ValueError:
        span = None
    if not sep or not span or span[1] <= span[0]:
        raise argparse.ArgumentTypeError(f"expected START-END in source time, e.g. 312.4-318.9 or 5:12.4-5:18.9, "
                                         f"got {text!r}")
    return span


def _pick_mt_model(arg: str) -> str:
    from .translate import DEFAULT_MODELS
    if arg and arg != "auto":
        return DEFAULT_MODELS.get(arg, arg)
    ram = mac_ram_gb() or 8
    return DEFAULT_MODELS["large" if ram >= 15.5 else "small"]


def cmd_edit(a) -> int:
    t_start = time.time()
    if not 0.5 <= a.speed <= 2.0:
        die("--speed must be between 0.5 and 2.0")
    if not (a.preset or a.no_cut or (a.max_pause and a.keep_pause)):
        die("choose how tightly to cut pauses — there is no default, the right pace depends on the "
            "video:\n" + preset_table() + "\nUse --preset NAME, or --max-pause S --keep-pause S, or --no-cut.")
    a.preset = PRESET_ALIASES.get(a.preset, a.preset)
    src = os.path.abspath(os.path.expanduser(a.input))
    if not os.path.isfile(src):
        die(f"input not found: {src}")
    stem = os.path.splitext(os.path.basename(src))[0]
    out = os.path.abspath(os.path.expanduser(a.out or os.path.join(os.path.dirname(src), f"{stem}_edit")))
    work = os.path.join(out, "work")
    os.makedirs(work, exist_ok=True)
    set_log_file(os.path.join(work, "run.log"))
    log(f"jianjian {__version__} — job for {src}")
    log(f"output folder: {out}")
    report = {"input": src, "output_dir": out, "version": __version__, "stages": {}}

    # 1. probe
    from .media import probe
    info = probe(src)
    write_json(os.path.join(work, "media.json"), info.to_dict())
    log(f"media: {fmt_dur(info.duration)}, {info.width}x{info.height} @ {info.fps:.2f} fps, "
        f"audio={'yes' if info.has_audio else 'NO'}")
    if not info.has_audio:
        die("input has no audio stream")
    if abs(info.video_start - info.audio_start) > 0.05:
        log(f"WARNING: video/audio stream start offset {info.video_start - info.audio_start:+.3f}s in source")
    report["media"] = info.to_dict()

    # 2. audio + VAD + transcript (cached)
    from . import asr
    audio = asr.load_audio(src)
    vad_path = os.path.join(work, "vad.json")
    if os.path.exists(vad_path) and not a.redo_asr:
        vad = [tuple(x) for x in read_json(vad_path)]
        log(f"VAD: reusing {len(vad)} regions from cache")
    else:
        vad = asr.run_vad(audio, threshold=a.vad_threshold)
        write_json(vad_path, vad)
    tr_path = os.path.join(work, "transcript.json")
    tr = read_json(tr_path) if os.path.exists(tr_path) and not a.redo_asr else None
    if tr and (tr.get("model_arg") != a.whisper_model or tr.get("lang_arg") != a.lang
               or "prompt" not in tr or tr.get("hint")):
        tr = None  # settings changed, or cached by a version without the per-window prompt
    if tr:
        log(f"transcript: reusing cache ({len(tr['words'])} words, language={tr['language']})")
    else:
        t0 = time.time()
        tr = asr.transcribe(audio, model_name=a.whisper_model, language=None if a.lang == "auto" else a.lang)
        tr["model_arg"], tr["lang_arg"] = a.whisper_model, a.lang
        tr["seconds"] = round(time.time() - t0, 1)
        write_json(tr_path, tr)
    report["transcript"] = {"language": tr["language"], "model": tr["model"], "words": len(tr["words"]),
                            "seconds": tr.get("seconds")}

    # 3. filler words (optional): a second, verbatim transcript keeps "uh/um" with timestamps
    fill_spans, protect, cands, vw = [], list(tr["words"]), None, None
    if (a.cut_fillers or a.fillers) and not a.no_cut:
        from . import fillers as fl
        vt_path = os.path.join(work, "transcript_verbatim.json")
        vt = read_json(vt_path) if os.path.exists(vt_path) and not a.redo_asr else None
        if vt and (vt.get("model_arg") != a.whisper_model or vt.get("lang_arg") != a.lang):
            vt = None
        if vt:
            log(f"verbatim transcript: reusing cache ({len(vt['words'])} words)")
        else:
            vt = asr.transcribe(audio, model_name=a.whisper_model,
                                language=None if a.lang == "auto" else a.lang, verbatim=True)
            vt["model_arg"], vt["lang_arg"] = a.whisper_model, a.lang
            write_json(vt_path, vt)
        vw = vt["words"]
        if a.fillers:
            cands = fl.load_review(read_json(a.fillers), vw)
            log(f"fillers: loaded {len(cands)} reviewed candidates from {a.fillers}")
        else:
            cands = fl.detect(vw)
            # content-cut suggestions (preamble, logistics, restarts ...): for review, never cut here
            from .content import suggest
            cands += [{"words": c["words"], "kind": "content", "cut": False, "reason": c["reason"]} for c in suggest(vw)]
            cands.sort(key=lambda c: c["words"][0])
            for k, c in enumerate(cands):
                c["id"] = k + 1
        write_json(os.path.join(out, "fillers.json"), fl.describe(cands, vw))
        fl.write_review_md(os.path.join(out, "fillers_review.md"), cands, vw)
        fill_spans = fl.spans(cands, vw, a.fps, audio=audio)
        gone = fl.cut_word_indices(cands)
        protect += [w for i, w in enumerate(vw) if i not in gone]
        kinds = {}
        for c in cands:
            if c["cut"]:
                kinds[c["kind"]] = kinds.get(c["kind"], 0) + 1
        fsec = sum(b - a_ for a_, b in fill_spans)
        log(f"fillers: cutting {sum(kinds.values())} of {len(cands)} candidates {kinds}, {fsec:.1f}s; "
            f"review list: fillers_review.md")
        content = [c for c in fl.describe(cands, vw) if c["kind"] == "content"]
        if content:
            log(f"content: {len(content)} cut suggestions for review ({sum(c['end'] - c['start'] for c in content):.0f}s; "
                f"{sum(1 for c in content if c['cut'])} approved), see fillers_review.md")
        report["fillers"] = {"candidates": len(cands), "cut": kinds, "seconds": round(fsec, 1),
                             "reviewed": bool(a.fillers),
                             "content_suggested": len(content), "content_cut": sum(1 for c in content if c["cut"])}

    # 4. cut plan
    mp, kp, _ = PRESETS.get(a.preset, (None, None, ""))
    cs = CutSettings(max_pause=a.max_pause or mp or 0.9, keep_pause=a.keep_pause or kp or 0.45, fps=a.fps)
    preset = "no cuts" if a.no_cut else a.preset or "custom"
    if a.no_cut:
        log("pause preset: no cuts (--no-cut: full length, subtitles only)")
        keeps = keep_ranges_from_cuts([], info.duration, a.fps)
        speech, cuts = [], []
    else:
        log(f"pause preset: {preset} (pauses > {cs.max_pause}s -> {cs.keep_pause}s)")
        speech, cuts, keeps = plan(vad, protect, info.duration, cs, fill_spans)
        # keep every cut out of audible sound: edges move to quiet points (see edges.py)
        from .edges import Loudness, edges_in_sound, refine_cuts
        loud = Loudness(audio)
        before = edges_in_sound(cuts, loud)
        cuts, est = refine_cuts(cuts, fill_spans, loud, a.fps)
        keeps = keep_ranges_from_cuts(cuts, info.duration, a.fps)
        est.update(edges_in_sound_before=before, edges_in_sound=edges_in_sound(cuts, loud))
        log(f"cut edges: {est['edges_in_sound_before']} of {2 * est['cuts']} were in audible sound -> "
            f"{est['edges_in_sound']} now; {est['moved']} cuts moved to quiet edges, {est['split']} split "
            f"around a sound, {est['valley']} glued fillers cut at a valley, {est['dropped']} dropped "
            f"(no quiet point: pause kept, or a glued filler left in)")
        if est["edges_in_sound"]:
            log(f"WARNING: {est['edges_in_sound']} cut edges still sit in audible sound; listen to those cuts")
    if a.hook:
        # cold open: the hook spans play first, then the edit from the start (cuts.apply_hooks)
        opener = sum(max(0.0, min(k.src_end, h1) - max(k.src_start, h0)) for h0, h1 in a.hook for k in keeps)
        try:
            keeps = apply_hooks(keeps, a.hook, a.fps, move=a.hook_mode == "move")
        except ValueError as e:
            die(f"--hook: {e}")
        log(f"hook: cold open of {len(a.hook)} span(s), {opener:.1f}s, "
            f"{'moved from' if a.hook_mode == 'move' else 'also kept at'} its original place")
        report["hook"] = {"spans": [list(h) for h in a.hook], "mode": a.hook_mode, "seconds": round(opener, 3)}
        for h0, h1 in a.hook:
            for w in tr["words"]:
                for t, which in ((h0, "start"), (h1, "end")):
                    if float(w["s"]) + 0.02 < t < float(w["e"]) - 0.02:
                        log(f"NOTE: hook {which} {t:.2f}s falls inside the word {w['w'].strip()!r} "
                            f"({w['s']:.2f}-{w['e']:.2f}s); use word or cue times from original-timeline.srt")
    st = stats(keeps, info.duration, a.fps)
    write_json(os.path.join(out, "cuts.json"), {
        "settings": cs.to_dict(), "stats": st,
        "keep_ranges": [[round(k.src_start, 4), round(k.src_end, 4), round(k.tl_start, 4)] for k in keeps],
        "removed": [[round(x, 3), round(y, 3)] for x, y in cuts]})
    log(f"cuts: removed {st['num_cuts']} pauses/fillers, {st['removed_seconds']:.1f}s "
        f"({st['removed_percent']}%), {fmt_dur(st['source_duration'])} -> {fmt_dur(st['edited_duration'])}")
    report["cuts"] = {"preset": preset, "settings": cs.to_dict(), **st}
    if not a.no_cut:
        report["cuts"]["edges"] = est
    tmap = TimeMap(keeps)
    # B-roll: places where a speaker asks for something to be shown ("put the clip here")
    from .content import broll_markers
    report["broll"] = [{**m, "edit_time": round(tmap.to_timeline(m["start"]) / a.speed, 2)} for m in broll_markers(tr["words"])]
    for m in report["broll"]:
        log(f"B-roll: insert point at {fmt_dur(m['edit_time'])} in the edit: {m['text'][:70]!r}")

    # 4. cues (+ reuse translations from a previous run of the same transcript)
    cues_path = os.path.join(out, "cues.json")
    if a.cues:
        cues = [Cue(**{k: v for k, v in d.items() if k in Cue.__dataclass_fields__}) for d in read_json(a.cues)]
        log(f"cues: loaded {len(cues)} edited cues from {a.cues}")
    else:
        cues = build_cues(tr["words"], CueSettings(max_units=a.max_chars))
        if os.path.exists(cues_path) and not a.retranslate:
            old = {(d["start"], d["text"]): d.get("translation", "") for d in read_json(cues_path)}
            reused = 0
            for c in cues:
                t = old.get((c.start, c.text))
                if t:
                    c.translation, reused = t, reused + 1
            if reused:
                log(f"cues: reused {reused} translations from previous run")
    if cands:
        # subtitles say what the edit says: cut repeats / discourse words / restarts leave the text
        from .fillers import strip_from_cues
        changed, flag = strip_from_cues(cues, cands, vw)
        cues = [c for c in cues if c.text.strip()]
        log(f"subtitles: removed cut filler words from {len(changed)} lines")
        if flag:
            log(f"subtitles: CHECK the Chinese of lines {flag}: it may still translate a cut filler")
        report.setdefault("fillers", {})["subtitle_lines_changed"] = len(changed)
        report["fillers"]["check_translation"] = flag
    nz = sum(1 for c in cues if c.lang == "zh")
    log(f"cues: {len(cues)} subtitle lines ({nz} Chinese, {len(cues) - nz} English)")

    # 5. translation
    tracks = {"bi": ("zh", "en"), "zh": ("zh",), "en": ("en",), "none": ()}[a.subs]
    need = [c for c in cues if not c.translation and ((c.lang == "zh" and "en" in tracks) or
                                                       (c.lang == "en" and "zh" in tracks))]
    if a.translations:
        from .translate import apply_translation_file
        n = apply_translation_file(cues, a.translations)
        log(f"translations: imported {n} from {a.translations}")
        need = [c for c in need if not c.translation]
    if need and a.translator == "mlx":
        from .translate import translate_cues
        try:
            report["translation"] = translate_cues(need, _pick_mt_model(a.mt_model),
                                                   glossary=_parse_glossary(a.glossary))
        except ImportError as e:
            log(f"WARNING: translation skipped, mlx-lm not available ({e})")
            report["translation"] = {"skipped": str(e)}
    elif need:
        log(f"translation: skipped ({len(need)} lines left untranslated; translator={a.translator})")
        report["translation"] = {"skipped": "translator=none", "untranslated": len(need)}
    write_json(cues_path, [c.to_dict() for c in cues])

    # 6. timeline subtitles (on the final timeline: edited, then sped up by --speed)
    tl_cues = remap(cues, tmap)
    if a.speed != 1.0:
        for c in tl_cues:
            c.tl_start, c.tl_end = c.tl_start / a.speed, c.tl_end / a.speed
        log(f"speed: {a.speed}x (pitch kept) -> {fmt_dur(tmap.edited_duration / a.speed)}")
        report["speed"] = a.speed
        if a.speed > 1.15:
            log("NOTE: above ~1.15x speech starts to sound rushed")
    write_srt(os.path.join(out, f"{stem}.zh.srt"), tl_cues, "zh")
    write_srt(os.path.join(out, f"{stem}.en.srt"), tl_cues, "en")
    write_srt(os.path.join(out, f"{stem}.bilingual.srt"), tl_cues, "bi")
    write_srt(os.path.join(out, f"{stem}.original-timeline.srt"), cues, "bi", timeline=False)
    ass_path = os.path.join(out, f"{stem}.bilingual.ass")
    order = tuple(t for t in ("zh", "en") if t in tracks)
    cards = []
    if a.cards:
        from .cards import load_cards
        cards = load_cards(a.cards, tmap)
        for cd in cards:
            cd["tl_start"], cd["tl_end"] = cd["tl_start"] / a.speed, cd["tl_end"] / a.speed
        log(f"cards: {len(cards)} explainer cards from {a.cards}")
    write_ass(ass_path, tl_cues, info.width, info.height, a.font or _default_font(), order=order, cards=cards)
    report["subtitles"] = {"lines": len(tl_cues), "zh": sum(1 for c in tl_cues if c.zh),
                           "en": sum(1 for c in tl_cues if c.en)}

    # 7. Jianying draft
    from . import draft as jd
    from .validate import check_draft
    if not a.no_draft:
        name = a.draft_name or f"{stem}_auto_{time.strftime('%m%d-%H%M')}"
        try:
            root = jd.find_drafts_root(a.drafts_root)
        except FileNotFoundError as e:
            root = ""
            log(f"WARNING: {e}; the draft will only be written to the output folder")
        if root and not a.no_install:  # rename on a clash only when we will install next to it
            base, n = name, 2
            while os.path.exists(os.path.join(root, name)):
                name, n = f"{base}_{n}", n + 1
        staging = os.path.join(out, "jianying_draft")
        rec_media, rec_root = _map_path(src, a.path_map), _map_path(root or staging, a.path_map)
        staged = jd.build_draft(staging, name, info, rec_media, keeps, tl_cues, a.fps,
                                final_root=rec_root, tracks=order, cards=cards, speed=a.speed)
        chk = check_draft(staged, keeps, a.fps, rec_media, local_media=src, speed=a.speed)
        report["draft"] = {"name": name, "staged": staged, "check": chk}
        log(f"draft check: {'OK' if chk['ok'] else 'PROBLEMS: ' + '; '.join(chk['problems'])}")
        if root and chk["ok"] and not a.no_install:
            report["draft"]["installed"] = jd.install_draft(staged, root)
        elif root and not chk["ok"]:
            log("draft NOT installed into Jianying because validation failed")

    # 8. MP4 render
    if not a.no_render:
        from .render import render
        from .validate import check_render
        ff = find_ffmpeg()
        if not ff:
            log("WARNING: no ffmpeg found; skipping MP4 render (run setup.sh or install ffmpeg)")
        else:
            caps = ffmpeg_caps(ff)
            mp4 = os.path.join(out, f"{stem}_edited.mp4")
            srts = [(os.path.join(out, f"{stem}.{t}.srt"), t) for t in order] if a.soft_subs else []
            want_burn = a.burn and bool(order)
            if want_burn and not caps["libass"]:
                log("NOTE: this ffmpeg has no libass; adding subtitles as selectable tracks instead of burning in")
                srts = [(os.path.join(out, f"{stem}.{t}.srt"), t) for t in order]
            r = render(src, mp4, keeps, info, caps, fps=a.fps, ass_path=ass_path if want_burn else None,
                       srt_tracks=srts, encoder=a.encoder, speed=a.speed)
            probes = [c.tl_start for c in tl_cues][:: max(1, len(tl_cues) // 8)][:8]
            vr = check_render(mp4, audio, keeps, a.fps, probes, speed=a.speed, ffmpeg=ff)
            r["check"] = vr
            report["render"] = {"file": mp4, **r}
            log(f"render check: {'OK' if vr['ok'] else 'PROBLEMS: ' + '; '.join(vr['problems'])}; "
                f"sync probes: " + ", ".join(f"{p['offset_ms']:+.0f}ms" for p in vr["sync_probes"]))

    report["total_seconds"] = round(time.time() - t_start, 1)
    write_json(os.path.join(out, "report.json"), report)
    _write_report_md(os.path.join(out, "report.md"), report)
    log(f"done in {fmt_dur(report['total_seconds'])}. Report: {os.path.join(out, 'report.md')}")
    ok = report.get("draft", {}).get("check", {}).get("ok", True) and \
        report.get("render", {}).get("check", {}).get("ok", True)
    return 0 if ok else 2


def _write_report_md(path: str, r: dict) -> None:
    c, m = r.get("cuts", {}), r.get("media", {})
    lines = [f"# Edit report — {os.path.basename(r['input'])}", "",
             f"- Source: `{r['input']}` ({fmt_dur(m.get('duration', 0))}, {m.get('width')}x{m.get('height')})",
             f"- Edited length: {fmt_dur(c.get('edited_duration', 0) / r.get('speed', 1.0))}"
             f"{' at ' + str(r['speed']) + 'x speed' if r.get('speed') else ''} — removed {c.get('num_cuts')} pauses/fillers, "
             f"{c.get('removed_seconds')}s ({c.get('removed_percent')}%), longest {c.get('longest_cut')}s",
             f"- Pause preset: no cuts (--no-cut)" if c.get('preset') == "no cuts" else
             f"- Pause preset: {c.get('preset')} — max_pause={c.get('settings', {}).get('max_pause')}s, "
             f"keep_pause={c.get('settings', {}).get('keep_pause')}s",
             f"- Transcript: language={r.get('transcript', {}).get('language')}, "
             f"model={r.get('transcript', {}).get('model')}, words={r.get('transcript', {}).get('words')}",
             f"- Subtitles: {r.get('subtitles', {}).get('lines')} lines "
             f"(zh {r.get('subtitles', {}).get('zh')}, en {r.get('subtitles', {}).get('en')})"]
    e = c.get("edges")
    if e:
        lines.append(f"- Cut edges in audible sound: {e['edges_in_sound']} (before moving them to quiet points: "
                     f"{e['edges_in_sound_before']}); {e['moved']} cuts moved, {e['split']} split around a sound, "
                     f"{e['dropped']} dropped (pause kept or glued filler left in)")
    h = r.get("hook")
    if h:
        lines.append(f"- Cold open: {', '.join(f'{x:.2f}-{y:.2f}s' for x, y in h['spans'])} plays first "
                     f"({h['seconds']}s, {'moved' if h['mode'] == 'move' else 'teaser: also kept in place'})")
    fz = r.get("fillers")
    if fz:
        lines.append(f"- Filler words: cut {sum(fz['cut'].values())} of {fz['candidates']} candidates "
                     f"{fz['cut']}, {fz['seconds']}s ({'reviewed' if fz['reviewed'] else 'automatic only'}; "
                     f"see fillers_review.md)")
    if fz and fz.get("content_suggested"):
        lines.append(f"- Content cuts: {fz['content_suggested']} suggested, {fz['content_cut']} approved "
                     f"(see fillers_review.md)")
    for m in r.get("broll", []):
        lines.append(f"- B-roll insert point at {fmt_dur(m['edit_time'])} in the edit: \"{m['text']}\"")
    t = r.get("translation")
    if t:
        lines.append(f"- Translation: {json.dumps(t, ensure_ascii=False)}")
    d = r.get("draft")
    if d:
        lines += ["", "## Jianying draft", f"- Name: **{d['name']}**",
                  f"- Installed at: `{d.get('installed', 'not installed')}`",
                  f"- Check: {'OK' if d['check']['ok'] else d['check']['problems']}",
                  f"- Tracks: " + ", ".join(f"{t['type']}:{t['name']} ({t['segments']})" for t in d["check"]["tracks"])]
    v = r.get("render")
    if v:
        ck = v["check"]
        lines += ["", "## Exported MP4", f"- File: `{v['file']}`",
                  f"- Encoder: {v['encoder']}, burned subtitles: {v['burned_subtitles']}, {v['seconds']}s",
                  f"- Duration {ck['duration_s']}s (expected {ck['expected_s']}s)",
                  f"- A/V sync probes (offset vs expected audio): " +
                  ", ".join(f"{p['t']}s: {p['offset_ms']:+.0f}ms (r={p['corr']})" for p in ck["sync_probes"]),
                  f"- Check: {'OK' if ck['ok'] else ck['problems']}"]
    lines += ["", f"Total time: {fmt_dur(r.get('total_seconds', 0))}", ""]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def cmd_doctor(a) -> int:
    ok = True
    print(f"jianjian {__version__}  python {sys.version.split()[0]}  mac={is_mac()}")
    ram = mac_ram_gb()
    print(f"RAM: {ram:.0f} GB" if ram else "RAM: unknown")
    for mod in ("faster_whisper", "av", "numpy", "opencc", "mlx_lm"):
        try:
            __import__(mod)
            print(f"  [ok] {mod}")
        except Exception as e:
            print(f"  [--] {mod}: {e}")
            ok = ok and mod not in ("faster_whisper", "av", "numpy")
    ff = find_ffmpeg()
    if ff:
        c = ffmpeg_caps(ff)
        print(f"ffmpeg: {c['path']}\n  {c['version']}\n  libass={c['libass']} videotoolbox={c['videotoolbox']} "
              f"libx264={c['libx264']}")
    else:
        print("ffmpeg: NOT FOUND (MP4 export disabled)")
    from .draft import find_drafts_root
    try:
        print(f"Jianying drafts folder: {find_drafts_root(a.drafts_root)}")
    except FileNotFoundError as e:
        print(f"Jianying drafts folder: {e}")
    free = shutil.disk_usage(os.path.expanduser("~")).free / 1024 ** 3
    print(f"free disk: {free:.0f} GB")
    print(f"translation model for this machine: {_pick_mt_model('auto')}")
    return 0 if ok else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="jianjian", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("edit", help="edit a podcast recording")
    e.add_argument("input")
    e.add_argument("--out", help="output folder (default: <video folder>/<name>_edit)")
    g = e.add_argument_group("pauses")
    g.add_argument("--preset", choices=list(PRESETS) + list(PRESET_ALIASES), default=None,
                   help="required (no default): " + ", ".join(PRESETS) + "; see `jianjian presets`")
    g.add_argument("--max-pause", type=float, help="shorten silences longer than this (s)")
    g.add_argument("--keep-pause", type=float, help="length a shortened silence keeps (s)")
    g.add_argument("--no-cut", action="store_true", help="keep the full length (subtitles only)")
    g.add_argument("--vad-threshold", type=float, default=0.5)
    g.add_argument("--cut-fillers", action="store_true",
                   help="also cut uh/um and stutter repeats; lists like/so/you know for review")
    g.add_argument("--fillers", help="reviewed fillers.json (cut flags decided); implies --cut-fillers")
    g.add_argument("--hook", type=parse_span, action="append", default=[], metavar="START-END",
                   help="cold open: play this source span first (seconds or m:ss; repeat for several, "
                        "played in the given order), then the edit from the start")
    g.add_argument("--hook-mode", choices=["teaser", "move"], default="teaser",
                   help="teaser (default): the hook also plays at its original place; move: only at the start")
    s = e.add_argument_group("subtitles")
    s.add_argument("--lang", default="auto", help="spoken language: auto | zh | en")
    s.add_argument("--subs", choices=["bi", "zh", "en", "none"], default="bi")
    s.add_argument("--whisper-model", default="large-v3-turbo")
    s.add_argument("--translator", choices=["mlx", "none"], default="mlx")
    s.add_argument("--mt-model", default="auto", help="auto | large | small | <mlx model repo>")
    s.add_argument("--glossary", help="term list: JSON {src: dst} or 'src = dst' lines")
    s.add_argument("--translations", help="JSON of translations to import (e.g. from your coding agent)")
    s.add_argument("--cues", help="use an edited cues.json instead of rebuilding from the transcript")
    s.add_argument("--retranslate", action="store_true")
    s.add_argument("--cards", help="explainer cards JSON: [{at, duration, title, text}] (source seconds)")
    s.add_argument("--max-chars", type=float, default=20.0, help="max Chinese characters per subtitle line")
    s.add_argument("--redo-asr", action="store_true", help="ignore cached VAD/transcript")
    j = e.add_argument_group("Jianying")
    j.add_argument("--draft-name")
    j.add_argument("--drafts-root", default="")
    j.add_argument("--no-draft", action="store_true")
    j.add_argument("--no-install", action="store_true", help="build the draft but don't copy it into Jianying")
    j.add_argument("--path-map", action="append", default=[], help=argparse.SUPPRESS)
    r = e.add_argument_group("export")
    r.add_argument("--no-render", action="store_true")
    r.add_argument("--no-burn", dest="burn", action="store_false", help="don't burn subtitles into the MP4")
    r.add_argument("--soft-subs", action="store_true", help="also embed selectable subtitle tracks")
    r.add_argument("--encoder", default="auto", help="auto | h264_videotoolbox | libx264")
    r.add_argument("--fps", type=int, default=30, choices=[24, 25, 30, 48, 50, 60])
    r.add_argument("--speed", type=float, default=1.0,
                   help="play the whole edit faster, pitch kept (e.g. 1.05; above ~1.15 sounds rushed)")
    r.add_argument("--font", default="", help="subtitle font for the MP4 (default PingFang SC)")
    e.set_defaults(func=cmd_edit)

    pr = sub.add_parser("presets", help="list the pause presets")
    pr.set_defaults(func=lambda _a: print(preset_table()) or 0)

    d = sub.add_parser("doctor", help="check the environment")
    d.add_argument("--drafts-root", default="")
    d.set_defaults(func=cmd_doctor)

    a = p.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
