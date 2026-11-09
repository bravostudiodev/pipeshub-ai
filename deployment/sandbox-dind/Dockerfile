# Build from the pinned upstream rootless DinD image. Keep the Docker version
# aligned with the chart's sandboxExecutor.image tag.
FROM docker:29.9.2-dind-rootless

USER root

# Preserve the upstream rootless account name and subordinate-ID ranges, but
# assign the host-visible container identity used by this deployment.
RUN apk add --no-cache shadow \
    && groupmod --gid 10101 rootless \
    && usermod --uid 10101 --gid 10101 rootless \
    && chown -R 10101:10101 /home/rootless \
    && grep -q '^rootless:[0-9]*:65536$' /etc/subuid \
    && grep -q '^rootless:[0-9]*:65536$' /etc/subgid

COPY start-dockerd.sh smoke-test.sh /usr/local/bin/
RUN chmod 0555 /usr/local/bin/start-dockerd.sh /usr/local/bin/smoke-test.sh

USER 10101:10101
