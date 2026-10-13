#!/usr/bin/env bash
# Sets up the server venv and symlinks the add-in into Fusion's AddIns folder (macOS).
set -euo pipefail
cd "$(dirname "$0")"

python3 -m venv .venv
.venv/bin/pip install -q "mcp[cli]>=1.2,<2"

ADDINS="$HOME/Library/Application Support/Autodesk/Autodesk Fusion 360/API/AddIns"
mkdir -p "$ADDINS"
ln -sfn "$PWD/addin/FusionMCP" "$ADDINS/FusionMCP"

echo "Add-in linked: $ADDINS/FusionMCP"
echo "Register the server with Claude Code:"
echo "  claude mcp add fusion -- $PWD/.venv/bin/python $PWD/server/server.py"
