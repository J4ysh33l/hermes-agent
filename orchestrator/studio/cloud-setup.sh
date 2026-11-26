#!/usr/bin/env bash
# Setup script for a Claude Code cloud environment (paste it under the environment's Setup script, or
# run it on any fresh Linux box). It makes a new container ready for the studio before the session
# starts, so nothing is reinstalled by hand:
#   - the studio's voice environment, Kokoro and OmniVoice (+ its half-size copy) and Whisper models,
#     in $HERMES_HOME (Hermes' own install.sh --omnivoice; ~1.9 GB packages + ~2.6 GB models)
#   - Remotion's packages and its Chrome in $SRC; the session's checkout links to them (see the last line)
#   - $HERMES_HOME/brief/brief.yaml for the studio (only when there is none)
# It needs no secrets: the repo is public and the setup script cannot read the environment's
# variables anyway. Tokens (GITHUB_HANDOFF_TOKEN, CLAUDE_ROUTINE_URL/TOKEN) stay in the environment's
# variables. Your voice file is not here: copy it to $HERMES_HOME/studio/voices/me.pt in the session.
# Safe to re-run: install.sh skips what is already there.
set -euo pipefail
export HERMES_HOME="${HERMES_HOME:-/home/user/faceless-home}"
SRC=/opt/hermes-setup
REPO="${HERMES_REPO:-https://github.com/J4ysh33l/hermes-agent.git}"

if [ -d "$SRC/.git" ]; then
    git -C "$SRC" fetch -q --depth 1 origin main && git -C "$SRC" reset -q --hard FETCH_HEAD
else
    git clone -q --depth 1 "$REPO" "$SRC"
fi

mkdir -p "$HERMES_HOME/brief" "$HERMES_HOME/studio/voices"
bash "$SRC/orchestrator/studio/install.sh" --omnivoice   # voice env + models, then npm install in $SRC

if [ ! -f "$HERMES_HOME/brief/brief.yaml" ]; then
    cat > "$HERMES_HOME/brief/brief.yaml" <<'EOF'
studio:
  engine: omnivoice
  writer: claude
  claude_via: handoff
  handoff_repo: J4ysh33l/hermes-handoffs
  research: true
  threads: 4
  video_concurrency: 2
EOF
fi
echo "ready   HERMES_HOME=$HERMES_HOME (voice env, models, brief.yaml); Remotion in $SRC"
echo "Next, in the session: ln -s $SRC/orchestrator/studio/remotion/node_modules orchestrator/studio/remotion/node_modules; copy your me.pt"
