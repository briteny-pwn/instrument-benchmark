#!/bin/sh
set -eu

test "$(uname -s)" = "Linux"
test "$(uname -m)" = "x86_64"
test -S /var/run/docker.sock

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
instrument_root=$(CDPATH= cd -- "$script_dir/.." && pwd)
checkout_parent=$(dirname -- "$instrument_root")
config_arg=${1:-configs/fibsem_liftout_v1.yaml}
case "$config_arg" in
    /*) config_path=$config_arg ;;
    *) config_path=$instrument_root/$config_arg ;;
esac

test -f "$config_path"
test -d "$checkout_parent/instance/.git"
test -d "$checkout_parent/evaluator/.git"
test -d "$checkout_parent/fibsem/.git"

socket_gid=$(stat -c '%g' /var/run/docker.sock)
runner_image=iab/fibsem-validation-runner:v1

docker build \
    --platform linux/amd64 \
    --file "$instrument_root/container/fibsem-validation-runner.Dockerfile" \
    --tag "$runner_image" \
    "$instrument_root/container"

docker run --rm \
    --platform linux/amd64 \
    --user "$(id -u):$(id -g)" \
    --group-add "$socket_gid" \
    --env HOME=/tmp \
    --mount type=bind,src="$checkout_parent",dst="$checkout_parent" \
    --mount type=bind,src=/tmp,dst=/tmp \
    --mount type=bind,src=/var/run/docker.sock,dst=/var/run/docker.sock \
    --workdir "$instrument_root" \
    "$runner_image" \
    scripts/validate_fibsem_benchmark.py --config "$config_path"
