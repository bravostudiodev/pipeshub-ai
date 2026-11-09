#!/bin/sh
set -eu
runtime_dir="${XDG_RUNTIME_DIR:?XDG_RUNTIME_DIR must be configured}"
data_root=/home/rootless/.local/share/docker/data
mkdir -p "$runtime_dir"
chmod 0700 "$runtime_dir"
mkdir -p "$data_root"
export DOCKER_TLS_CERTDIR=""
# Rootless namespace GID 0 maps to the pod's outer GID 10101.
# The data-root child is owned by UID 10101; the mounted parent may not be.
exec /usr/local/bin/dockerd-entrypoint.sh dockerd --data-root="$data_root" --host=unix:///run/docker/docker.sock --group=0
