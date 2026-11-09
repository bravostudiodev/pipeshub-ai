#!/bin/sh
set -eu
image="${SANDBOX_IMAGE:?SANDBOX_IMAGE must be configured}"
export DOCKER_HOST=unix:///run/docker/docker.sock
export DOCKER_CONFIG=/docker-config
docker_info="$(docker info)"
if ! printf '%s\n' "$docker_info" | grep -Eq '^  rootless$'; then
  echo "Docker daemon did not report rootless mode; refusing to start the sandbox executor" >&2
  exit 1
fi
cgroup_driver="$(printf '%s\n' "$docker_info" | sed -n 's/^ Cgroup Driver: //p')"
cgroup_version="$(printf '%s\n' "$docker_info" | sed -n 's/^ Cgroup Version: //p')"
echo "Docker rootless engine cgroup driver: ${cgroup_driver:-unknown}; cgroup version: ${cgroup_version:-unknown}"
if [ "$cgroup_driver" != systemd ] || [ "$cgroup_version" != 2 ]; then
  echo "WARNING: rootless Docker resource limits may not be enforced; limits require delegated cgroup v2 with systemd" >&2
fi
echo "Pulling configured sandbox image: $image"
docker pull "$image"
echo "Checking Python and TypeScript runtimes inside an isolated non-root container"
if ! docker run --rm --pull=never --network none --user sandbox \
  --cap-drop ALL --security-opt no-new-privileges --memory 512m --cpus 0.5 --pids-limit 256 \
  --entrypoint sh "$image" -ec '
    test "$(id -u)" -ne 0
    python -c "assert sum([1, 2]) == 3"
    tsx -e "if (1 + 1 !== 2) process.exit(1)"
  '; then
  echo "Sandbox startup smoke check failed. The configured image must support non-root execution with rootless Docker (see Moby issue 52268); isolation will not be weakened." >&2
  exit 1
fi
echo "Sandbox startup smoke check passed"
