# jianjian 剪剪

**Turn a podcast or video-call recording into an edited Jianying Pro (剪映专业版) project, locally
and for free.** Long pauses and filler words are trimmed, synchronized Chinese + English subtitles
are added, and you get both an editable Jianying draft and a finished MP4.

- **Pause trimming** with presets for Shorts, YouTube, conversations, podcasts and interviews
- **Filler-word removal** (optional): uh / um and stutters automatically; "like / you know" after review
- **Bilingual subtitles**, transcribed and translated on your Mac (Whisper + Qwen2.5 via MLX)
- **A new, editable Jianying draft** that references your original file, plus an **MP4** with
  burned-in subtitles, rendered by FFmpeg
- **Optional speed-up** (e.g. 1.05×) with the voice pitch kept
- **Cold open** (optional): start a short video on a hook line from later in the recording
- **Built for coding agents** (Claude Code, Codex): a skill maps plain-language requests to the tool

No paid software, no API keys, and no media leaves the Mac. The network is used only once, to
download open-source packages and models.

> jianjian is an independent project. It is not affiliated with or endorsed by ByteDance, the
> maker of Jianying / CapCut. Jianying's draft format is undocumented; a Jianying update can break
> draft generation. Tested with Jianying Pro 11.5 on macOS.

## Requirements

