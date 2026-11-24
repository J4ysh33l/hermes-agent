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
sed "s|@REPO_ROOT@|$REPO_ROOT|" "$REPO_ROOT/orchestrator/outreach/launcher.py.template" \
    > "$HOME_DIR/scripts/outreach_draft.py"
echo "wrote   $HOME_DIR/scripts/outreach_draft.py (Hermes' agent drafts Slack messages and meetings)"
sed "s|@REPO_ROOT@|$REPO_ROOT|" "$REPO_ROOT/orchestrator/hr/launcher.py.template" > "$HOME_DIR/scripts/hr_payslips.py"
mkdir -p "$HOME_DIR/hr/templates" && chmod 700 "$HOME_DIR/hr"
echo "wrote   $HOME_DIR/scripts/hr_payslips.py (put your payslip.docx in $HOME_DIR/hr/templates/)"
sed "s|@REPO_ROOT@|$REPO_ROOT|" "$REPO_ROOT/orchestrator/hr/inbox_launcher.py.template" > "$HOME_DIR/scripts/hr_inbox.py"
echo "wrote   $HOME_DIR/scripts/hr_inbox.py (HR inbox sweep; needs hr.mailbox in brief.yaml)"

mkdir -p "$HOME_DIR/myday" && chmod 700 "$HOME_DIR/myday"
if [ ! -f "$HOME_DIR/myday/myday.yaml" ]; then
    cp "$REPO_ROOT/orchestrator/myday/myday.example.yaml" "$HOME_DIR/myday/myday.yaml"
    echo "created $HOME_DIR/myday/myday.yaml (times, points, goals review day)"
fi
for job in morning tick; do
    sed -e "s|@REPO_ROOT@|$REPO_ROOT|" -e "s|@COMMAND@|$job|" "$REPO_ROOT/orchestrator/myday/launcher.py.template" \
        > "$HOME_DIR/scripts/myday_$job.py"
done
echo "wrote   $HOME_DIR/scripts/myday_morning.py and myday_tick.py (My day: card, reminders, bills from Gmail)"

sed "s|@REPO_ROOT@|$REPO_ROOT|" "$REPO_ROOT/orchestrator/recap/launcher.py.template" > "$HOME_DIR/scripts/deadline_recap.py"
echo "wrote   $HOME_DIR/scripts/deadline_recap.py (the 20:00 deadline recap)"

sed "s|@REPO_ROOT@|$REPO_ROOT|" "$REPO_ROOT/orchestrator/notes/launcher.py.template" > "$HOME_DIR/scripts/smriti.py"
mkdir -p "$HOME_DIR/notes" && chmod 700 "$HOME_DIR/notes"
echo "wrote   $HOME_DIR/scripts/smriti.py (Smriti: meeting notes; needs ffmpeg and the Teams permissions)"

# Older installs linked plugins/brief; the plugin is now one for every orchestrator command.
[ -L "$HOME_DIR/plugins/brief" ] && rm "$HOME_DIR/plugins/brief"
ln -sfn "$REPO_ROOT/orchestrator/plugin" "$HOME_DIR/plugins/orchestrator"
echo "linked  $HOME_DIR/plugins/orchestrator -> $REPO_ROOT/orchestrator/plugin"

cat <<NEXT

Next (run these yourself):
  hermes plugins enable orchestrator
  hermes cron create "15 8 * * *" --timezone Asia/Kolkata --no-agent \\
      --script morning_brief.py --deliver telegram --name morning-brief
  hermes cron create "30 7 * * *" --timezone Asia/Kolkata --no-agent \\
      --script myday_morning.py --deliver telegram --name myday-morning
  hermes cron create "*/15 * * * *" --timezone Asia/Kolkata --no-agent \\
      --script myday_tick.py --deliver telegram --name myday-tick
  hermes cron create "0 10,17 * * *" --timezone Asia/Kolkata --no-agent \\
      --script hr_inbox.py --deliver telegram --name hr-inbox
  hermes cron create "0 20 * * *" --timezone Asia/Kolkata --no-agent \\
      --script deadline_recap.py --deliver telegram --name deadline-recap
  hermes cron create "*/15 * * * *" --timezone Asia/Kolkata --no-agent \\
      --script smriti.py --deliver telegram --name smriti
  python -m orchestrator.brief run --dry-run      # from $REPO_ROOT: preview without saving
NEXT
