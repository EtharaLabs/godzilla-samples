#!/usr/bin/env bash
# Oracle: the original project source (with vendored dependencies) and a compile.sh
# that rebuilds it offline. Proves the task is solvable through the agent's own
# interface; it does not measure agent capability.
set -euo pipefail
cd /workspace
cp -R /solution/reference/. /workspace/
# Large trees (vendored crates) would trigger git's automatic gc in the background, racing Harbor's copy of /workspace.
git -c gc.auto=0 add -A >/dev/null 2>&1 && git -c gc.auto=0 commit -qm "Reference solution" >/dev/null 2>&1
