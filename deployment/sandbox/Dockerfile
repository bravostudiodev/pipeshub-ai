FROM python:3.12-slim

LABEL maintainer="pipeshub" \
      description="Unified sandbox for Python, TypeScript, SQLite, and PostgreSQL code execution"

# System deps: Cairo/Pango for SVG/PDF rendering, SQLite, PostgreSQL client, curl for Node setup.
# chromium: headless layout check for Slidev decks (/opt/slidev/build_deck.py).
# iptables: containers on the egress bridge install their egress firewall at start
# (app/agent_loop_lib/sandbox/coding/egress_firewall.py), then drop to `sandbox`
# with no capabilities via setpriv (util-linux). Without iptables, networked runs
# fall back to no network.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libcairo2 \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        fonts-dejavu-core \
        fonts-inter \
        fontconfig \
        sqlite3 \
        postgresql-client \
        curl \
        gnupg \
        tzdata \
        iptables \
        chromium \
    && rm -rf /var/lib/apt/lists/*

# Node.js 22 is required by the pinned Slidev and Mermaid dependencies.
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    rm -rf /var/lib/apt/lists/*

# Global Node tools
RUN npm install -g tsx && npm cache clean --force

# Slidev and its themes are pinned separately from the general-purpose packages.
# Projects can link /opt/slidev/node_modules to use these without network access.
COPY slidev-package.json /opt/slidev/package.json
COPY slidev-package-lock.json /opt/slidev/package-lock.json
COPY brand-assets/oddbytes/ /opt/brand-assets/oddbytes/
RUN cd /opt/slidev && npm ci --omit=dev --no-audit --no-fund && npm cache clean --force
# Builds decks into a self-contained dist/index.html for the gateway-protected preview
# and checks the layout of every slide in headless Chromium.
COPY slidev/build_deck.py slidev/single-file.vite.mjs slidev/layout_check.js /opt/slidev/

# Install uv for fast Python package management
RUN pip install --no-cache-dir uv

# Python data-science and document-generation packages
RUN uv pip install --system --no-cache \
    pandas \
    matplotlib \
    seaborn \
    plotly \
    kaleido \
    openpyxl \
    python-docx \
    python-pptx \
    Pillow \
    reportlab \
    fpdf2 \
    cairosvg \
    numpy \
    scipy \
    tabulate \
    xlsxwriter \
    jinja2

# Every matplotlib savefig refuses figures with overflowing, overlapping, tiny
# or low-contrast text (sitecustomize patches Figure.savefig on first import).
COPY python/sitecustomize.py python/oddjeeves_figure_check.py /usr/local/lib/python3.12/site-packages/

# Directories the sandbox user needs to write into at runtime.
# /src   — container cwd; programs write output files here
# /output — $OUTPUT_DIR; alternate artifact output path
# /install — npm install --prefix target for TypeScript packages
RUN mkdir -p /src /output /install && chmod 777 /src /output /install

# Non-root user
RUN useradd --create-home --shell /bin/bash sandbox
USER sandbox
WORKDIR /home/sandbox

# Pre-install Node packages in the sandbox user's home. The office-document
# creation libraries (pptxgenjs/docx/exceljs/pdfkit/pdf-lib) are deliberately
# pre-installed: the builtin skill packs steer agents to Node for document
# CREATION, and if only the Python equivalents are pre-installed the model
# takes the zero-friction path (python-pptx et al.) despite the guidance.
RUN npm init -y && \
    npm install --save \
        fs-extra \
        sharp \
        @types/node \
        csv-stringify \
        json2csv \
        papaparse \
        pptxgenjs \
        docx \
        exceljs \
        pdfkit \
        pdf-lib \
    && npm cache clean --force

WORKDIR /src
