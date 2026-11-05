"""The sandbox refuses to save matplotlib figures with overflowing or unreadable text.

Runs wherever matplotlib is installed (the sandbox image); run it there with
`python3 test_figure_check.py`.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import pytest
except ImportError:  # The sandbox image runs this file directly, without pytest.
    import matplotlib
else:
    matplotlib = pytest.importorskip("matplotlib")
matplotlib.use("Agg")
import matplotlib.figure  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

_HERE = Path(__file__).resolve()
CHECK_DIR = next(
    path for path in [*(parent / "deployment/sandbox/python" for parent in _HERE.parents), _HERE.parent]
    if (path / "oddjeeves_figure_check.py").exists()
)
sys.path.insert(0, str(CHECK_DIR))
import oddjeeves_figure_check as check  # noqa: E402

check.install(matplotlib.figure)


def _save(fig, **kwargs) -> tuple[Path, Exception | None]:
    target = Path(tempfile.mkdtemp()) / "chart.png"
    try:
        fig.savefig(target, **kwargs)
        return target, None
    except check.FigureLayoutError as error:
        return target, error
    finally:
        plt.close(fig)


def _status_board(row_gap: float):
    """The reported dashboard: bars with bullet lists underneath each row."""
    fig, ax = plt.subplots(figsize=(7.2, 5.2), facecolor="#212121")
    ax.set_facecolor("#212121")
    ax.axis("off")
    rows = [("Shipped", 6, "#21896A", ["Brand verification passed", "Beta live — chirp.shop/beta",
                                         "DataGrail cookie consent", "Record Practice"]),
            ("In progress", 4, "#A3CACC", ["Nov 4 changelog — 30+ fixes", "Google demo voice-over + CASA review",
                                            "GTM assets & landers", "Affiliate deals", "Product catalog integration"]),
            ("Blocked", 3, "#FC4539", ["Gmail approval — 6–10 wks", "Braze keys", "Alias test data"])]
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 3 * row_gap)
    for index, (name, count, color, items) in enumerate(rows):
        top = 3 * row_gap - index * row_gap - 0.4
        ax.barh(top, count, height=0.35, color=color, left=0.5)
        ax.text(0.3, top, name, color="white", ha="right", va="center", fontsize=12)
        ax.text(0.7 + count, top, str(count), color="white", va="center", fontsize=12)
        for line, item in enumerate(items):
            ax.text(0.5, top - 0.45 - 0.3 * line, "· " + item, color="#E6E6E6", fontsize=10, va="center")
    return fig


def test_the_reported_status_board_is_refused_and_not_written() -> None:
    target, error = _save(_status_board(row_gap=1.6))

    assert error is not None and not target.exists()
    assert any("partly covered" in problem for problem in error.problems)


def test_the_same_board_with_room_for_its_lists_saves() -> None:
    target, error = _save(_status_board(row_gap=2.4), bbox_inches="tight")

    assert error is None, error
    assert target.exists()


def test_ordinary_charts_save() -> None:
    fig, ax = plt.subplots(figsize=(8, 4.5))
    bars = ax.bar(["Oct 28", "Oct 29", "Oct 30", "Nov 3"], [5, 0, 1, 12], color=["#FC4539", "#212121", "#A3CACC", "#21896A"])
    ax.bar_label(bars, fontsize=10)
    ax.bar([0, 1, 2, 3], [1, 2, 1, 3], bottom=[5, 0, 1, 12], label="Demand", color="#FFB400")
    ax.legend(loc="upper left", fontsize=10)
    ax.set_title("Deals won per day", fontsize=14)
    ax.set_ylabel("Deals won", fontsize=10)
    ax.table(cellText=[["Creators", "10"], ["Supply", "0"]], loc="bottom", bbox=[0, -0.6, 0.5, 0.35])
    fig.subplots_adjust(bottom=0.35)

    _, error = _save(fig, dpi=150, bbox_inches="tight")
    assert error is None, error


def test_common_chart_types_with_text_on_coloured_areas_save() -> None:
    import numpy as np

    fig, axes = plt.subplots(1, 3, figsize=(13, 4))
    data = np.array([[1, 8, 3], [9, 2, 7], [4, 6, 5]])
    axes[0].imshow(data, cmap="viridis")
    for (row, col), value in np.ndenumerate(data):
        axes[0].text(col, row, str(value), ha="center", va="center", fontsize=11,
                     color="white" if value < 5 else "black")
    _, _, percentages = axes[1].pie([40, 35, 25], labels=["Creators", "Demand", "Supply"], autopct="%d%%",
                colors=["#FC4539", "#212121", "#A3CACC"], textprops={"fontsize": 10},
                wedgeprops={"edgecolor": "white"})
    for percentage, color in zip(percentages, ["white", "white", "black"]):
        percentage.set_color(color)
    axes[2].plot([1, 2, 3, 4], [3, 5, 4, 7], marker="o")
    axes[2].annotate("peak", xy=(4, 7), xytext=(2.6, 6.6), fontsize=10, arrowprops={"arrowstyle": "->"})
    axes[2].set_xlabel("Week", fontsize=10)
    axes[2].grid(True, alpha=0.3)
    fig.suptitle("Overview", fontsize=16)

    _, error = _save(fig, dpi=150, bbox_inches="tight")
    assert error is None, error


def test_overlapping_text_faint_text_tiny_text_and_edge_overflow_are_reported() -> None:
    fig = plt.figure(figsize=(6, 3), facecolor="#F3F3F3")
    fig.text(0.05, 0.6, "Build-out progress at a glance", fontsize=24, color="#212121")
    fig.text(0.05, 0.62, "Pulled live from Slack", fontsize=11, color="#212121")
    fig.text(0.05, 0.9, "Sales pulse", fontsize=20, color="white")
    fig.text(0.05, 0.2, "footnote", fontsize=6, color="#212121")
    fig.text(0.8, 0.3, "This sentence is far too long for the figure", fontsize=11, color="#212121")

    _, error = _save(fig)
    problems = "\n".join(error.problems)
    assert "overlaps" in problems
    assert "'Sales pulse' has too little contrast" in problems
    assert "'footnote' is 6 pt" in problems
    assert "runs past the edge" in problems


def test_crowded_tick_labels_are_reported() -> None:
    fig, ax = plt.subplots(figsize=(4, 3))
    ax.bar([f"2026-10-{day:02d} long label" for day in range(1, 13)], range(12))

    _, error = _save(fig, bbox_inches="tight")
    assert error is not None
    assert any("tick labels" in problem and "overlap" in problem for problem in error.problems)


def test_text_overflowing_a_card_is_reported() -> None:
    from matplotlib.patches import FancyBboxPatch

    fig = plt.figure(figsize=(6, 3), facecolor="#F3F3F3")
    fig.patches.append(FancyBboxPatch((0.05, 0.55), 0.3, 0.15, boxstyle="square,pad=0",
                                      transform=fig.transFigure, facecolor="white"))
    fig.text(0.07, 0.6, "18 deals won", fontsize=12, color="#212121")
    fig.text(0.07, 0.535, "12 of them on Nov 3", fontsize=10, color="#212121")

    _, error = _save(fig)
    assert error is not None
    assert any("12 of them on Nov 3" in problem and "partly covered" in problem for problem in error.problems)


def test_sitecustomize_installs_the_check_for_any_script(tmp_path=None) -> None:
    folder = Path(tmp_path or tempfile.mkdtemp())
    script = folder / "plot.py"
    script.write_text(
        "import matplotlib\nmatplotlib.use('Agg')\nimport matplotlib.pyplot as plt\n"
        "fig = plt.figure(figsize=(4, 2))\nfig.text(0.1, 0.5, 'tiny', fontsize=5)\n"
        f"plt.savefig({str(folder / 'out.png')!r})\n"
    )
    result = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, check=False,
        env={**os.environ, "PYTHONPATH": str(CHECK_DIR)},
    )
    assert result.returncode != 0
    assert "FigureLayoutError" in result.stderr and "'tiny' is 5 pt" in result.stderr
    assert not (folder / "out.png").exists()


if __name__ == "__main__":
    failures = 0
    for name, test in sorted(globals().items()):
        if name.startswith("test_"):
            try:
                test()
                print("PASS", name)
            except Exception as error:  # noqa: BLE001
                failures += 1
                print("FAIL", name, type(error).__name__, error)
    sys.exit(1 if failures else 0)
