"""Contracts for Slidev's preinstalled coding-sandbox workflow."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]


def test_slidev_skill_uses_sandbox_and_preinstalled_dependencies() -> None:
    skill = (ROOT / "backend/python/app/agents/agent_loop/skills/builtin_packs/slidev/SKILL.md").read_text()
    assert "pack_version: 1.0.13" in skill
    assert "run_code" in skill
    assert "/opt/slidev/build_deck.py" in skill
    assert "http.server" not in skill
    assert "render_slidev" not in skill
    assert "OUTPUT_DIR" in skill
    assert "slidev-presentation.zip" in skill
    assert "/opt/brand-assets/oddbytes/" in skill
    assert "The Youngest is not installed" in skill
    # <style> in slides.md is slide-scoped; deck-wide CSS must live in style.css.
    assert "deck/style.css" in skill
    assert "v-motion" in skill and "slidev-vclick-hidden" in skill
    assert "do not save extra copies" in skill
    assert "never inside\n`$OUTPUT_DIR`" in skill
    assert "data-layout-ignore" in skill and "headless Chromium" in skill
    assert "3:1 contrast" in skill and "OB_White_*" in skill
    assert "fewer slides than `slides.md` defines" in skill


def test_sandbox_slidev_dependencies_are_pinned() -> None:
    root = ROOT / "deployment/sandbox"
    manifest = json.loads((root / "slidev-package.json").read_text())
    lock = json.loads((root / "slidev-package-lock.json").read_text())
    assert manifest["dependencies"] == lock["packages"][""]["dependencies"]
    assert manifest["dependencies"] == {
        "@slidev/cli": "53.0.0",
        "@slidev/theme-default": "0.25.0",
        "@slidev/theme-seriph": "0.25.0",
    }
    dockerfile = (root / "Dockerfile").read_text()
    assert "setup_22.x" in dockerfile
    assert "slidev-package-lock.json" in dockerfile
    assert "npm ci --omit=dev" in dockerfile
    assert "COPY slidev/build_deck.py slidev/single-file.vite.mjs slidev/layout_check.js /opt/slidev/" in dockerfile
    assert "fonts-inter" in dockerfile
    assert "chromium" in dockerfile
    assert "COPY python/sitecustomize.py python/oddjeeves_figure_check.py /usr/local/lib/python3.12/site-packages/" in dockerfile
    assert "FROM python:3.12-slim" in dockerfile  # the COPY target above is version-specific
    assert "COPY brand-assets/oddbytes/ /opt/brand-assets/oddbytes/" in dockerfile
    assets = root / "brand-assets/oddbytes"
    logos = {
        f"OB_{color}_{kind}.{ext}"
        for color in ("Black", "White")
        for kind in ("Icon", "Logo", "Primary_Icon", "Primary_Logo")
        for ext in ("svg", "png")
    }
    assert {path.name for path in assets.iterdir()} == logos | {
        "README.md", "Sticker-Curiosity.png", "Sticker-HB.png", "Sticker-Logo.png",
    }


def test_presentation_requests_are_routed_to_the_slidev_skill() -> None:
    app = ROOT / "backend/python/app/agents/agent_loop"
    skill = (app / "skills/builtin_packs/slidev/SKILL.md").read_text()
    description = next(line for line in skill.splitlines() if line.startswith("description:"))
    first_sentence = description.split(". ")[0]
    for word in ("presentation", "slide deck", "pitch deck", "PowerPoint"):
        assert word in description
    # The skill list shows only the first sentence, capped at 200 characters.
    assert "presentation" in first_sentence[:200] and "slide deck" in first_sentence[:200]
    assert "developers" not in description

    domain = (app / "domain_agents.py").read_text()
    assert "use the slidev skill and run_code" in domain
    assert "ANY request for a presentation" in domain
    assert "slidev skill" in (app / "prompt_builder.py").read_text()
