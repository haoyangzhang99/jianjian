"""The marking transcript for a scripted solo talk: one line per take, for the speaker to edit.

    .venv/bin/python tools/marking.py make words.json -o transcript.md [--english]
    .venv/bin/python tools/marking.py diff transcript.orig.md transcript.md [--json]

`make` turns the words from tools/words_by_pause.py into lines `L001 [0:43] text`, one per sentence
or false start (a new line after sentence punctuation or a pause of 0.7 s), under a short "how to
edit" header, and keeps an untouched copy next to it (`*.orig.md`). The agent then adds the flags and
notes (skill §4b); the speaker deletes the lines they don't want, or deletes words inside a line.
`diff` lists what they removed, what they changed inside a line, and anything they wrote (for
example the path of a re-recorded sentence).
"""
import argparse
import json
import re
import shutil

LINE = re.compile(r"^L(\d+) \[(\d+):(\d+)\] ?(.*)$")
FLAGS = "🔁✅❓⚠〰️*"

HEAD_ZH = """# 逐字稿（待你标注）

## 怎么改

- 每行是你实际说的一句（或半句），`[分:秒]` 是原片时间。**不要的行整行删掉**，我按剩下的行剪。
- 只想去掉一行里的几个词，直接把那几个词删掉就行。
- 读错又没有重读的句子，可以补录一小段，把文件路径写在那一行下面。
- `L001` 这种行号请保留。`>` 开头的是备注，删不删都行。

| 标记 | 意思 |
|---|---|
| 🔁 | 重读里被放弃的一遍或半句，建议删 |
| ✅ | 重读里完整的一遍，建议留 |
| ❓ | 两遍都完整，你选一遍 |
| ⚠️ | 读错了词或数字，而且没有重读可以替换，需要你决定 |
| 〰️ | 和稿子有小出入，意思没变，建议留 |
| 无标记 | 和稿子一致 |

---

"""
HEAD_EN = """# Transcript to mark

## How to edit

- Each line is one sentence (or false start) as you said it; `[m:ss]` is the time in the recording.
  **Delete the whole line** for anything you don't want. I cut from the lines that remain.
- To drop a few words inside a line, just delete those words.
- For a misread sentence with no good retake, record it again and write the file's path under the line.
- Keep the `L001` numbers. Lines starting with `>` are notes; keep or delete them as you like.

| Mark | Meaning |
|---|---|
| 🔁 | an abandoned take or false start: suggest deleting |
| ✅ | the complete take of a retake: suggest keeping |
| ❓ | two complete takes: pick one |
| ⚠️ | a wrong word or number with no retake to replace it: your call |
| 〰️ | a small difference from the script, same meaning: suggest keeping |
| none | matches the script |

---

"""


def lines_from_words(words, pause=0.7):
    """[{"t": start seconds, "text": str}] : a new line after . ? ! or a pause of `pause` seconds."""
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if nxt is None or w["w"].rstrip().endswith((".", "?", "!")) or nxt["s"] - w["e"] >= pause:
            out.append({"t": cur[0]["s"], "text": " ".join(x["w"].strip() for x in cur)})
            cur = []
    return out


def render(lines, english=False):
    body = "\n\n".join(f"L{i:03d} [{int(l['t'] // 60)}:{int(l['t'] % 60):02d}] {l['text']}" for i, l in enumerate(lines, 1))
    return (HEAD_EN if english else HEAD_ZH) + body + "\n"


def parse(text):
    """{line number: (seconds, text without flags)} and the set of all raw lines."""
    out = {}
    for raw in text.splitlines():
        m = LINE.match(raw)
        if m:
            clean = m.group(4).translate({ord(c): None for c in FLAGS}).strip()
            out[int(m.group(1))] = (int(m.group(2)) * 60 + int(m.group(3)), clean)
    return out, set(text.splitlines())


def diff(orig_text, edited_text):
    """What the speaker did: deleted lines, lines changed inside, and anything they wrote."""
    o, oraw = parse(orig_text)
    e, _ = parse(edited_text)
    deleted = [{"line": k, "t": o[k][0], "text": o[k][1]} for k in sorted(o) if k not in e]
    changed = []
    for k in sorted(e):
        if k in o and o[k][1].split() != e[k][1].split():
            ow, ew = o[k][1].split(), e[k][1].split()
            changed.append({"line": k, "t": o[k][0], "before": o[k][1], "after": e[k][1],
                            "removed": [w for w in ow if ow.count(w) > ew.count(w)]})
    notes, last = [], None
    for raw in edited_text.splitlines():
        m = LINE.match(raw)
        if m:
            last = int(m.group(1))
        elif raw.strip() and raw not in oraw:
            notes.append({"after_line": last, "text": raw.strip()})
    return {"deleted": deleted, "changed": changed, "notes": notes, "kept": len(e), "of": len(o)}


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("make")
    m.add_argument("words"); m.add_argument("-o", "--out", required=True); m.add_argument("--english", action="store_true")
    d = sub.add_parser("diff")
    d.add_argument("orig"); d.add_argument("edited"); d.add_argument("--json", action="store_true")
    a = p.parse_args()
    if a.cmd == "make":
        lines = lines_from_words(json.load(open(a.words, encoding="utf-8"))["words"])
        open(a.out, "w", encoding="utf-8").write(render(lines, a.english))
        orig = re.sub(r"(\.md)?$", ".orig.md", a.out, count=1)
        shutil.copyfile(a.out, orig)
        print(f"{len(lines)} lines -> {a.out}\nUntouched copy for diffing later: {orig}\nAdd the flags and notes to {a.out}, then make the copy again (cp) before sending it.")
        return
    r = diff(open(a.orig, encoding="utf-8").read(), open(a.edited, encoding="utf-8").read())
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=1)); return
    f = lambda t: f"{t // 60}:{t % 60:02d}"
    print(f"kept {r['kept']} of {r['of']} lines")
    for x in r["deleted"]:
        print(f"  deleted L{x['line']:03d} [{f(x['t'])}] {x['text'][:90]}")
    for x in r["changed"]:
        print(f"  changed L{x['line']:03d} [{f(x['t'])}] removed {x['removed']}\n    - {x['before']}\n    + {x['after']}")
    for x in r["notes"]:
        print(f"  note after L{x['after_line']:03d}: {x['text']}" if x["after_line"] else f"  note: {x['text']}")


if __name__ == "__main__":
    main()
