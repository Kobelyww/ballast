#!/usr/bin/env python3
"""Render the cost crossover from stored benchmark rows, as an SVG with no dependencies.

The claim being drawn is one line of README that nobody believes until they see the
shape of it: context control is *not* a fixed saving. On short tasks the retrieved
briefing and skill machinery make the controlled arm the more expensive one; past some
transcript size it flips and pays back on every later call. A single aggregate ratio
hides exactly that, so the figure is the argument.

Usage:  python scripts/plot_crossover.py bench/results/eval.json docs/figures/crossover.svg
"""

from __future__ import annotations

import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

W, H = 900, 470
PAD_L, PAD_R, PAD_T, PAD_B = 78, 34, 62, 78
BASELINE, CONTROL = "naive", "ballast"
SAVES, PAYS = "#1a5aa0", "#a05a10"  # above / below the break-even line
SAVES_FILL, PAYS_FILL = "#eef6ff", "#fdf1e6"
CHAR_W = 6.4  # monospace advance at font-size 10, used only to fit labels


def ratios(rows: list[dict]) -> list[tuple[str, float, float, float]]:
    """(scenario, baseline prompt tokens, baseline/control token ratio, cost ratio)."""
    by: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        by[(row["arm"], row["scenario_id"])].append(row)
    out = []
    for sid in sorted({scenario for _arm, scenario in by}):
        base = by[(BASELINE, sid)]
        ref = by.get((CONTROL, sid))
        if not base or not ref:
            continue
        b_tok = sum(r["prompt_tokens_total"] for r in base) / len(base)
        c_tok = sum(r["prompt_tokens_total"] for r in ref) / len(ref)
        if b_tok <= 0 or c_tok <= 0:
            continue
        b_cost = sum(r["cost"] for r in base) / len(base)
        c_cost = sum(r["cost"] for r in ref) / len(ref)
        out.append((sid, b_tok, b_tok / c_tok, (b_cost / c_cost) if c_cost else float("nan")))
    out.sort(key=lambda item: item[1])
    return out


def _log_ticks(lo: float, hi: float) -> list[float]:
    ticks = []
    for power in range(int(math.floor(math.log10(lo))), int(math.ceil(math.log10(hi))) + 1):
        for mantissa in (1, 2, 5):
            value = mantissa * 10**power
            if lo * 0.9 <= value <= hi * 1.1:
                ticks.append(value)
    return ticks


def _short(sid: str) -> str:
    """`L16_fat_batch` -> `L16`: the deck prefix and its number carry the meaning."""
    match = re.match(r"[A-Z]+\d+", sid)
    return match.group(0) if match else sid


def _wan(value: float) -> str:
    if value >= 1e6:
        return f"{value / 1e6:.1f}M"
    if value >= 1e3:
        return f"{value / 1e3:.0f}k"
    return f"{value:.0f}"


