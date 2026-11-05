"""Refuse to save a matplotlib figure whose text is unreadable or does not fit.

`sitecustomize.py` patches `Figure.savefig` (and so `plt.savefig`) to run
`check_figure` first. A figure with problems raises `FigureLayoutError`
listing each one, and no file is written, so a broken chart never becomes
an artifact.
"""

from __future__ import annotations

import functools
from typing import Any

MIN_FONT_PT = 8
# WCAG's large-text minimum; 4.5 would refuse white on the OddBytes red (#FC4539, about 3.5).
MIN_CONTRAST = 3.0
MAX_REPORTED = 15


class FigureLayoutError(ValueError):
    def __init__(self, problems: list[str]) -> None:
        shown = problems[:MAX_REPORTED]
        more = len(problems) - len(shown)
        super().__init__(
            "Figure not saved: its text does not fit or is hard to read. Fix every item, then save again:\n"
            + "\n".join(f"- {problem}" for problem in shown)
            + (f"\n- ... and {more} more" if more > 0 else "")
            + "\nTypical fixes: leave more space between rows (taller figure or fewer items), move labels "
            "clear of bars and boxes, shorten text, or make a box larger than its text."
        )
        self.problems = problems


def _luminance(rgb: tuple[float, float, float]) -> float:
    def channel(value: float) -> float:
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(value) for value in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(foreground: tuple[float, ...], background: tuple[float, ...]) -> float:
    alpha = foreground[3] if len(foreground) > 3 else 1.0
    blended = tuple(alpha * f + (1 - alpha) * b for f, b in zip(foreground[:3], background[:3], strict=True))
    lighter, darker = sorted((_luminance(blended), _luminance(background[:3])), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _label(text: Any) -> str:
    return repr(" ".join(text.get_text().split())[:50])


def _usable(text: Any) -> bool:
    return (text.get_visible() and bool(text.get_text().strip())
            and (text.get_alpha() is None or text.get_alpha() > 0))


def _visible_texts(fig: Any) -> tuple[list[Any], list[list[Any]]]:
    """Free text (titles, labels, annotations, legends) and, per axis, its drawn tick labels.

    Tick labels are compared only with their own axis's other tick labels:
    matplotlib keeps stale tick-label objects around, so mixing them into
    the figure-wide comparison reports overlaps that are never drawn.
    """
    from matplotlib.text import Text

    owned: set[int] = set()
    axis_labels: list[Any] = []
    tick_groups: list[list[Any]] = []
    for ax in fig.axes:
        for axis in getattr(ax, "_axis_map", {"x": ax.xaxis, "y": ax.yaxis}).values():
            # Materialise the ticks first so every label created here is in `owned`.
            drawn = axis.get_majorticklabels() + axis.get_minorticklabels()
            owned.update((id(axis.label), id(axis.offsetText)))
            for tick in axis.majorTicks + axis.minorTicks:
                owned.update((id(tick.label1), id(tick.label2)))
            if ax.get_visible() and ax.axison and axis.get_visible():
                axis_labels.append(axis.label)
                tick_groups.append([label for label in drawn if _usable(label)])
    free = [t for t in fig.findobj(Text) if id(t) not in owned] + axis_labels
    free = [t for t in free if _usable(t) and (t.axes is None or t.axes.get_visible())]
    return free, tick_groups


def _boxes(fig: Any, texts: list[Any], renderer: Any) -> list[tuple[Any, Any]]:
    """Filled rectangles text can sit on or collide with: bars, cards, table cells, legend frames."""
    from matplotlib.colors import to_rgba
    from matplotlib.patches import FancyBboxPatch, Rectangle

    excluded = {id(fig.patch)} | {id(ax.patch) for ax in fig.axes}
    excluded |= {id(t.get_bbox_patch()) for t in texts if t.get_bbox_patch() is not None}
    boxes = []
    for patch in fig.findobj(lambda artist: isinstance(artist, (Rectangle, FancyBboxPatch))):
        if id(patch) in excluded or not patch.get_visible() or not patch.get_fill():
            continue
        if to_rgba(patch.get_facecolor())[3] <= 0.5:
            continue
        extent = patch.get_window_extent(renderer)
        if extent.width > 2 and extent.height > 2:
            boxes.append((patch, extent))
    return boxes


def _rendered_background(pixels: Any, box: Any, foreground: tuple[float, ...]) -> tuple[float, ...] | None:
    """Most common rendered colour behind the text, ignoring its own glyph pixels."""
    import numpy as np

    height, width = pixels.shape[:2]
    x0, x1 = max(int(box.x0), 0), min(int(box.x1) + 1, width)
    y0, y1 = max(height - int(box.y1) - 1, 0), min(height - int(box.y0), height)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    patch = pixels[y0:y1, x0:x1, :3].reshape(-1, 3).astype(np.float64) / 255.0
    quantised = np.round(patch * 31).astype(np.int64)
    keys = quantised[:, 0] * 1024 + quantised[:, 1] * 32 + quantised[:, 2]

    def mode(selection: Any) -> tuple[Any, int]:
        values, counts = np.unique(keys[selection], return_counts=True)
        return values[counts.argmax()], int(counts.max())

    glyph_like = np.abs(patch - np.asarray(foreground[:3])).sum(axis=1) <= 0.3
    key, _ = mode(np.ones(len(keys), dtype=bool))
    # Solid glyph interiors of large bold text can outnumber the background;
    # prefer the commonest clearly different colour when it is substantial.
    if glyph_like.any() and (~glyph_like).any():
        other, count = mode(~glyph_like)
        if count >= 0.15 * len(keys):
            key = other
    return (key // 1024 / 31, key // 32 % 32 / 31, key % 32 / 31, 1.0)


def _overlap(a: Any, b: Any) -> tuple[float, float]:
    return min(a.x1, b.x1) - max(a.x0, b.x0), min(a.y1, b.y1) - max(a.y0, b.y0)


def _contains(outer: Any, inner: Any, slack: float = 1.0) -> bool:
    return (inner.x0 >= outer.x0 - slack and inner.x1 <= outer.x1 + slack
            and inner.y0 >= outer.y0 - slack and inner.y1 <= outer.y1 + slack)


def check_figure(fig: Any, *, tight: bool = False, background: Any = None) -> list[str]:
    """Return every text problem in `fig`; empty means it is safe to save."""
    from matplotlib.colors import to_rgba

    import numpy as np

    original_face = fig.get_facecolor()
    if background is not None:
        fig.set_facecolor(background)  # savefig(facecolor=...) paints this, not the figure's own
    try:
        fig.canvas.draw()
        pixels = np.asarray(fig.canvas.buffer_rgba()).copy()
    finally:
        fig.set_facecolor(original_face)
    renderer = fig.canvas.get_renderer()
    texts, tick_groups = _visible_texts(fig)
    boxes = _boxes(fig, texts, renderer)
    problems: list[str] = []
    placed: list[tuple[Any, Any]] = []

    for text in texts:
        box = text.get_window_extent(renderer)
        if box.width <= 0 or box.height <= 0:
            continue
        label = _label(text)
        if not tight and not _contains(fig.bbox, box):
            problems.append(f"{label} runs past the edge of the image")
        if text.get_fontsize() < MIN_FONT_PT:
            problems.append(f"{label} is {text.get_fontsize():.0f} pt; use at least {MIN_FONT_PT} pt")

        for other_label, other in placed:
            width, height = _overlap(box, other)
            if width > 0.2 * min(box.height, other.height) and height > 0.25 * min(box.height, other.height):
                problems.append(f"{label} overlaps {other_label}")
        placed.append((label, box))

        holders, crossing = [], []
        for patch, extent in boxes:
            width, height = _overlap(box, extent)
            if width <= 1 or height <= 0.25 * box.height:
                continue
            (holders if _contains(extent, box) else crossing).append((patch, extent))
        # A box drawn on top (a legend over bars) hides whatever it crosses.
        top = max((patch.get_zorder() for patch, _ in holders), default=None)
        if any(top is None or patch.get_zorder() >= top for patch, _ in crossing):
            problems.append(f"{label} is partly covered by, or sticks out of, a bar or box")

        color = to_rgba(text.get_color(), text.get_alpha())
        back = _rendered_background(pixels, box, color)
        if back is not None and _contrast(color, back) < MIN_CONTRAST:
            problems.append(f"{label} has too little contrast against its background")

    for group in tick_groups:
        extents = [(label, label.get_window_extent(renderer)) for label in group]
        for index, (label, box) in enumerate(extents):
            if label.get_fontsize() < MIN_FONT_PT:
                problems.append(f"tick label {_label(label)} is {label.get_fontsize():.0f} pt; use at least {MIN_FONT_PT} pt")
            for other, other_box in extents[index + 1:]:
                width, height = _overlap(box, other_box)
                if width > 1 and height > 1:
                    problems.append(f"tick labels {_label(label)} and {_label(other)} overlap; rotate, thin out, or shorten them")

    return list(dict.fromkeys(problems))


def install(figure_module: Any) -> None:
    """Make `Figure.savefig` refuse figures that fail `check_figure`."""
    original = figure_module.Figure.savefig
    if getattr(original, "_oddjeeves_checked", False):
        return

    @functools.wraps(original)
    def savefig(self: Any, fname: Any, *args: Any, **kwargs: Any) -> Any:
        from matplotlib import rcParams

        tight = (kwargs.get("bbox_inches") or rcParams["savefig.bbox"]) == "tight"
        background = None if kwargs.get("transparent") else kwargs.get("facecolor")
        if background == "auto":
            background = None
        problems = check_figure(self, tight=tight, background=background)
        if problems:
            raise FigureLayoutError(problems)
        return original(self, fname, *args, **kwargs)

    savefig._oddjeeves_checked = True  # type: ignore[attr-defined]
    figure_module.Figure.savefig = savefig
