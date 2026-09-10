#!/bin/bash
#
# Retry the push on its own, when the weekly run committed but could not send.
# Same reason it needs a token: the machine's active gh account is the work
# one, and this is a personal repo.

cd "$(dirname "$(readlink "$0" || echo "$0")")/.." || exit 1

AHEAD="$(git log origin/main..HEAD --oneline 2>/dev/null | wc -l | tr -d ' ')"
if [ "$AHEAD" = "0" ]; then
  echo "Nothing to push. GitHub already has everything."
else
  echo "Pushing $AHEAD commit(s):"
  git log origin/main..HEAD --oneline
  echo
  TOKEN="$(gh auth token --user jleibowitz9 2>/dev/null)"
  if [ -z "$TOKEN" ]; then
    echo "No token for jleibowitz9. Run: gh auth login --user jleibowitz9"
  elif GH_TOKEN="$TOKEN" git push origin main; then
    echo "Pushed."
  else
    echo "Push failed. The commits are safe locally."
  fi
  unset TOKEN
fi

echo
echo "Press return to close this window."
read -r
