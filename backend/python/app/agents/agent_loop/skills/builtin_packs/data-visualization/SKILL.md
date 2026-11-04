---
name: data-visualization
description: "Use this skill whenever the user asks for a chart, graph, plot, or visualization of data — 'chart this by month', 'show me a breakdown by category', 'visualize the trend'. Covers picking the right chart type for the question being asked, labeling/readability rules, and which plotting library to reach for. Pair with data-analysis for the underlying data prep."
metadata:
  agent-loop:
    version: 1.0.0
    category: data
    subcategory: visualization
    tags: [data, visualization, matplotlib, plotly, charts]
    status: active
    source: builtin
    requires: [data-analysis]
    pack_name: data-visualization
    pack_version: 1.0.4
---

# Data visualization

`matplotlib`, `seaborn`, `plotly`, and `kaleido` are already installed in the sandbox — no `install_packages` call needed for any workflow below.

## Choosing a chart type

Pick the chart type from the *question being asked*, not from habit — a bar chart is not the universal default:

| Question shape | Chart type |
|---|---|
| Comparing a metric across categories ("revenue by region") | Bar chart (horizontal if category labels are long) |
| Trend over time ("revenue by month") | Line chart |
| Distribution of a single variable ("how are order sizes distributed") | Histogram, or box plot for comparing distributions across groups |
| Relationship between two numeric variables ("does price correlate with rating") | Scatter plot |
| Composition of a whole ("market share by segment") | Stacked bar chart — prefer this over a pie chart once there are more than ~4-5 slices, since angle/area comparisons get hard to read past that; a pie chart is defensible for 2-4 slices where the "parts of a whole" framing is the entire point |

If the question doesn't clearly map to one of these, default to a bar or line chart (whichever fits the data shape) rather than reaching for something more exotic — a chart the user immediately understands beats a more "interesting" one they have to puzzle over.

## Readability rules (apply to every chart)

- **Always set a title and axis labels with units** (`"Revenue ($K)"`, not just `"Revenue"`) — a chart with unlabeled axes forces the viewer to guess what they're looking at.
- **Only add a legend when there's more than one series/category to distinguish.** A legend on a single-series chart is clutter.
- **Never leave x-axis labels rotated to the point of being hard to read.** If category names are long, use a horizontal bar chart instead of rotating vertical bar labels 90 degrees.
- **Use a colorblind-safe palette** — matplotlib's `"viridis"`/`"cividis"` colormaps or seaborn's `"colorblind"` palette, rather than a default red/green distinction as the only signal between two series.
- **Sort categorical bar charts by value (descending), not alphabetically**, unless the categories have a natural order (months, ordinal ratings) — alphabetical order makes it harder to spot the biggest/smallest category at a glance.

## Text must be readable and fit (apply to every chart and dashboard)

Static images cannot be zoomed or fixed by the viewer, so unreadable or cut-off text ships as a defect.

- **Pick text colors against the actual background.** Title and label colors chosen for a dark page are invisible on a light one, so set the figure and axes facecolors explicitly and derive every text color from them. Normal text needs a contrast ratio of at least 4.5:1 (about `#6B6B6B` on white at the lightest); never use light grey for notes or captions.
- **Minimum sizes at `dpi=150`:** titles 14 pt or more, axis labels and legend text 10 pt or more, data labels and footnotes 9 pt or more. If text must be smaller than that to fit, there is too much on the figure: remove a chart or a label rather than shrinking type.
- **Size boxes and cards from their content.** For KPI cards or annotated panels, measure each text with `text.get_window_extent(renderer)` (or leave generous height: about 1.6 x the sum of the line heights plus padding) instead of guessing a height, and keep a margin of at least 2% of the figure height below footnotes.
- **Label zero and empty values** (`0`) on bars so a missing bar reads as zero, not as missing data.
- **No text may overlap other text.** A title, subtitle, and eyebrow label stacked in a header need line gaps measured from their real heights (see `get_window_extent`), not guessed offsets; the check below reports every overlapping pair. Also keep annotations clear of bars and titles; offset them or drop them.

## Check the figure before saving

Run this on the figure just before `savefig`. Do not rely on `analyze_image`: it only works on images the user attached to the chat, not on files you generate.

**Every file written to `$OUTPUT_DIR` becomes a separate artifact version that the user sees**, so a chart saved, fixed, and saved again shows up as several near-identical files. Never save a draft there. Build the figure, run `check_figure`, and call `savefig` into `$OUTPUT_DIR` only when it returns no problems, all in the same `run_code` call. If it returns problems, print them, write nothing, fix the code, and run again. Save the final file exactly once.

