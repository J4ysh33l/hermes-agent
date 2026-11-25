#!/usr/bin/env bash
# The editor as its own Hermes profile ("editor"), sharing the studio's install (venv, models, Remotion).
# Usage: orchestrator/edit/install.sh            (after orchestrator/studio/install.sh --omnivoice)
set -euo pipefail

REPO="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
MAIN="${HERMES_HOME:-$HOME/.hermes}"
EDITOR_HOME="$MAIN/profiles/editor"

if [ ! -d "$EDITOR_HOME" ]; then
    hermes profile install "$REPO/orchestrator/edit/profile" --name editor -y
    echo "ready   profile editor in $EDITOR_HOME"
else
    echo "have    profile editor in $EDITOR_HOME"
fi
mkdir -p "$EDITOR_HOME/brief" "$EDITOR_HOME/edit/styles" "$EDITOR_HOME/edit/brand" "$EDITOR_HOME/edit/jobs"
if [ ! -f "$EDITOR_HOME/brief/brief.yaml" ]; then
    sed "s#/home/ubuntu/.hermes#$MAIN#g" "$REPO/orchestrator/edit/profile/brief.yaml.example" > "$EDITOR_HOME/brief/brief.yaml"
    echo "wrote   $EDITOR_HOME/brief/brief.yaml (set studio.handoff_repo)"
fi

[ -x "$MAIN/venvs/studio/bin/python" ] || echo "note    run orchestrator/studio/install.sh --omnivoice first (Whisper lives in the studio venv)"
[ -d "$REPO/orchestrator/studio/remotion/node_modules/@fontsource/manrope" ] || \
    (cd "$REPO/orchestrator/studio/remotion" && npm ci --no-audit --no-fund)
command -v ffmpeg >/dev/null || echo "note    install ffmpeg (sudo apt install ffmpeg)"
fc-list 2>/dev/null | grep -qi emoji || echo "note    for emoji graphics: sudo apt install fonts-noto-color-emoji"

echo
echo "Add the queue to cron (crontab -e), every 5 minutes, one pass at a time:"
echo "*/5 * * * * cd $REPO && HERMES_HOME=$EDITOR_HOME $(command -v python3) -m orchestrator.edit queue >> $EDITOR_HOME/edit/run.log 2>&1"
echo
echo "Then: $EDITOR_HOME/.env (a second Telegram bot, your user id, the handoff token), start its gateway"
echo "(editor gateway start), and send /edit styles."
