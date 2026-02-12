#!/usr/bin/env bash
set -euo pipefail

export TZ=Asia/Shanghai

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT_DIR/logs"
mkdir -p "$LOG_DIR"

# Avoid overlapping runs (hourly cron + manual triggers).
LOCK_FILE="$ROOT_DIR/.run.lock"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "$(date -Iseconds) locked; skip" >>"$LOG_DIR/cron.log"
  exit 0
fi

# Load keys without hardcoding secrets into the repo.
if [[ -f "$HOME/.openclaw/.env" ]]; then
  set -a
  # shellcheck disable=SC1090
  . "$HOME/.openclaw/.env"
  set +a
fi

if [[ -z "${BRAVE_API_KEY:-}" ]]; then
  echo "Missing BRAVE_API_KEY (set it in env or ~/.openclaw/.env)" >&2
  exit 2
fi

cd "$ROOT_DIR"

# Keep repo in sync.
git pull --rebase --autostash >>"$LOG_DIR/git.log" 2>&1 || true

# Generate a snapshot (writes a timestamped archive under docs/d/).
python3 scripts/generate.py >>"$LOG_DIR/generate.log" 2>&1

# Commit + push if anything changed.
git add docs
if git diff --cached --quiet; then
  echo "$(date -Iseconds) no changes" >>"$LOG_DIR/cron.log"
  exit 0
fi

git commit -m "chore: intel snapshot $(date '+%F %H:%M %Z')" >/dev/null

git push >>"$LOG_DIR/git.log" 2>&1

echo "$(date -Iseconds) pushed" >>"$LOG_DIR/cron.log"
