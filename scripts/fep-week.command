#!/bin/bash
#
# The weekly run, as one double-click.
#
#   1. pull results, scores and ESPN weights, run the model, snapshot the week
#   2. rebuild the dashboard
#   3. commit the season file and push it to GitHub
#   4. open the dashboard
#
# Lives in scripts/ so it is version controlled; the Desktop and the Dock hold
# pointers to it. Finder runs a double-clicked script from the home directory,
# not from the repo, so the first thing it does is find its own repo.

cd "$(dirname "$(readlink "$0" || echo "$0")")/.." || exit 1

pause_and_exit() {
  echo
  echo "$1"
  echo "Press return to close this window."
  read -r
  exit 1
}

echo "FEP weekly run"
echo "$(pwd)"
echo

python3 cli.py week || pause_and_exit "The run failed. Nothing was written."

echo
python3 cli.py dashboard || pause_and_exit "The board updated, but the dashboard did not build."

# The season file is the one thing here that cannot be regenerated, so every
# run is recorded and sent off the machine. Only the run's own outputs are
# staged, and it is the run that says which those are: staging the three
# directories whole would sweep up whatever another session had part-finished
# in them. Without a manifest -- an older run, or a failure before it was
# written -- fall back to the directories, which is what this always did.
PATHS="$(python3 -c 'from fep import manifest
m = manifest.read()
print(" ".join(m["paths"]) if m and m["paths"] else "data newsletters chart-data")' 2>/dev/null)"
[ -z "$PATHS" ] && PATHS="data newsletters chart-data"

# Every step is checked. This used to run `git commit ... && echo saved`, which
# printed nothing at all on failure and carried straight on to the push, so a
# run that committed nothing looked exactly like one that had.
if [ -n "$(git status --porcelain $PATHS 2>/dev/null)" ]; then
  if ! git add $PATHS; then
    pause_and_exit "The run finished, but git could not stage it. Nothing was saved."
  fi
  if git commit -q -m "The weekly run, $(date '+%Y-%m-%d')"; then
    echo "  saved to git"
  else
    pause_and_exit "The run finished, but git could not commit it. Nothing was saved."
  fi
fi

# This is a personal repo, but the machine's active gh account is the work one,
# so a plain push authenticates as the wrong user and is refused. Ask gh for
# the personal token at run time: it lives in the keychain gh already manages,
# stays in this process, and is never written anywhere.
if git log origin/main..HEAD --oneline 2>/dev/null | grep -q .; then
  TOKEN="$(gh auth token --user jleibowitz9 2>/dev/null)"
  if [ -z "$TOKEN" ]; then
    echo "  could not reach the jleibowitz9 token; run: gh auth login --user jleibowitz9"
  elif GH_TOKEN="$TOKEN" git push -q origin main 2>/dev/null; then
    echo "  pushed to GitHub"
  else
    echo "  push failed; the commit is safe locally, run scripts/fep-push.command to retry"
  fi
  unset TOKEN
fi

echo
open dashboard/index.html
