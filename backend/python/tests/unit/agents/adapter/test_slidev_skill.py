"""Contracts for Slidev's preinstalled coding-sandbox workflow."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]


def test_slidev_skill_uses_sandbox_and_preinstalled_dependencies() -> None:
    skill = (ROOT / "backend/python/app/agents/agent_loop/skills/builtin_packs/slidev/SKILL.md").read_text()
    assert "pack_version: 1.0.1" in skill
    assert "run_code" in skill
    assert "/opt/slidev/node_modules" in skill
    assert "render_slidev" not in skill
    assert "OUTPUT_DIR" in skill
    assert "/opt/brand-assets/oddbytes/" in skill
    assert "The Youngest is not installed" in skill


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
    assert "fonts-inter" in dockerfile
    assert "COPY brand-assets/oddbytes/ /opt/brand-assets/oddbytes/" in dockerfile
    assets = root / "brand-assets/oddbytes"
    assert {path.name for path in assets.iterdir()} == {
        "OB_Black_Icon.svg", "OB_Black_Logo.svg", "OB_Black_Primary_Icon.svg",
        "OB_Black_Primary_Logo.svg", "OB_White_Icon.svg", "OB_White_Logo.svg",
        "OB_White_Primary_Icon.svg", "_OB_White_Primary_Logo.svg",
        "Sticker-Curiosity.png", "Sticker-HB.png", "Sticker-Logo.png",
    }
