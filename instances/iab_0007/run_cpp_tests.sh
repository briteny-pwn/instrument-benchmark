#!/bin/sh
set -eu
layer=${1:?layer required}
repo=${IAB_REPOSITORY:?IAB_REPOSITORY required}
cxx=${CXX:-c++}
mkdir -p .work/cpp
$cxx -std=c++17 -Wall -Wextra tests/contract_main.cpp -o .work/cpp/iab_adapter_tests
IAB_TRACE_PATH="${IAB_TRACE_PATH:-.work/state_trace.trace.json}" .work/cpp/iab_adapter_tests "$layer" "$repo"
