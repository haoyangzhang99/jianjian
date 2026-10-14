"""Check an edited video lost no real words: transcribe it verbatim and align with the words that
should remain (the source's verbatim transcript minus the cut fillers).

    .venv/bin/python tools/verify_words.py EDIT_DIR [--video other.mp4]

EDIT_DIR is a jianjian output folder made with --cut-fillers (it has work/transcript_verbatim.json,
fillers.json and cuts.json). Reports remaining uh/um and every expected word missing from the
edit, with context. Re-transcription itself is a little noisy, so compare against a baseline run
on a pause-only edit before blaming the cuts.
"""
import argparse
import difflib
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from jianjian import asr  # noqa: E402
from jianjian.fillers import HESITATIONS, norm  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("edit_dir")
    p.add_argument("--video", help="edited video to check (default: the *_edited.mp4 in EDIT_DIR)")
    p.add_argument("--expect-all", action="store_true", help="expect every verbatim word except "
                   "hesitations (use for a pause-only baseline edit)")
    a = p.parse_args()
    d = a.edit_dir
    vw = json.load(open(os.path.join(d, "work", "transcript_verbatim.json"), encoding="utf-8"))["words"]
    cuts = json.load(open(os.path.join(d, "cuts.json"), encoding="utf-8"))["removed"]
    gone = set()
    if not a.expect_all:
        for c in json.load(open(os.path.join(d, "fillers.json"), encoding="utf-8")):
            if c["cut"]:
                gone.update(range(c["words"][0], c["words"][1] + 1))
    # words inside removed spans that aren't fillers would be clipped words: keep them as expected
    exp = [(i, norm(w["w"])) for i, w in enumerate(vw)
           if i not in gone and norm(w["w"]) and norm(w["w"]) not in HESITATIONS]

    video = a.video or glob.glob(os.path.join(d, "*_edited.mp4"))[0]
    audio = asr.load_audio(video)
    out = asr.transcribe(audio, verbatim=True)["words"]
    got = [norm(w["w"]) for w in out if norm(w["w"])]
    left = sum(1 for t in got if t in HESITATIONS)
    got_words = [t for t in got if t not in HESITATIONS]

    sm = difflib.SequenceMatcher(a=[t for _, t in exp], b=got_words, autojunk=False)
    missing = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op in ("delete", "replace"):
            for k in range(i1, i2):
                missing.append(exp[k][0])
    print(f"video: {video}")
    print(f"expected words: {len(exp)}  transcribed: {len(got_words)}  uh/um still audible: {left}")
    print(f"expected words not found: {len(missing)} ({100 * len(missing) / max(len(exp), 1):.1f}%)")
    in_cut = [i for i in missing if any(c0 <= (vw[i]['s'] + vw[i]['e']) / 2 <= c1 for c0, c1 in cuts)]
    print(f"  ...of which inside a removed span (really cut away): {len(in_cut)}")
    for i in in_cut:
        ctx = "".join(w["w"] for w in vw[max(0, i - 5):i]) + " [" + vw[i]["w"].strip() + "] " + \
              "".join(w["w"] for w in vw[i + 1:i + 6])
        print(f"    {vw[i]['s']:7.2f}s  {ctx.strip()}")


if __name__ == "__main__":
    main()
