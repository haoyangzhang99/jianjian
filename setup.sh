#!/usr/bin/env bash
# One-time setup for jianjian on an Apple Silicon Mac. Safe to re-run.
# - creates a private Python environment in ./.venv (nothing installed system-wide)
# - installs faster-whisper, mlx-lm, opencc, imageio-ffmpeg
# - downloads the Whisper and translation models into the Hugging Face cache (~/.cache/huggingface)
# - links the agent skill into ~/.agents/skills, ~/.codex/skills and ~/.claude/skills (if those exist)
# - links the `jianjian` command into ~/.local/bin
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
VENV="$HERE/.venv"
say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

say "Checking machine"
echo "macOS $(sw_vers -productVersion 2>/dev/null || echo '?') on $(uname -m)"
[[ "$(uname -s)" == "Darwin" ]] || echo "WARNING: not macOS — Jianying install and MLX translation won't work"
[[ "$(uname -m)" == "arm64" ]] || echo "WARNING: not Apple Silicon — MLX translation won't work"
RAM_GB=$(( $(sysctl -n hw.memsize 2>/dev/null || echo 8589934592) / 1073741824 ))
FREE_GB=$(df -g "$HOME" | awk 'NR==2 {print $4}')
echo "RAM: ${RAM_GB} GB   free disk: ${FREE_GB} GB"
if (( RAM_GB >= 16 )); then MT_MODEL="mlx-community/Qwen2.5-7B-Instruct-4bit"; MT_GB=4.3
else MT_MODEL="mlx-community/Qwen2.5-1.5B-Instruct-4bit"; MT_GB=0.9; fi  # 3B is not Apache-2.0
echo "Models to download (first run only): Whisper large-v3-turbo ~1.6 GB, $MT_MODEL ~${MT_GB} GB, Python packages ~1 GB"
if (( FREE_GB < 12 )); then echo "ERROR: need at least 12 GB free disk"; exit 1; fi

say "Python environment"
if [[ ! -x "$VENV/bin/python" ]]; then
  if command -v uv >/dev/null 2>&1; then
    uv venv --python 3.12 "$VENV"
  else
    PY=""
    for c in python3.12 python3.11 python3.13 python3.10 /opt/homebrew/bin/python3 "$HOME/.homebrew/bin/python3" python3; do
      p=$(command -v "$c" 2>/dev/null || true); [[ -n "$p" ]] || continue
      ok=$("$p" -c 'import sys,platform; print(int((3,10)<=sys.version_info[:2]<=(3,13) and platform.machine()=="arm64"))' 2>/dev/null || echo 0)
      if [[ "$ok" == "1" ]]; then PY="$p"; break; fi
    done
    if [[ -z "$PY" ]]; then
      echo "ERROR: need an arm64 Python 3.10–3.13. Install one with:  brew install python@3.12"
      exit 1
    fi
    echo "using $PY ($("$PY" --version))"
    "$PY" -m venv "$VENV"
  fi
fi
"$VENV/bin/python" -m pip install -q --upgrade pip 2>/dev/null || true
if command -v uv >/dev/null 2>&1; then PIP=(uv pip install --python "$VENV/bin/python"); else PIP=("$VENV/bin/python" -m pip install); fi
"${PIP[@]}" -q -r "$HERE/requirements.txt"
"$VENV/bin/python" -c "import faster_whisper, mlx_lm, opencc; print('packages OK: faster-whisper', faster_whisper.__version__)"

say "Downloading models (cached; skipped if already present)"
"$VENV/bin/python" - "$MT_MODEL" <<'PY'
import sys
from huggingface_hub import snapshot_download
for repo in ["mobiuslabsgmbh/faster-whisper-large-v3-turbo", sys.argv[1]]:
    print("model:", repo, flush=True)
    snapshot_download(repo)
print("models OK")
PY

say "Agent skill"
chmod +x "$HERE/bin/jianjian" "$HERE/first_run.sh" 2>/dev/null || true
for d in "$HOME/.agents/skills" "$HOME/.codex/skills" "$HOME/.claude/skills"; do
  parent="$(dirname "$d")"
  if [[ -d "$parent" ]]; then
    mkdir -p "$d"
    if [[ -L "$d/jianjian" || ! -e "$d/jianjian" ]]; then
      ln -sfn "$HERE/skill" "$d/jianjian"; echo "linked skill -> $d/jianjian"
    else
      echo "skipped $d/jianjian (exists and is not our link)"
    fi
  fi
done

say "Command"
mkdir -p "$HOME/.local/bin"
if [[ -L "$HOME/.local/bin/jianjian" || ! -e "$HOME/.local/bin/jianjian" ]]; then
  ln -sfn "$HERE/bin/jianjian" "$HOME/.local/bin/jianjian"; echo "linked command -> ~/.local/bin/jianjian"
else
  echo "skipped ~/.local/bin/jianjian (exists and is not our link)"
fi
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo "NOTE: add ~/.local/bin to your PATH to run 'jianjian' from anywhere";; esac

say "Environment check"
"$HERE/bin/jianjian" doctor || true
echo
echo "Setup complete. Try:  jianjian presets   then   jianjian edit \"/path/to/episode.mp4\" --preset conversation"
