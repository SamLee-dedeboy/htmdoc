#!/bin/bash
# Double-click this file to start the htmdoc helper.
# Leave the window it opens running while you edit; close it when you're done.
#
# Pass options after double-clicking isn't possible, so edit the last line to
# add flags if you need them, e.g.:  exec python3 htmdoc.py --root ~/Documents
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then
  exec python3 htmdoc.py "$@"
else
  echo "Python 3 was not found. Install it once from https://www.python.org/downloads/"
  echo "then double-click this file again."
  read -r -p "Press Return to close."
fi
