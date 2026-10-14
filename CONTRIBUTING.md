# Contributing

Thanks for helping. A few things make reviews quick:

- **Discuss big changes first** in an issue, especially anything touching the Jianying draft
  format, timing/sync, or the review workflow.
- **Read [docs/DECISIONS.md](docs/DECISIONS.md)** before changing how transcription, cutting,
  translation or rendering works. Several obvious alternatives were tried and failed; the file says
  why.
- **Run the unit tests**: install pytest once (`uv pip install --python .venv/bin/python -r requirements-dev.txt`,
  or `.venv/bin/python -m pip install -r requirements-dev.txt`), then
  `.venv/bin/python -m pytest`. They run in seconds and need no models.
- **Test on a real recording** for changes to the pipeline, and include what you checked in the
  pull request: `report.md`'s sync checks, and `tools/verify_words.py` for filler changes.
- **Never commit media or personal data**: no videos, audio, transcripts or `*_edit/` folders.
  Personal notes belong in `STATUS.md`, which git ignores.
- **Keep it local and free**: no paid services or API keys in the default path, and models and
  packages must have open-source licenses (see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)).
- **Match the surrounding code**: plain Python, short functions, comments that explain *why*.

By contributing you agree that your contribution is licensed under the MIT License.
