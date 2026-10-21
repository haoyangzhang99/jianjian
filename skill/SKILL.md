---
name: jianjian
description: Edit a podcast/meeting video for Jianying Pro (剪映专业版) on this Mac — remove long pauses, add synchronized Chinese+English subtitles, optional explainer cards, create an editable Jianying draft and export an MP4. Use when the user asks to edit/cut/subtitle a podcast or episode, "剪播客", "去掉停顿", "加双语字幕", or to make a Jianying project from a recording, including short videos for Douyin (抖音), Xiaohongshu (小红书) or Shorts.
---

# Podcast → Jianying pipeline (jianjian)

Everything runs locally. Tool: the `jianjian` command (`setup.sh` links it into `~/.local/bin`); call it
`JIANJIAN` below. If it isn't on the PATH, it is `bin/jianjian` in the jianjian repo — this skill folder is a
symlink into that repo, so the repo is the parent of this file's real location. If `JIANJIAN doctor` says it
isn't set up, run `bash <repo>/setup.sh` first.

## 0. Before every new video: ask which pause preset

There is no default pace. Before you start editing a new video, show the user this table and ask
which preset to use, even if they already said "remove pauses". The only exceptions are when they
named a preset or gave exact numbers for this video. Reruns of the same video keep the preset
already chosen.

| Preset | Pauses longer than | become | Best for |
|---|---|---|---|
| `shorts` | 0.5 s | 0.25 s | Shorts / Reels / TikTok, one speaker, fastest pace |
| `youtube` | 0.6 s | 0.3 s | YouTube talking head, one speaker |
| `conversation` | 0.6 s | 0.35 s | YouTube conversation, 2+ speakers (keeps turn-taking natural) |
| `podcast` | 0.75 s | 0.4 s | Podcast / long-form listening, relaxed pace |
| `interview` | 1.0 s | 0.6 s | Slow, reflective interview; keeps thinking pauses |

If unsure, suggest one: `conversation` for a two-person YouTube show, `podcast` for audio-first.
`jianjian presets` prints the list. Exact values: `--max-pause S --keep-pause S`.

## 0b. Short-video platforms: plan the first 30 seconds

If the video is for Douyin (抖音), Xiaohongshu (小红书), Kuaishou, WeChat Channels (视频号), Shorts,
Reels or TikTok, suggest this opening structure along with the preset question, and build the
deliverable to it. If the platform isn't clear and the video is short or vertical, ask. These feeds
rank on completion, engagement and share rate, and the opening decides whether people stay.

| By | Goal | How |
|---|---|---|
| 0–3 s | **Hook** | One of three: a counter-intuitive claim (反常识); suspense: a striking result without the how (设置悬念); credentials + result, then empathy with the viewer's problem (身份 + 成绩) |
| 15 s | **Deliver value** | The first concrete tip or core insight, so staying feels worth it (值回票价) |
| 30 s | **Show the structure** | Say what the video covers and what the viewer gets, e.g. "今天分享三点：第一…第二…第三…" |

1. Run the edit once with `--cut-fillers` (the transcript is cached for reruns). Read
   `<out>/<name>.original-timeline.srt`.
2. Show the user an opening plan: the line that will open the video and its hook type, the value
   line, the roadmap line (source timestamps for each), and what gets cut to bring them forward:
   greetings, "大家好我是…", setup chatter, warm-up before the point. Content cuts are judgment
   calls, so wait for the user's OK.
3. Apply it: in `<out>/fillers.json`, add `{"words": [i, j], "kind": "restart", "cut": true}` for
   each span to remove (indices into `work/transcript_verbatim.json`), then rerun with
   `--fillers <out>/fillers.json`. If the user didn't ask for filler cuts, set the automatic
   candidates to `"cut": false`.
4. Check the edited timeline (`<out>/<name>.zh.srt` or `.bilingual.srt`, already speed-adjusted):
   hook within the first second, value by 15 s, roadmap by 30 s. Put these three times in your report.
5. If the best hook comes later in the recording, open on it with a cold open:
   `--hook START-END` (source time from `original-timeline.srt`, seconds or m:ss; repeat the flag
   for several spans, played in the given order). Take START and END from the line's cue times so
   the hook starts and ends on whole words; jianjian logs a NOTE when a bound falls inside a word.
   By default the hook plays first and again at its original place (`--hook-mode teaser`, like a
   精彩预告); `--hook-mode move` plays it only at the start. Ask which the user wants: a teaser
   repeats the line, a move takes it out of its context. Pauses and fillers inside the hook stay
   cut, its subtitles appear at 0 s, and the draft, MP4 and checks all follow the new order. If the
   recording has no usable hook, offer to record a 3-second hook line to add in Jianying, or
   (weaker) a card at 0 s with the hook as text (`--cards`, see §4). Never claim the structure is
   met when it isn't.

## 1. Map the request to flags

