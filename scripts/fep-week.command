#!/bin/bash
#
# The weekly run, as one double-click.
#
#   1. pull results, scores and ESPN weights, run the model, snapshot the week
#   2. rebuild the dashboard
#   3. commit the season file
#   4. open the dashboard
#
# Live in scripts/ so it is version controlled; the Desktop holds a symlink to
# it. Finder runs it from wherever the symlink sits, so the first thing it does
# is find its own repo rather than trust the working directory.

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
# run is recorded. This is local only -- it never pushes.
if [ -n "$(git status --porcelain data newsletters chart-data 2>/dev/null)" ]; then
  git add data newsletters chart-data
  git commit -q -m "The weekly run, $(date '+%Y-%m-%d')" && echo "  saved to git"
fi

echo
open dashboard/index.html