def render(points: list[tuple[str, float, float, float]], source: str) -> str:
    xs = [p[1] for p in points]
    ys = [p[2] for p in points]
    lo_x, hi_x = min(xs) * 0.62, max(xs) * 1.35
    lo_y, hi_y = min(min(ys), 0.9) - 0.05, max(max(ys), 1.1) + 0.07
    lx0, lx1 = math.log10(lo_x), math.log10(hi_x)
    plot_w, plot_h = W - PAD_L - PAD_R, H - PAD_T - PAD_B

    def px(value: float) -> float:
        return PAD_L + (math.log10(value) - lx0) / (lx1 - lx0) * plot_w

    def py(value: float) -> float:
        return H - PAD_B - (value - lo_y) / (hi_y - lo_y) * plot_h

    y_be = py(1.0)
    svg: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" '
        'font-family="ui-monospace, SFMono-Regular, Menlo, monospace">',
        "<title>Where context control stops costing and starts paying</title>",
        f'<rect width="{W}" height="{H}" fill="#ffffff"/>',
        f'<text x="{PAD_L}" y="24" font-size="15" fill="#111">Where context control stops costing and starts paying</text>',
        f'<text x="{PAD_L}" y="39" font-size="10.5" fill="#666">one point per task · y = naive prompt tokens ÷ ballast prompt tokens</text>',
        f'<text x="{PAD_L}" y="53" font-size="10.5" fill="#666">above 1.00 the controlled arm is the cheaper one; below it, the controlled arm is the one paying</text>',
        f'<rect x="{PAD_L}" y="{PAD_T - 4}" width="0" height="0"/>',
        # Which band is which is the whole claim, so the bands say it themselves rather
        # than relying on a legend the reader has to cross-reference.
        f'<rect x="{PAD_L}" y="{PAD_T}" width="{plot_w}" height="{y_be - PAD_T:.1f}" fill="{SAVES_FILL}"/>',
        f'<rect x="{PAD_L}" y="{y_be:.1f}" width="{plot_w}" height="{H - PAD_B - y_be:.1f}" fill="{PAYS_FILL}"/>',
        f'<text x="{PAD_L + 8}" y="{PAD_T + 15}" font-size="10.5" fill="{SAVES}">control SAVES — folded history stops being billed on every call</text>',
        f'<text x="{PAD_L + 8}" y="{H - PAD_B - 7}" font-size="10.5" fill="{PAYS}">control PAYS — briefing and skill machinery is pure overhead</text>',
    ]

    for tick in _log_ticks(lo_x, hi_x):
        x = px(tick)
        svg.append(f'<line x1="{x:.1f}" y1="{PAD_T}" x2="{x:.1f}" y2="{H - PAD_B}" stroke="#eaeaea"/>')
        svg.append(f'<text x="{x:.1f}" y="{H - PAD_B + 16}" font-size="10" fill="#777" text-anchor="middle">{_wan(tick)}</text>')

    for value in (round(lo_y, 1), 1.0, round(hi_y, 1)):
        if not lo_y <= value <= hi_y:
            continue
        y = py(value)
        strong = abs(value - 1.0) < 1e-9
        stroke = "#c0392b" if strong else "#e0e0e0"
        dash = ' stroke-dasharray="6 4"' if strong else ""
        width = "1.6" if strong else "1"
        svg.append(f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{W - PAD_R}" y2="{y:.1f}" stroke="{stroke}" stroke-width="{width}"{dash}/>')
        label_fill = "#c0392b" if strong else "#777"
        svg.append(f'<text x="{PAD_L - 8}" y="{y + 3.5:.1f}" font-size="10" fill="{label_fill}" text-anchor="end">{value:.2f}</text>')

    # The break-even point is found on the sorted series, not asserted from a tag list.
    crossing = next((i for i, p in enumerate(points) if p[2] >= 1.0), None)
    for index, (sid, tokens, ratio, _cost) in enumerate(points):
        x, y = px(tokens), py(ratio)
        hero = sid.startswith("L")
        colour = SAVES if ratio >= 1 else PAYS
        radius = "5.2" if hero else "3.4"
        opacity = "0.95" if hero else "0.6"
        edge = "1.2" if hero else "0.8"
        svg.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius}" fill="{colour}" fill-opacity="{opacity}" '
            f'stroke="#ffffff" stroke-width="{edge}"/>'
        )
        if index == crossing:
            svg.append(f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{x:.1f}" y2="{H - PAD_B}" stroke="#c0392b" stroke-width="1" stroke-dasharray="2 3"/>')
            note = f"break-even: {_short(sid)} at {_wan(tokens)} tokens"
            span = len(note) * CHAR_W
            # Anchor away from whichever edge the point is nearer, then clamp, so the
            # note is always fully inside the canvas rather than running off the frame.
            anchor = "start" if x < (PAD_L + W - PAD_R) / 2 else "end"
            if anchor == "start":
                nx = min(max(x + 7, PAD_L + 4), W - PAD_R - span)
            else:
                nx = max(min(x - 7, W - PAD_R - 4), PAD_L + span)
            svg.append(
                f'<text x="{nx:.1f}" y="{H - PAD_B - 26}" font-size="10" fill="#c0392b" text-anchor="{anchor}">{note}</text>'
            )

    cheapest = min(points, key=lambda p: p[2])
    dearest = max(points, key=lambda p: p[2])
    labelled = [p for i, p in enumerate(points) if i == crossing or p[0].startswith("L") or p is cheapest or p is dearest]

    # Greedy label placement: try the slots around a point and take the first that hits
    # nothing. Without this the long-horizon cluster overprints itself into noise.
    placed: list[tuple[float, float, float, float]] = []

    def free(box: tuple[float, float, float, float]) -> bool:
        x0, y0, x1, y1 = box
        return not any(x0 < b[2] and x1 > b[0] and y0 < b[3] and y1 > b[1] for b in placed)

    for sid, tokens, _ratio, cost_ratio in labelled:
        x, y = px(tokens), py(_ratio)
        text = f"{_short(sid)} · {cost_ratio:.2f}×"
        span = len(text) * CHAR_W
        for dx, dy in ((0, -11), (0, 17), (0, -23), (0, 29), (span / 2 + 14, -4), (-span / 2 - 14, -4), (0, -35), (0, 41)):
            cx = min(max(x + dx, PAD_L + span / 2), W - PAD_R - span / 2)
            cy = y + dy
            box = (cx - span / 2, cy - 9, cx + span / 2, cy + 3)
            if free(box):
                placed.append(box)
                svg.append(f'<text x="{cx:.1f}" y="{cy:.1f}" font-size="10" fill="#333" text-anchor="middle">{text}</text>')
                break

    svg.append(
        f'<text x="{PAD_L + plot_w / 2:.0f}" y="{H - 26}" font-size="11" fill="#555" text-anchor="middle">'
        "total prompt tokens per task on the uncontrolled arm (log scale)</text>"
    )
    mid = PAD_T + plot_h / 2
    svg.append(
        f'<text x="16" y="{mid:.0f}" font-size="11" fill="#555" text-anchor="middle" transform="rotate(-90 16 {mid:.0f})">'
        "naive ÷ ballast prompt tokens</text>"
    )
    svg.append(
        f'<text x="{PAD_L}" y="{H - 8}" font-size="9" fill="#999">drawn from {source} · regenerate with '
        "scripts/plot_crossover.py</text>"
    )
    svg.append("</svg>")
    return "\n".join(svg) + "\n"


def main(argv: list[str]) -> int:
    source = Path(argv[1] if len(argv) > 1 else "bench/results/eval.json")
    target = Path(argv[2] if len(argv) > 2 else "docs/figures/crossover.svg")
    payload = json.loads(source.read_text(encoding="utf-8"))
    points = ratios(payload["rows"])
    if not points:
        print(f"no {BASELINE}/{CONTROL} pairs in {source}", file=sys.stderr)
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(points, f"{source} · {payload.get('generated_at', 'unknown')}"), encoding="utf-8")
    lo, hi = min(p[2] for p in points), max(p[2] for p in points)
    print(f"{target} — {len(points)} tasks, ratio {lo:.2f}–{hi:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
