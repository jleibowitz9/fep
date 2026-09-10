#!/bin/bash
#
# The FEP app, as one double-click.
#
# Starts the local server that puts the model behind the dashboard's buttons
# and opens the page. Everything the weekly run does is a button once this is
# running: the ESPN pull, the model, the snapshot, the stat pack, the chart,
# the Sheet, the CMS and the commit.
#
# This window is the app. Leave it open while you use the page; closing it, or
# Ctrl-C, or Quit on the page itself, all stop the server.
#
# Lives in scripts/ so it is version controlled; the Desktop and the Dock hold
# pointers to it. Finder runs a double-clicked script from the home directory,
# not from the repo, so the first thing it does is find its own repo.

cd "$(dirname "$(readlink "$0" || echo "$0")")/.." || exit 1

python3 dashboard/serve.py

echo
echo "Press return to close this window."
read -r
