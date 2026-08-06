#!/bin/sh
set -eu

test "$(uname -s)" = "Linux"
test "$(uname -m)" = "x86_64"
test -S /var/run/docker.sock

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
instrument_root=$(CDPATH= cd -- "$script_dir/.." && pwd)
checkout_parent=$(dirname -- "$instrument_root")
config_arg=${1:-configs/openfibsem/fibsem_liftout_v1.yaml}
case "$config_arg" in
    /*) config_path=$config_arg ;;
    *) config_path=$instrument_root/$config_arg ;;
esac

test -f "$config_path"
test -d "$checkout_parent/instance/.git"
test -d "$checkout_parent/evaluator/.git"
test -d "$checkout_parent/fibsem/.git"

socket_gid=$(stat -c '%g' /var/run/docker.sock)
git_bin=$(command -v git)
git_exec_path=$(git --exec-path)
test -x "$git_bin"
test -d "$git_exec_path"
git_libraries=$(
    ldd "$git_bin" | awk \
        '$2 == "=>" && $3 ~ /^\// && $3 !~ /\/libc\.so\./ { print $3 }
         $1 ~ /^\// && $1 !~ /\/ld-linux/ { print $1 }'
)
test -n "$git_libraries"
set -- \
    --mount type=bind,src="$git_bin",dst="$git_bin",readonly \
    --mount type=bind,src="$git_exec_path",dst="$git_exec_path",readonly
for git_library in $git_libraries; do
    test -f "$git_library"
    set -- "$@" \
        --mount type=bind,src="$git_library",dst="$git_library",readonly
done
runner_image=iab/fibsem-validation-runner:v1

docker build \
    --platform linux/amd64 \
    --network=none \
    --file "$instrument_root/container/fibsem-validation-runner.Dockerfile" \
    --tag "$runner_image" \
    "$instrument_root/container"

docker run --rm \
    --platform linux/amd64 \
    --network=none \
    --user "$(id -u):$(id -g)" \
    --group-add "$socket_gid" \
    --env HOME=/tmp \
    "$@" \
    --mount type=bind,src="$checkout_parent",dst="$checkout_parent" \
    --mount type=bind,src=/tmp,dst=/tmp \
    --mount type=bind,src=/var/run/docker.sock,dst=/var/run/docker.sock \
    --workdir "$instrument_root" \
    "$runner_image" \
    scripts/validate_fibsem_benchmark.py --config "$config_path"
