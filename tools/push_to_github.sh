#!/usr/bin/env bash
# Push the prepared commits to remontsuri/world-of-claudecraft-agent (branch: backup only).
#
# The token is read from the environment and handed to git through an inline
# credential helper, so it never lands in .git/config, in argv, or in shell history.
#
#   GH_TOKEN=<pat> bash tools/push_to_github.sh
set -euo pipefail

REMOTE=https://github.com/remontsuri/world-of-claudecraft-agent.git
BRANCH=${BRANCH:-backup}
REPO=/home/user/push/woc-agent

: "${GH_TOKEN:?GH_TOKEN is not set}"

cd "$REPO"
echo "== branch/HEAD before push =="
git status -sb | head -3
git log --oneline -3

echo "== remote refs =="
git -c credential.helper='!f() { echo username=x-access-token; echo password="$GH_TOKEN"; }; f' \
    ls-remote "$REMOTE" "refs/heads/$BRANCH"

echo "== push =="
git -c credential.helper='!f() { echo username=x-access-token; echo password="$GH_TOKEN"; }; f' \
    push "$REMOTE" "$BRANCH:$BRANCH"

echo "== verify =="
git -c credential.helper='!f() { echo username=x-access-token; echo password="$GH_TOKEN"; }; f' \
    ls-remote "$REMOTE" "refs/heads/$BRANCH"
echo "local HEAD: $(git rev-parse HEAD)"