| User says | Flags |
|---|---|
| pause pace | `--preset NAME`: **always ask first**; see "Before every new video" below |
| for Douyin / 小红书 / Shorts / 短视频 | suggest `--preset shorts` and the 3/15/30 s opening plan (§0b) |
| open on a later line / cold open / 先放高光 | `--hook START-END` (source time; `--hook-mode move` to not repeat it), §0b |
| exact numbers ("cut pauses over 1.5 s down to 0.5 s") | `--max-pause 1.5 --keep-pause 0.5` |
| don't cut anything / subtitles only | `--no-cut` |
| remove filler words / uh, um / 去掉嗯啊、口头禅 | `--cut-fillers`, then review (§5) |
| make it faster / speed up / 加速 | `--speed 1.05` (subtle) or `1.1` (brisk); keep it ≤ 1.15 |
| bilingual subtitles (default) | `--subs bi` |
| Chinese only / English only / no subtitles | `--subs zh` / `--subs en` / `--subs none` |
| the podcast is all Chinese (more accurate) | `--lang zh` (default `auto` handles mixed zh/en speakers) |
| don't burn subtitles into the MP4 | `--no-burn` (add `--soft-subs` for selectable tracks) |
| only the Jianying project, no export | `--no-render` |
| only the MP4 | `--no-draft` |
| name the project | `--draft-name "..."` |
| term list for translation | `--glossary terms.txt` (lines `源词 = target`) |

Default output folder: next to the video, `<name>_edit/`. Never pass paths you haven't checked exist.

## 2. Run

```bash
JIANJIAN edit "/path/to/episode.mp4" [flags]
```
A 60-min episode takes roughly 15–20 min on Apple Silicon (measured: 15-min clip in 4.5 min).
Stages are cached in `<out>/work/`: re-running with different pause/subtitle/card settings skips
transcription. Use `--redo-asr` only if the transcript itself is bad.

## 3. Check and report

Read `<out>/report.md`. Report to the user: edited length and how much was removed, number of
subtitle lines, the Jianying draft name (it appears in Jianying's 本地草稿 list), the MP4 path, and
any PROBLEMS lines. For short-video platforms, also give the hook / value / roadmap times (§0b). Exit code 2 means a validation check failed — say which, don't claim success.

## 5. Review filler words (with --cut-fillers)

uh/um and stutter repeats are cut automatically; like / so / you know / I mean / 那个 / 就是 are only
listed. Read `<out>/fillers_review.md` (each candidate in context), then edit `<out>/fillers.json`:
- set `"cut": true` for fillers ("it was, **like**, huge", "that's fine, **you know**") and keep
  meaning ("I **like** this song", "**so** important", "I don't think **so**", "fruit **like** apples");
- set `"cut": false` on a "repeat" that is really two speakers or emphasis;
- add restarts: `{"words": [i, j], "kind": "restart", "cut": true}` (indices into
  `work/transcript_verbatim.json`);
- content suggestions (kind "content", with a reason: preamble before the greeting, talk about the
  recording, logistics, word search, back-and-forth, restart, unfinished ending) are never cut until
  approved. Show the user the list (time, reason, text) and ask before setting `"cut": true`. If
  `editing-style.local.md` exists, propose the kinds the user usually cuts. Reject false restarts:
  lists ("a red shirt or a red hat") and plain repetition ("talking about it"). Each
  approved passage also leaves the subtitles; recheck the Chinese of the lines listed as CHECK;
- B-roll: `report.md` lists insert points where a speaker asks for something to be shown ("put the
  clip here"), with their time in the edit. Tell the user; jianjian can't source the footage.
Rerun with `--fillers <out>/fillers.json` (fast: both transcripts are cached). Optionally check with
`.venv/bin/python tools/verify_words.py <out>`: "inside a removed span" must be 0.

## 4. Review subtitles (recommended before publishing)

The automatic subtitles are well timed but not publish-ready: expect wrong proper names (film
titles, people, brands), a few mishearings, and about 1 in 10 lines mistranslated. Review all of
`cues.json`, then rerun with `--cues` as below. That rerun only rebuilds the draft and MP4, about
2 min for 15 min of video. Don't put names into the transcription prompt: it made Whisper loop.


- **Translations**: read `<out>/cues.json` (fields: id, lang, text, translation). Fix weak lines and
  write `{"<id>": "better translation", ...}` to `<out>/fixes.json`, then rerun with
  `--translations <out>/fixes.json` (fast: transcription is cached).
- **Transcript typos / names**: in a copy of cues.json, fix `text` (and its `translation`) and rerun
  with `--cues reviewed.json`. Translations you write there are kept; lines with an empty
  `translation` are translated again locally. Don't change ids or timings.
- **Explainer cards** (secondary feature): read the transcript (`<out>/<name>.original-timeline.srt`),
  pick a few terms a general audience wouldn't know, and write `cards.json`:
  `[{"at": <source seconds>, "duration": 6, "title": "术语", "text": "一句话解释"}]` then rerun with
  `--cards cards.json`. Keep it to a handful; cards appear top-right and are editable text in Jianying.

## Rules

- Never modify or delete the source video or existing Jianying drafts. jianjian only adds a new draft
  (it auto-renames on a name clash) and writes into the output folder.
- Jianying 6+ encrypts drafts it saves, so a draft can't be edited by jianjian after you open/save it in
  Jianying. To change something, rerun jianjian to make a fresh draft.
- Export from inside Jianying is manual (导出 button); jianjian's own MP4 export is the automated path.
