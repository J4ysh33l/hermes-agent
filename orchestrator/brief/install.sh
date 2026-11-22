#!/usr/bin/env bash
# Install the morning brief into a Hermes home. Safe to re-run; never overwrites brief.yaml.
# Usage: orchestrator/brief/install.sh            (HERMES_HOME defaults to ~/.hermes)
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(git -C "$HERE" rev-parse --show-toplevel)"
HOME_DIR="${HERMES_HOME:-$HOME/.hermes}"

mkdir -p "$HOME_DIR/brief" "$HOME_DIR/scripts" "$HOME_DIR/plugins"
chmod 700 "$HOME_DIR/brief"

if [ ! -f "$HOME_DIR/brief/brief.yaml" ]; then
    cp "$HERE/brief.example.yaml" "$HOME_DIR/brief/brief.yaml"
    echo "created $HOME_DIR/brief/brief.yaml (edit topics and markets there)"
fi

sed "s|@REPO_ROOT@|$REPO_ROOT|" "$HERE/launcher.py.template" > "$HOME_DIR/scripts/morning_brief.py"
echo "wrote   $HOME_DIR/scripts/morning_brief.py"

ln -sfn "$HERE/plugin" "$HOME_DIR/plugins/brief"
echo "linked  $HOME_DIR/plugins/brief -> $HERE/plugin"

cat <<NEXT

Next (run these yourself):
  hermes plugins enable brief
  hermes cron create "15 8 * * *" --timezone Asia/Kolkata --no-agent \\
      --script morning_brief.py --deliver telegram --name morning-brief
  python -m orchestrator.brief run --dry-run      # from $REPO_ROOT: preview without saving
NEXT