```python
import matplotlib.colors as mc
import os
from pathlib import Path
from matplotlib.patches import Patch
from matplotlib.text import Text

def _luminance(color):
    channel = lambda v: v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(v) for v in mc.to_rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b

def check_figure(fig, min_pt=9, min_contrast=4.5):
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    figure_box = fig.bbox
    bars = {id(p) for ax in fig.axes for c in ax.containers for p in c}
    bars |= {id(fig.patch)} | {id(ax.patch) for ax in fig.axes}
    bars |= {id(fig.patch)} | {id(ax.patch) for ax in fig.axes}
    boxes = [(p, p.get_window_extent(renderer)) for p in fig.findobj(Patch)
             if id(p) not in bars and p.get_visible() and p.get_facecolor()[3] > 0.5
             and p.get_window_extent(renderer).width > 20]
    problems = []
    placed = []
    for text in fig.findobj(Text):
        label = text.get_text().strip()
        if not label or not text.get_visible():
            continue
        box = text.get_window_extent(renderer)
        for other_label, other in placed:
            width = min(box.x1, other.x1) - max(box.x0, other.x0)
            height = min(box.y1, other.y1) - max(box.y0, other.y0)
            if width > 4 and height > 0.25 * min(box.height, other.height):
                problems.append(f"overlaps other text: {label[:40]!r} and {other_label[:40]!r}")
        placed.append((label, box))
        if (box.x0 < figure_box.x0 - 1 or box.y0 < figure_box.y0 - 1
                or box.x1 > figure_box.x1 + 1 or box.y1 > figure_box.y1 + 1):
            problems.append(f"outside the image: {label[:40]!r}")
        if text.get_fontsize() < min_pt:
            problems.append(f"too small ({text.get_fontsize():.0f} pt): {label[:40]!r}")
        cx, cy = (box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2
        cards = [(p, b) for p, b in boxes if b.x0 <= cx <= b.x1 and b.y0 <= cy <= b.y1]
        card = min(cards, key=lambda pb: pb[1].width * pb[1].height, default=None)
        if card is not None and (box.x0 < card[1].x0 - 1 or box.x1 > card[1].x1 + 1
                                 or box.y0 < card[1].y0 - 1 or box.y1 > card[1].y1 + 1):
            problems.append(f"overflows its box: {label[:40]!r}")
        axes = text.axes
        inside_axes = axes is not None and axes.bbox.contains(box.x0, box.y0) and axes.bbox.contains(box.x1, box.y1)
        background = (card[0].get_facecolor() if card is not None
                      else axes.get_facecolor() if inside_axes else fig.get_facecolor())
        lighter, darker = sorted((_luminance(text.get_color()), _luminance(background)), reverse=True)
        if (lighter + 0.05) / (darker + 0.05) < min_contrast:
            problems.append(f"low contrast against its background: {label[:40]!r}")
    return problems

problems = check_figure(fig)
if problems:
    print("FIX BEFORE SAVING:", *problems, sep="\n- ")
else:
    fig.savefig(Path(os.environ["OUTPUT_DIR"]) / "chart.png", dpi=150, bbox_inches="tight")
```

The check treats any filled rectangle behind text (a KPI card, a panel) as that text's box: it reports text that sticks out of the card and judges contrast against the card color. Bars are ignored. Draw cards as filled `Rectangle` or `FancyBboxPatch` patches so they are checked.

## Library choice

- **`matplotlib`/`seaborn` → static PNG.** The default choice for a chart that's going into a report, an email, or anywhere it just needs to be an image. Save via `plt.savefig("chart.png", dpi=150, bbox_inches="tight")` — the `bbox_inches="tight"` avoids clipped axis labels, a common failure mode. Saved files surface to the user automatically as artifacts; you don't need to do anything extra to hand them over.
- **`plotly` (+ `kaleido` for static export) → when the user wants interactivity** (hover tooltips, zoom/pan) or explicitly asks for an HTML output. Export interactive output via `fig.write_html("chart.html")`; if a static image is needed instead, `fig.write_image("chart.png")` (uses `kaleido` under the hood).
- Default to `matplotlib`/`seaborn` unless the user's request specifically implies interactivity or a web-embeddable artifact — it's the lighter-weight choice and covers the vast majority of "make me a chart" requests.

## Before finishing

Look at what you actually plotted against what was asked — a common failure mode is generating a technically-valid chart of the wrong slice of data (e.g. totals instead of averages, or the wrong grouping column) because a `data-analysis` step upstream computed something adjacent to, but not exactly, what was requested. Re-read the user's question once more against the chart's title and axes before presenting it. Also confirm `check_figure` printed no problems and that the file was saved only once.