- An Apple Silicon Mac (MLX translation needs it)
- An arm64 Python 3.10–3.13, or [`uv`](https://github.com/astral-sh/uv)
- About 12 GB of free disk for packages and models
- Jianying Pro for the draft (optional: the MP4 doesn't need it)

## Install

```bash
git clone https://github.com/haoyangzhang99/jianjian.git
cd jianjian
bash setup.sh
```

Setup:

- Creates `./.venv` with faster-whisper, mlx-lm, opencc, jieba and imageio-ffmpeg. Nothing is
  installed system-wide.
- Downloads the Whisper large-v3-turbo model (about 1.6 GB) into `~/.cache/huggingface`.
- Downloads a translation model into the same cache, sized to your RAM:
  - 16 GB or more: Qwen2.5-7B-Instruct, 4-bit, about 4.3 GB
  - less than 16 GB: Qwen2.5-1.5B-Instruct, 4-bit, about 0.9 GB (lower translation quality)
- Links the `jianjian` command into `~/.local/bin`.
- Links `skill/` into `~/.agents/skills`, `~/.codex/skills` and `~/.claude/skills`, for whichever
  of those already exist, so coding agents can use it from plain language.

No macOS permissions are needed. jianjian reads and writes files only: your video folder, a new
`<name>_edit/` output folder, and Jianying's drafts folder
(`~/Movies/JianyingPro/User Data/Projects/com.lveditor.draft/`), where it only ever adds new drafts.

## Quick start

```bash
jianjian presets                                   # pick a pause preset (there is no default)
jianjian edit ~/Videos/episode.mp4 --preset conversation
jianjian edit ~/Videos/episode.mp4 --preset conversation --cut-fillers --speed 1.05
jianjian doctor                                    # check the environment
```

Or ask your coding agent in plain language:

> Edit ~/Videos/episode.mp4 for Jianying: trim the pauses, cut filler words, add Chinese and English
> subtitles, and export it.

The agent asks which pause preset to use before it starts (see `skill/SKILL.md`). For Douyin,
Xiaohongshu or Shorts it also proposes a 3 / 15 / 30 s opening (hook, value, structure) and trims
the preamble so the edit opens on the hook, or moves a later hook line to the front with `--hook`.

Output goes to `<video folder>/<name>_edit/`:

| File | What |
|---|---|
| `report.md` / `report.json` | What was done, plus the validation and sync checks |
| `<name>_edited.mp4` | Finished video with burned-in subtitles |
| `<name>.zh.srt`, `.en.srt`, `.bilingual.srt`, `.bilingual.ass` | Subtitles on the edited timeline |
| `<name>.original-timeline.srt` | Subtitles on the original, uncut timeline |
| `cues.json` | Every subtitle line with its translation; edit it and rerun with `--cues` |
| `fillers.json`, `fillers_review.md` | Filler-word candidates and decisions (with `--cut-fillers`) |
| `cuts.json` | The exact keep ranges and removed pauses / fillers |
| `jianying_draft/` | A copy of the generated draft; the live one is inside Jianying |

In Jianying, the draft appears under 首页 → 本地草稿. If Jianying was already open, go back to the
home page, or restart Jianying if it still doesn't show.

## Pause presets

| Preset | Pauses longer than | become | Best for |
|---|---|---|---|
| `shorts` | 0.5 s | 0.25 s | Shorts / Reels / TikTok, one speaker, fastest pace |
| `youtube` | 0.6 s | 0.3 s | YouTube talking head, one speaker |
| `conversation` | 0.6 s | 0.35 s | YouTube conversation, 2+ speakers (keeps turn-taking natural) |
| `podcast` | 0.75 s | 0.4 s | Podcast / long-form listening, relaxed pace |
| `interview` | 1.0 s | 0.6 s | Slow, reflective interview; keeps thinking pauses |

Pauses at or below the threshold are left as they are; longer ones are shortened to the kept
length. The values follow common silence-removal tools: Mubert Cast's default is pauses over 0.5 s
shortened to 0.3 s, FireCut suggests 750 ms with 250 + 250 ms padding, AutoCut calls 0.3–0.5 s
ideal for YouTube, auto-editor keeps 0.2 s each side, and Chinese 口播 guidance keeps 0.2–0.8 s
(0.8–1.2 s for interviews).

## Settings

| Flag | Default | Meaning |
|---|---|---|
| `--preset NAME` | **required** | Pause handling; see the presets above. There is no default because the right pace depends on the video. |
| `--max-pause S --keep-pause S` | | Exact pause thresholds instead of a preset |
| `--no-cut` | | Keep the full length (subtitles only) |
| `--cut-fillers` | | Also cut uh/um and stutter repeats (also "they, uh, they"). like / so / you know, word restarts and **content-cut suggestions** (preamble, logistics, word searches, back-and-forth, restarts, an unfinished ending) are listed in `fillers_review.md` for review, not cut. `report.md` also lists **B-roll insert points** ("put the clip here"). |
| `--fillers FILE` | | Apply a reviewed `fillers.json` (`"cut": true/false` per candidate; restarts can be added by word range) |
| `--hook START-END` | | Cold open: play this span of the original (seconds or m:ss, e.g. `10:16.3-10:24.4`) first, then the edit from the start. Repeat for several spans. |
| `--hook-mode teaser\|move` | teaser | `teaser`: the hook also plays again at its original place; `move`: only at the start |
| `--insert AT=CLIP` | | Put a clip (a film scene, a screen recording) into the edit at this moment of the original (seconds or m:ss; a moment inside a cut snaps to the cut). It plays at normal speed even with `--speed`, with its own sound matched to the conversation's loudness, scaled to fit the frame. Repeat for several clips. Use the B-roll insert points in `report.md`. |
| `--speed 1.05` | 1.0 | Play the whole edit faster, voice pitch kept. 1.05× is barely noticeable, 1.1× feels brisk, and above about 1.15× speech sounds rushed. |
| `--lang auto\|zh\|en` | auto | `auto` detects the language per segment, which suits mixed Chinese/English speakers |
| `--subs bi\|zh\|en\|none` | bi | Which subtitle languages to create |
| `--glossary FILE` | | Term list for the translator, as `源词 = target` lines or JSON |
| `--cues FILE` | | Use a reviewed `cues.json` (fixed text and translations) |
| `--translations FILE` | | Import fixed or better translations (`{"id": "text"}`) |
| `--cards FILE` | | Explainer cards: `[{"at": src_seconds, "duration": 6, "title": "", "text": ""}]` |
| `--no-draft` / `--no-render` / `--no-install` | | Skip the Jianying draft, skip the MP4, or build the draft without adding it to Jianying |
| `--no-burn` / `--soft-subs` | | Don't burn in subtitles / also add selectable subtitle tracks |
| `--fps 30` | 30 | Timeline frame rate; every cut is snapped to this frame grid |

Re-runs are fast: the VAD and transcripts are cached in `work/`, so changing pause settings,
subtitles, fillers or cards doesn't re-transcribe. Use `--redo-asr` to force a fresh transcript.

## Review before publishing

Automatic subtitles are well timed but not publish-ready: expect wrong proper names (titles,
people, brands), a few mishearings and roughly one mistranslated line in ten. The workflow, which
an agent can do for you (see `skill/SKILL.md`):

1. Review `cues.json`: fix `text` and `translation` in a copy, rerun with `--cues reviewed.json`.
2. With `--cut-fillers`: review `fillers_review.md`, set `"cut"` in `fillers.json` (fillers and
   the suggested content cuts), rerun with `--fillers fillers.json`. Optionally run `.venv/bin/python tools/verify_words.py <out>` to confirm
   no real words were cut.
3. Watch the result and listen to the cuts.

## How it works

```
video ─► 16 kHz audio ─► Silero VAD ─┐
                    └─► faster-whisper (word timestamps) ─┤ (+ verbatim pass for filler words)
                                                          ├─► keep ranges, snapped to 1/fps
                                                          │      │
             subtitle cues ◄─ word grouping ◄─────────────┘      ├─► Jianying draft (pyJianYingDraft)
                │                                                │      main track = keep ranges of the ORIGINAL file
          MLX translation (Qwen2.5)                              │      text track = bilingual cues on the edit
                │                                                └─► FFmpeg render (same keep ranges)
                └──────────────── remapped onto edited timeline ─────────► SRT / ASS / burned-in MP4
```

- **Sync.** The Jianying timeline, the render and the subtitles all use the same frame-snapped keep
  ranges, so the edit can't drift over hundreds of cuts. Each render is checked automatically by
  cross-correlating its audio with the expected audio.
- **Fillers** come from a second, verbatim Whisper pass and are re-located on the waveform, because
  Whisper's timestamps for "uh" are often 0.1–0.5 s off. Cuts never reach into neighbouring words
  and get a short audio fade.
- **Translation** works one whole sentence at a time, then splits each translation back over that
  sentence's subtitle lines at word boundaries.
- **Drafts.** Jianying 6+ encrypts drafts it saves, so jianjian never reads or edits an existing
  draft; it writes a new one.

[docs/DECISIONS.md](docs/DECISIONS.md) explains each design choice and the test result behind it.

## Capability report

Tested on an Apple Silicon Mac (48 GB RAM, Jianying Pro 11.5) with a 15-minute, two-speaker English
conversation recorded on a video call. A full run (transcribe, translate, draft, render) took about
4.5 minutes; expect roughly 15–20 minutes for a 60-minute episode.

**Fully automated and tested**

| Feature | Result on the test recording |
|---|---|
| Pause trimming | `conversation` preset: 15:00 → 12:20 together with filler cuts. Cuts snapped to the 1/30 s grid, never inside a word. |
| Filler words | 234 candidates; 117 uh/um and 28 stutter repeats cut automatically. Re-transcribing the edit: 0 real words cut, 13 of 118 uh/um still audible (mostly glued to a word). |
| Transcription | faster-whisper large-v3-turbo on the CPU, about 10× realtime, punctuated throughout |
| Bilingual subtitles | 258 lines; one text box per line in Jianying (no overlap when lines wrap); burned into the MP4 |
| Translation | Qwen2.5-7B via MLX, en → zh, about 0.4 s per sentence, 0 failed lines |
| Jianying draft | New draft in 本地草稿: 1 video track referencing the original file, 1 bilingual text track; opens in Jianying 11.5 |
| MP4 export | 1080p, 30 fps, VideoToolbox; duration exact, A/V sync within 10 ms at every probe (also at 1.05×) |
| Speed-up | 1.05×: subtitle starts vs spoken words median −3 ms, no drift |
| Cold open (`--hook`) | A line from 10:16 played first, as a teaser and moved (also with two hooks): the draft and MP4 open on it, its subtitles start at 0.07 s on the spoken word, all sync probes within 10 ms (also at 1.05×) |
| Validation | `report.md` lists each check; the command exits with code 2 if one fails |

**Partially automated**

- **Subtitle quality** needs the review pass above. On the test recording the review fixed 15
  transcript lines (names, a few mishearings) and about 30 real translation errors.
- **Contextual fillers** (like / so / you know / restarts) are listed for review: 36 of 84 were cut.
  The review also kept "repeats" that were really two speakers echoing each other.
- **Explainer cards** (`--cards`) are built but not yet tested on a real episode.
- **Chinese and mixed zh/en audio:** the code paths exist but are not yet tested on real audio.

**Manual**

- Exporting from inside Jianying (导出); jianjian's MP4 is the automated export.
- Edits made in Jianying after opening the draft. To change something automated, rerun jianjian;
  it creates a new draft.
- Listening to the cuts before publishing.

**Unsupported**

- Reading or re-editing drafts Jianying has saved (they are encrypted).
- Automated export through Jianying on macOS.
- Speaker labels (diarization).
- Jianying templates, stickers or effects; the draft holds video and text tracks only.

## Pitfalls

Every mistake found while building and using jianjian is written down here: what went wrong, why,
and what to do. [docs/DECISIONS.md](docs/DECISIONS.md) has the longer story behind each design
choice. **Add new pitfalls here as you find them.**

**Jianying**

- **Never update a draft in place; always add a new one.** Jianying encrypts `draft_info.json` only
  when it *saves*. A draft that is open in Jianying, or was opened without saving, still looks like
  untouched plain JSON — and Jianying later saves its in-memory copy over any change made on disk.
  "Still plain JSON" does not mean "never opened". (Signs it was opened: a `Timelines/` folder or a
  `.locked` file in the draft folder.)
- **Drafts point to media by absolute path.** Moving or renaming the source video (or an export
  left in Downloads) turns the clips "offline". Copy files to a stable folder before building a
  draft on them.
- **Two separate subtitle tracks overlapped** whenever a line wrapped: Jianying grows a text box up
  and down from its centre. Use one text box per subtitle with a style range per language.
- **Cut parts are hidden, not deleted.** Each clip plays a range of the original file, so the
  playhead jumps at every cut and a clip's edge can be dragged out to bring removed audio back.
  This is expected, not a bug.
- **Jianying exports 44.1 kHz stereo, about 3 dB quieter than a mono source.** Don't read that as
  an editing choice when comparing someone's export with jianjian's output.
- **A name clash renamed the staging draft even with `--no-install`,** so a manual copy picked up a
  stale folder. Fixed; always verify the installed draft, not just the copy step.

**Transcription**

- **`initial_prompt` only reaches the first 30-s window** (with `condition_on_previous_text=False`);
  after that, transcripts lost punctuation. Send the style prompt as `hotwords`.
- **Names or term lists in the prompt leak into the transcript** and can start a repetition loop
  that swallows real speech. Fix names during review instead.
- **PyAV 19 breaks faster-whisper 1.2.1** (`metadata_errors=` was removed). Keep `av<17`.
- **Whisper drops "uh/um" and mistimes the ones it keeps** (often 0.1–0.5 s off). Use a verbatim
  pass to find fillers and locate each one on the waveform before cutting.
- **Re-transcriptions misspell names** (e.g. a surname heard as a different word). Never match
  lines between two transcriptions by exact words; match by position and fuzzy similarity.

**Cutting**

- **Cuts landed inside audible sound.** The speech detector misses soft sounds (trailing
  syllables, breaths, short interjections), and a filler cut can nick the neighbouring word, so
  words sounded cut off. Now every cut edge is checked against the audio and moved to a quiet point
  (`jianjian/edges.py`); `report.md` lists how many edges still sit in sound. Listen to those.
- **Only the side that stays has to be quiet.** Requiring quiet on both sides of a cut edge dropped
  most filler cuts, because the removed side is the "uh" itself. Check the kept audio next to the
  edge.
- **Video-call recordings contain digital silence.** Call apps mute the line between words (exact
  zeros, about 5% of one test recording). A noise floor estimated with those frames sat at -120 dB,
  so every ordinary pause looked loud. Ignore digital silence, and compare against the speech level
  as well as the room tone.
- **Fillers glued to words have no quiet point,** only a narrow valley (often under 40 ms). Measure
  loudness at the exact cut frame, not the loudest frame nearby, or the valley is never found.
  Leaving glued fillers in was tried and rejected in a listening test (the stutters bothered more
  than the valley cuts, which didn't sound clipped), so they are cut at the valley.
- **A filler cut's edges must stay near the filler, and only move inward.** Letting them slide
  anywhere inside the cut found a quiet point *before* the filler (so it wasn't cut at all) or the
  dip *inside* a stutter like "have you" (so half of it stayed); letting them move 70 ms *outward*
  clipped the end of the neighbouring word ("because" -> "becau-"). Search only within 70 ms
  inside each boundary.
- **"30 dB below the speech" is not quiet.** A soft tail after a word (a fading syllable or a
  breath) 35-40 dB below the speech is still heard when a cut stops it abruptly, and a listener
  heard it as the word being cut off. Pause cuts now start and end only where the audio is 45 dB
  below the speech.
- **Metrics are not the ear.** "Cut edges in audible sound" dropped by a third, yet in a listening
  test the moved edges didn't sound better; the change that mattered was cutting the stutters. Let
  the listener decide between versions, and judge filler removal by the share of the filler's
  sound that is cut, not its time span.
- **Checking "no word was cut" by word midpoints misses clipped word edges.** Check the audio
  level at each cut edge too, and treat transcript timings for short words ("I", "and") with
  caution: they are often 50 ms off, so a word-edge overlap test flags cuts that are fine.
- **A broken measurement overstates the problem.** The first count of "cuts in audible sound"
  (200 of 227) used the digital-silence noise floor above; the corrected count was 153. Re-check a
  metric whenever its definition changes.
- **A hard pause threshold is uneven:** a pause just under the threshold stays longer than a long
  pause that was shortened. Use a preset that fits the content, or exact values.
- **`--no-cut` reported "removed 1 pauses/fillers, 0.016s" and a "custom" preset.** Keep ranges
  end on the frame grid, so the source's last partial frame (a few ms) is never used, and the
  stats counted that sliver as a cut. Measure removed time against the frame-grid end, not the raw
  duration, and report `--no-cut` as "no cuts" instead of falling back to the default pause values.

- **Repeated words are not always a restart.** A restart detector that looked for a phrase said
  twice within a few words also flagged plain repetition (sentences shaped like "it starts *at the*
  station and ends *at the* airport") and lists (shaped like "a red shirt or a red hat"). Require
  a break (comma, "...", dash or uh) in the abandoned part and no sentence end, and keep restarts
  as suggestions for review.
- **A word said twice across a sentence end is not a stutter.** The stutter detector cut "what do
  you call *this*? This is art" and "that's what it's *for*. For real" (the second speaker
  starts a new sentence with the same word), and a rule cutting a sentence-final "so" also took "I
  don't think *so*." Only cut a repeat when the first copy doesn't end a sentence, and review
  sentence-final discourse words one by one. The subtitle tidier had the same blind spot: it
  merged "for. For real" into "for. real" as if it were "the the".
- **Meta words occur in normal content.** Matching "recording" or "delete this part" flagged
  ordinary sentences and a joke about deleting a take. Match only unmistakable talk about the call
  ("is it recording", "can you hear me", "you're muted").
- **A restart cut can flip the meaning.** Cutting from the first copy of a phrase to the second
  turned a sentence shaped like "the report says, it's not, it *doesn't* say X"
  into "the report says X". It also drops list items ("if it rains, if it snows") and the
  subject of a quote ("she says, uh, you know, I quit…"). Review a restart by reading the
  sentence that is *left*, not the part that is removed; on a 90-minute test episode about a
  quarter of the suggested restarts had to be kept.
- **Two content cuts that touched left the speech between them in.** The verbatim transcript skipped
  4 s ("Okay, go ahead. If you're new here") between the end of one approved cut
  and the start of the next, so that stretch had no words to cut and stayed in the edit. Join
  content cuts that have no kept word between them into one span.
- **A request for B-roll can be missing from one transcript.** The clean transcript dropped a
  request to show a clip (the verbatim one had it) and misheard "clip" as "cliff" elsewhere.
  Look for insert points in every transcript there is, and match the request ("we could play it"),
  not only the noun.
- **Mapping a moment inside a cut to the edit assumed the edit was one stretch of the recording.**
  With inserted clips it is several, so a B-roll request inside a cut was reported 20 minutes late
  (after the last clip) instead of where its clip plays. Map such a moment to the stretch that
  starts before it.

**Subtitles and translation**

- **Translating several lines per request let the model shift text into the neighbouring line.**
  Translate one sentence at a time and split it back over its lines.
- **Subtitle text must follow the final edit, not an earlier one.** When someone edits the video
  further (e.g. in Jianying), rebuild each line's text from the edited video's own audio. Patching
  the old text fails: a stutter copy that is already shown once gets deleted again, and a cut that
  spans several lines is missed.
- **Placing old subtitle lines on a new edit by matching words leaves gaps** when words are
  misheard. Give every spoken word to exactly one line and close any gap by position.
- **Stretching a subtitle over a leftover word without changing its text** shows text that
  doesn't match the speech. Put the word into the line's text, or move the line boundary.
- **A transcript can silently skip a sentence.** Transcribing a whole long file once heard a full
  sentence as "Mm-hmm", so the sentence looked cut and its subtitle was dropped, and the coverage
  check (built on the same transcript) missed it too. Never treat "not in the transcript" as "cut"
  without checking the audio, and check subtitle coverage against the audio itself (speech
  detection), not against the transcript the subtitles came from.
- **Removing a cut word from a subtitle removed a word that is still spoken.** Subtitle text comes
  from the clean transcript, which often already leaves a restart out ("it took a, maybe a
  whole week" is written "it took maybe a whole week"); stripping the cut "a" again took the real
  one ("it took maybe whole week"). Only strip a word when the line shows it more often than the edited
  audio still says it.
- **Saved translations were looked up by each line's text before filler words were removed,** but
  saved with the text after, so about 40% of the lines were translated again on every run (2+
  minutes, and the wording changed between runs). Match saved translations after that step.
- **Subtitles leave out "uh/um", stutters and filler "you know / like / so"** on purpose. Keep the
  meaningful uses ("I like this", "fruit like apples").

**Render and checks**

- **Cropping a clip to fill the frame would cut off the film's own subtitles.** A screen recording of a
  film has the subtitles in the black bar under the picture. Inserted clips are scaled to fit and
  padded, never cropped.
- **An inserted clip split a keep range one frame before the cut began,** so 33 ms of the next word
  played right after the clip. Word times are only roughly right, so "the start of the word after"
  can sit a frame inside the kept audio. Snap an insert point within 0.3 s of a keep range's edge
  to that edge.
- **A subtitle that ends exactly where an inserted clip starts showed on the clip's first frame**
  (times on the sped-up timeline aren't on the frame grid). Keep subtitle lines a frame clear of
  inserted clips.

- **Homebrew's ffmpeg 8+ has no libass,** so subtitles couldn't be burned in. Prefer an ffmpeg
  with libass (imageio-ffmpeg's build has it).
- **Rounding each cut to 16 kHz on its own drifts a few samples per cut** and caused false sync
  failures. Build the reference audio sample-exact.
- **Sped-up audio can't be compared by waveform** (atempo output differs between sample rates);
  compare loudness envelopes.

**Models**

- **Qwen2.5-3B is not open source** ("qwen-research" license). The low-RAM fallback is Qwen2.5-1.5B.

## Troubleshooting

| Problem | Fix |
|---|---|
| `jianjian is not set up yet` | `bash setup.sh` |
| `jianjian: command not found` | Add `~/.local/bin` to your PATH, or run `bin/jianjian` from the repo |
| Draft doesn't appear in Jianying | Go back to the Jianying home page or restart Jianying, then check `report.md` → "Installed at" |
| Clips show as missing/offline in Jianying | The source video was moved or renamed. Put it back, or rerun jianjian. |
| Model download fails or is slow | Setup is resumable, so re-run it. In mainland China, `export HF_ENDPOINT=https://hf-mirror.com` first. |
| Subtitles too long | `--max-chars 16` for shorter lines |
| Cuts feel too aggressive | A gentler preset (`podcast`, `interview`), or raise `--keep-pause` |
| Wrong language on a section | `--lang zh` for an all-Chinese show, or fix the lines in `cues.json` and rerun with `--cues` |
| No burned-in subtitles in the MP4 | No ffmpeg with libass was found. jianjian prefers an ffmpeg with libass and falls back to the one bundled with imageio-ffmpeg; Homebrew's ffmpeg 8+ has none. Re-run `setup.sh`, or set `JIANJIAN_FFMPEG` to an ffmpeg with libass. |
| `ERROR: need an arm64 Python` | `brew install python@3.12`, or install `uv` |

## Contributing

Issues and pull requests are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md). Run the unit tests
with `.venv/bin/python -m pytest` (they need no models).

## License

jianjian is released under the [MIT License](LICENSE). It bundles pyJianYingDraft (Apache-2.0) and
downloads third-party models and packages under their own licenses; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
