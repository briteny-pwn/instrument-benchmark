#!/bin/sh
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$HERE"
python3 ../../evaluator/run_instance.py . --mode apply-gold
