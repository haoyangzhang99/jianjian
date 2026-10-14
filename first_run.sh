#!/usr/bin/env bash
# First run on a new Mac: setup, then a full edit of one video, everything logged to logs/.
#   bash first_run.sh "/path/to/episode.mp4" [preset]      (preset: see `bin/jianjian presets`)
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
VIDEO="${1:?usage: bash first_run.sh /path/to/video.mp4 [preset]}"
PRESET="${2:-conversation}"
mkdir -p "$HERE/logs"
LOG="$HERE/logs/first_run_$(date +%Y%m%d-%H%M%S).log"
{
  echo "first run started $(date)"
  bash "$HERE/setup.sh" && \
  "$HERE/bin/jianjian" edit "$VIDEO" --preset "$PRESET"
  echo "EXIT CODE: $?"
  echo "finished $(date)"
} 2>&1 | tee "$LOG"
echo
echo "Log saved to: $LOG"
