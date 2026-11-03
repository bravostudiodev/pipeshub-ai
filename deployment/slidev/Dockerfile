# Upstream image origin and resolution are recorded in README.md. The tag is
# intentionally retained in the reference for readability; the digest makes
# the build reproducible.
FROM docker.io/tangramor/slidev:latest@sha256:79c835dbc489be324f697a975842cd222371e62e62a388e200cf092ca0925db9

WORKDIR /workspace
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund \
    && chown -R node:node /workspace

ENTRYPOINT []
USER 1000:1000
ENV CI=true \
    npm_config_audit=false \
    npm_config_fund=false

CMD ["sleep", "120"]
