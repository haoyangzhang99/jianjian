# Agent instructions (Codex / Claude Code)

This folder is a local podcast-editing pipeline for Jianying Pro. The full usage guide for agents is
`skill/SKILL.md` — read it before running anything. Short version:

- Before editing a new video, ask the user which pause preset to use (`bin/jianjian presets`;
  skill/SKILL.md §0). There is no default, and the tool refuses to run without one.
- Run jobs with `bin/jianjian edit "<video>" --preset NAME [flags]`; check `<video>_edit/report.md` afterwards.
- `bin/jianjian doctor` checks the environment; `bash setup.sh` installs/repairs it.
- Don't touch the source video or existing Jianying drafts; jianjian only adds new drafts.
- Read docs/DECISIONS.md before changing the pipeline; run `.venv/bin/python -m pytest` after.
- Personal notes (episodes, names, paths) go in STATUS.md (git-ignored), never in tracked files.
- Code: `jianjian/` (cli, asr, cuts, fillers, subs, translate, draft, render, validate, cards);
  `vendor/pyJianYingDraft` is upstream pyJianYingDraft (Apache-2.0, commit in UPSTREAM_COMMIT).
