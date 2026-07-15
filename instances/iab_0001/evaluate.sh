#!/bin/sh
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$HERE"
if [ "$#" -gt 0 ]; then python3 ../../evaluator/run_instance.py . --mode evaluate --patch "$1"; else python3 ../../evaluator/run_instance.py . --mode evaluate; fi
