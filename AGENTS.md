# Agent instructions (Codex / Claude Code)

This folder is a local podcast-editing pipeline for Kdenlive (default) and Jianying Pro. The full usage guide for agents is
`skill/SKILL.md` — read it before running anything. Short version:

- Before editing a new video, ask the user which pause preset to use (`bin/jianjian presets`;
  skill/SKILL.md §0). There is no default, and the tool refuses to run without one.
- For Douyin / Xiaohongshu / Shorts, suggest the 3 / 15 / 30 s opening plan (hook, value,
  structure) and build the deliverable to it (skill/SKILL.md §0b).
- Run jobs with `bin/jianjian edit "<video>" --preset NAME [flags]`; check `<video>_edit/report.md` afterwards.
- `bin/jianjian doctor` checks the environment; `bash setup.sh` installs/repairs it.
- Don't touch the source video, existing Kdenlive projects or Jianying drafts; jianjian only adds new ones.
- Read docs/DECISIONS.md before changing the pipeline; run `.venv/bin/python -m pytest` after.
- Personal notes (episodes, names, paths) go in STATUS.md (git-ignored), never in tracked files.
- Every mistake or pitfall you hit goes into README.md → "Pitfalls" in the same change: what went
  wrong, why, and what to do (no personal details).
- Code: `jianjian/` (cli, asr, cuts, fillers, subs, translate, kdenlive, draft, render, validate, cards,
  animations);
  `vendor/pyJianYingDraft` is upstream pyJianYingDraft (Apache-2.0, commit in UPSTREAM_COMMIT).
