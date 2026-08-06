"""Generate the SC-FMA methodology figure as editable SVG and vector PDF."""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs" / "figures"
SVG_PATH = OUT_DIR / "sc_fma_framework.svg"
PDF_PATH = OUT_DIR / "sc_fma_framework.pdf"

W = 3000
H = 1420
PAGE_W_PT = 190 / 25.4 * 72
PAGE_H_PT = PAGE_W_PT * H / W
S = PAGE_W_PT / W

COLORS = {
    "ink": "#1f2937",
    "muted": "#526174",
    "light_text": "#65758a",
    "border": "#9aabbf",
    "hair": "#cbd5e1",
    "panel": "#ffffff",
    "panel2": "#ffffff",
    "core_fill": "#ffffff",
    "core_border": "#2f6f9f",
    "accent": "#2f6f9f",
    "accent_light": "#dbeaf7",
    "teal": "#4f8f7a",
    "teal_light": "#eef8f5",
    "amber": "#c18a2e",
    "amber_light": "#fbf3df",
    "fidelity_fill": "#dbeaf7",
    "graph_fill": "#eaf4ef",
    "redundancy_fill": "#fff4df",
    "bottleneck_fill": "#f1f4fb",
    "lavender": "#7b83a6",
    "white": "#ffffff",
}


class Figure:
    def __init__(self) -> None:
        self.svg: list[str] = []
        self.pdf = canvas.Canvas(str(PDF_PATH), pagesize=(PAGE_W_PT, PAGE_H_PT))
        self.pdf.setTitle("Overall Framework of SC-FMA")

    def px(self, x: float) -> float:
        return x * S

    def py(self, y: float) -> float:
        return PAGE_H_PT - y * S

    def rect(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        *,
        fill: str = "white",
        stroke: str = "border",
        sw: float = 2,
        r: float = 0,
        dash: str | None = None,
    ) -> None:
        fill_hex = COLORS[fill]
        stroke_hex = COLORS[stroke]
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        self.svg.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'rx="{r:.1f}" ry="{r:.1f}" fill="{fill_hex}" stroke="{stroke_hex}" '
            f'stroke-width="{sw:.1f}"{dash_attr}/>'
        )
        self.pdf.saveState()
        self.pdf.setFillColor(colors.HexColor(fill_hex))
        self.pdf.setStrokeColor(colors.HexColor(stroke_hex))
        self.pdf.setLineWidth(sw * S)
        if dash:
            parts = [float(p) * S for p in dash.replace(",", " ").split()]
            self.pdf.setDash(parts)
        if r:
            self.pdf.roundRect(self.px(x), self.py(y + h), self.px(w), self.px(h), self.px(r), 1, 1)
        else:
            self.pdf.rect(self.px(x), self.py(y + h), self.px(w), self.px(h), 1, 1)
        self.pdf.restoreState()

    def line(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        *,
        stroke: str = "border",
        sw: float = 2,
        dash: str | None = None,
    ) -> None:
        stroke_hex = COLORS[stroke]
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        self.svg.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{stroke_hex}" stroke-width="{sw:.1f}" stroke-linecap="round"{dash_attr}/>'
        )
        self.pdf.saveState()
        self.pdf.setStrokeColor(colors.HexColor(stroke_hex))
        self.pdf.setLineWidth(sw * S)
        if dash:
            parts = [float(p) * S for p in dash.replace(",", " ").split()]
            self.pdf.setDash(parts)
        self.pdf.line(self.px(x1), self.py(y1), self.px(x2), self.py(y2))
        self.pdf.restoreState()

    def polyline(
        self,
        pts: list[tuple[float, float]],
        *,
        stroke: str = "border",
        sw: float = 2,
        fill: str | None = None,
    ) -> None:
        stroke_hex = COLORS[stroke]
        fill_hex = "none" if fill is None else COLORS[fill]
        pts_attr = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        self.svg.append(
            f'<polyline points="{pts_attr}" fill="{fill_hex}" stroke="{stroke_hex}" '
            f'stroke-width="{sw:.1f}" stroke-linecap="round" stroke-linejoin="round"/>'
        )
        self.pdf.saveState()
        self.pdf.setStrokeColor(colors.HexColor(stroke_hex))
        self.pdf.setLineWidth(sw * S)
        if fill:
            self.pdf.setFillColor(colors.HexColor(COLORS[fill]))
        path = self.pdf.beginPath()
        path.moveTo(self.px(pts[0][0]), self.py(pts[0][1]))
        for x, y in pts[1:]:
            path.lineTo(self.px(x), self.py(y))
        self.pdf.drawPath(path, stroke=1, fill=1 if fill else 0)
        self.pdf.restoreState()

    def circle(
        self,
        cx: float,
        cy: float,
        r: float,
        *,
        fill: str = "white",
        stroke: str = "border",
        sw: float = 2,
    ) -> None:
        fill_hex = COLORS[fill]
        stroke_hex = COLORS[stroke]
        self.svg.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="{fill_hex}" '
            f'stroke="{stroke_hex}" stroke-width="{sw:.1f}"/>'
        )
        self.pdf.saveState()
        self.pdf.setFillColor(colors.HexColor(fill_hex))
        self.pdf.setStrokeColor(colors.HexColor(stroke_hex))
        self.pdf.setLineWidth(sw * S)
        self.pdf.circle(self.px(cx), self.py(cy), self.px(r), 1, 1)
        self.pdf.restoreState()

    def text(
        self,
        x: float,
        y: float,
        label: str,
        *,
        size: float = 34,
        fill: str = "ink",
        weight: str = "normal",
        style: str = "normal",
        anchor: str = "middle",
    ) -> None:
        fill_hex = COLORS[fill]
        family = "Helvetica, Arial, sans-serif"
        font_weight = "700" if weight == "bold" else "400"
        self.svg.append(
            f'<text x="{x:.1f}" y="{y:.1f}" fill="{fill_hex}" font-family="{family}" '
            f'font-size="{size:.1f}" font-weight="{font_weight}" font-style="{style}" '
            f'text-anchor="{anchor}" dominant-baseline="middle">{escape(label)}</text>'
        )
        if weight == "bold" and style == "italic":
            font = "Helvetica-BoldOblique"
        elif weight == "bold":
            font = "Helvetica-Bold"
        elif style == "italic":
            font = "Helvetica-Oblique"
        else:
            font = "Helvetica"
        pt_size = size * S
        pdf_y = self.py(y) - pt_size * 0.35
        self.pdf.saveState()
        self.pdf.setFillColor(colors.HexColor(fill_hex))
        self.pdf.setFont(font, pt_size)
        if anchor == "start":
            self.pdf.drawString(self.px(x), pdf_y, label)
        elif anchor == "end":
            self.pdf.drawRightString(self.px(x), pdf_y, label)
        else:
            self.pdf.drawCentredString(self.px(x), pdf_y, label)
        self.pdf.restoreState()

    def multiline(
        self,
        x: float,
        y: float,
        lines: list[str],
        *,
        size: float = 34,
        fill: str = "ink",
        weight: str = "normal",
        style: str = "normal",
        gap: float = 42,
        anchor: str = "middle",
    ) -> None:
        offset = (len(lines) - 1) * gap / 2
        for i, line in enumerate(lines):
            self.text(
                x,
                y - offset + i * gap,
                line,
                size=size,
                fill=fill,
                weight=weight,
                style=style,
                anchor=anchor,
            )

    def arrow(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        *,
        stroke: str = "border",
        sw: float = 2,
        head: float = 18,
    ) -> None:
        self.line(x1, y1, x2, y2, stroke=stroke, sw=sw)
        dx = x2 - x1
        dy = y2 - y1
        length = (dx * dx + dy * dy) ** 0.5
        if not length:
            return
        ux = dx / length
        uy = dy / length
        px = -uy
        py = ux
        base_x = x2 - ux * head
        base_y = y2 - uy * head
        pts = [
            (x2, y2),
            (base_x + px * head * 0.42, base_y + py * head * 0.42),
            (base_x - px * head * 0.42, base_y - py * head * 0.42),
        ]
        fill_hex = COLORS[stroke]
        pts_attr = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        self.svg.append(f'<polygon points="{pts_attr}" fill="{fill_hex}"/>')
        self.pdf.saveState()
        self.pdf.setFillColor(colors.HexColor(fill_hex))
        path = self.pdf.beginPath()
        path.moveTo(self.px(pts[0][0]), self.py(pts[0][1]))
        for x, y in pts[1:]:
            path.lineTo(self.px(x), self.py(y))
        path.close()
        self.pdf.drawPath(path, stroke=0, fill=1)
        self.pdf.restoreState()

    def check_icon(self, x: float, y: float, *, color: str = "teal", scale: float = 1.0) -> None:
        self.polyline(
            [(x, y + 7 * scale), (x + 11 * scale, y + 18 * scale), (x + 30 * scale, y - 8 * scale)],
            stroke=color,
            sw=5 * scale,
        )

    def save(self) -> None:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        svg_text = "\n".join(
            [
                '<?xml version="1.0" encoding="UTF-8"?>',
                f'<svg xmlns="http://www.w3.org/2000/svg" width="190mm" height="{190 * H / W:.1f}mm" '
                f'viewBox="0 0 {W} {H}" role="img">',
                "<title>Overall Framework of Structurally-Calibrated Functional Attribution</title>",
                "<desc>Camera-ready vector methodology figure for SC-FMA.</desc>",
                "<rect width=\"100%\" height=\"100%\" fill=\"#ffffff\"/>",
                *self.svg,
                "</svg>",
                "",
            ]
        )
        SVG_PATH.write_text(svg_text, encoding="utf-8")
        self.pdf.showPage()
        self.pdf.save()


def draw_main() -> None:
    fig = Figure()

    fig.text(1500, 78, "Overall Framework of Structurally-Calibrated Functional Attribution (SC-FMA)", size=58, weight="bold")

    # Semantic layer labels.
    fig.rect(110, 132, 650, 54, fill="white", stroke="hair", sw=1.5, r=12)
    fig.rect(800, 132, 1040, 54, fill="white", stroke="accent", sw=1.8, r=12)
    fig.rect(1900, 132, 1000, 54, fill="white", stroke="hair", sw=1.5, r=12)
    fig.text(435, 160, "Input Layer", size=32, fill="muted", weight="bold")
    fig.text(1320, 160, "SC-FMA Core", size=34, fill="accent", weight="bold")
    fig.text(2400, 160, "Explainable Outputs", size=32, fill="muted", weight="bold")

    # Stage 1.
    fig.rect(110, 250, 290, 900, fill="white", stroke="border", sw=2.2, r=18)
    fig.multiline(255, 305, ["Observable", "Reasoning Trace"], size=34, weight="bold", gap=38)
    step_y = [380, 492, 604, 716, 828, 940]
    step_labels = ["Reasoning", "Step 1", "Reasoning", "Step 2", "Reasoning", "Step n"]
    for i, y in enumerate(step_y):
        fig.rect(205, y, 145, 62, fill="panel", stroke="hair", sw=1.8, r=10)
        if i < 5:
            fig.arrow(278, y + 68, 278, y + 101, stroke="hair", sw=2, head=12)
        fig.text(277.5, y + 24, step_labels[i], size=25, fill="ink", weight="bold" if i % 2 == 1 else "normal")
        fig.text(277.5, y + 44, "trace unit", size=20, fill="light_text")
    fig.multiline(255, 1085, ["Step-level", "evidence-bearing trace"], size=22, fill="light_text", gap=26)

    # Stage 2.
    fig.rect(440, 250, 330, 900, fill="white", stroke="border", sw=2.2, r=18)
    fig.multiline(605, 305, ["Audit Graph", "Construction"], size=34, weight="bold", gap=38)
    chips = [
        ("Temporal Dependency", "accent_light", "accent"),
        ("Topical Similarity", "panel", "border"),
        ("Optional Semantic / KG", "teal_light", "teal"),
    ]
    for i, (label, fill, stroke) in enumerate(chips):
        y = 372 + i * 68
        fig.rect(485, y, 240, 42, fill=fill, stroke=stroke, sw=1.8, r=18)
        fig.text(605, y + 22, label, size=23, fill="ink")
    # Directed audit graph.
    graph_nodes = [
        (535, 640),
        (655, 620),
        (610, 735),
        (515, 820),
        (700, 840),
        (600, 965),
    ]
    edges = [(0, 1), (1, 2), (0, 2), (2, 3), (2, 4), (3, 5), (4, 5)]
    for a, b in edges:
        x1, y1 = graph_nodes[a]
        x2, y2 = graph_nodes[b]
        fig.arrow(x1, y1, x2, y2, stroke="hair", sw=2.2, head=12)
    for idx, (x, y) in enumerate(graph_nodes):
        fill = "accent_light" if idx in [1, 2, 5] else "white"
        fig.circle(x, y, 28, fill=fill, stroke="accent", sw=2.4)
        fig.text(x, y, f"s{idx + 1}", size=22, fill="accent", weight="bold")
    fig.multiline(605, 1070, ["Directed structural", "audit graph"], size=22, fill="light_text", gap=26)

    # Flow into the core.
    fig.arrow(400, 700, 440, 700, stroke="border", sw=2.2, head=14)
    fig.arrow(770, 700, 800, 700, stroke="border", sw=2.2, head=14)

    # Stage 3: SC-FMA core.
    fig.rect(800, 220, 1040, 1040, fill="core_fill", stroke="core_border", sw=3.5, r=26)
    fig.multiline(1320, 292, ["Structurally-Calibrated Functional", "Attribution (SC-FMA)"], size=42, fill="accent", weight="bold", gap=46)
    fig.text(1320, 358, "structural signals + fidelity signals -> calibrated review priorities", size=27, fill="muted")

    component_specs = [
        ("Fidelity", 1210, 400, "fidelity_fill", "accent"),
        ("Graph Necessity", 875, 615, "graph_fill", "teal"),
        ("Redundancy", 1565, 615, "redundancy_fill", "amber"),
        ("Bottleneck", 1210, 840, "bottleneck_fill", "lavender"),
    ]
    for label, x, y, fill, stroke in component_specs:
        fig.rect(x, y, 280, 110, fill=fill, stroke=stroke, sw=2.4, r=16)
        fig.text(x + 140, y + 56, label, size=32, fill="ink", weight="bold")

    fig.rect(1155, 585, 390, 165, fill="white", stroke="core_border", sw=3.6, r=24)
    fig.multiline(1350, 667, ["SCU Optimization", "Objective"], size=42, fill="accent", weight="bold", gap=48)
    fig.arrow(1350, 510, 1350, 585, stroke="accent", sw=2.5, head=14)
    fig.arrow(1155, 670, 1155, 670, stroke="accent", sw=2.5, head=14)
    fig.arrow(1155, 670, 1210, 670, stroke="accent", sw=2.5, head=14)
    fig.arrow(1565, 670, 1545, 670, stroke="accent", sw=2.5, head=14)
    fig.arrow(1350, 840, 1350, 750, stroke="accent", sw=2.5, head=14)

    fig.rect(1165, 1040, 370, 110, fill="white", stroke="hair", sw=2.2, r=15)
    fig.text(1350, 1072, "Calibrated Weight Vector", size=29, fill="ink", weight="bold")
    fig.text(1322, 1118, "[", size=42, fill="muted")
    fig.text(1350, 1118, "w", size=42, fill="accent", weight="bold", style="italic")
    fig.text(1378, 1118, "]", size=42, fill="muted")

    fig.polyline([(1545, 735), (1660, 735), (1660, 1095), (1535, 1095)], stroke="accent", sw=2.6)
    fig.arrow(1548, 1095, 1535, 1095, stroke="accent", sw=2.6, head=14)
    fig.text(910, 1195, "structural calibration", size=25, fill="light_text", anchor="start")
    fig.text(1795, 1195, "interpretable priorities", size=25, fill="light_text", anchor="end")

    # Stage 4.
    fig.arrow(1535, 1118, 1900, 410, stroke="accent", sw=2.3, head=14)
    fig.rect(1900, 250, 520, 300, fill="white", stroke="border", sw=2.2, r=18)
    fig.multiline(2160, 305, ["Priority Allocation", "under Fixed Review Budget"], size=31, weight="bold", gap=36)
    bars = [240, 195, 140, 90]
    labels = ["Step A", "Step B", "Step C", "Step D"]
    for i, (label, bar) in enumerate(zip(labels, bars)):
        y = 385 + i * 42
        fig.text(1995, y, label, size=24, fill="muted", anchor="start")
        fig.rect(2105, y - 14, 250, 20, fill="panel", stroke="hair", sw=1.2, r=7)
        fig.rect(2105, y - 14, bar, 20, fill="accent_light", stroke="accent", sw=1.2, r=7)

    # Stage 5.
    fig.arrow(2160, 550, 2160, 600, stroke="border", sw=2.2, head=14)
    fig.rect(1900, 600, 520, 300, fill="white", stroke="border", sw=2.2, r=18)
    fig.text(2180, 650, "Audit Queue", size=33, weight="bold")
    queue_items = ["Top-K Review Queue", "Selected Verification Steps", "Manual Inspection"]
    for i, item in enumerate(queue_items):
        y = 700 + i * 63
        fig.rect(2050, y, 280, 40, fill="panel", stroke="hair", sw=1.5, r=10)
        fig.text(2190, y + 21, item, size=23, fill="ink")
        if i < 2:
            fig.arrow(2190, y + 44, 2190, y + 61, stroke="hair", sw=2, head=9)

    # Stage 6.
    fig.arrow(2160, 900, 2160, 950, stroke="border", sw=2.2, head=14)
    fig.rect(1900, 950, 520, 360, fill="white", stroke="border", sw=2.4, r=18)
    fig.rect(1925, 975, 470, 66, fill="accent_light", stroke="accent", sw=1.8, r=12)
    fig.text(2160, 1008, "Explainable Audit Card", size=34, fill="accent", weight="bold")
    field_rows = [
        ("Fidelity", "0.82"),
        ("Graph Necessity", "0.76"),
        ("Redundancy", "0.18"),
        ("Bottleneck", "0.64"),
        ("Recommended Review Action", "Inspect"),
    ]
    for i, (label, value) in enumerate(field_rows):
        y = 1065 + i * 42
        fig.line(1935, y + 21, 2385, y + 21, stroke="hair", sw=1.1)
        fig.text(1950, y, label, size=23, fill="muted", anchor="start")
        value_fill = "teal" if i == 4 else "ink"
        fig.text(2370, y, value, size=23, fill=value_fill, weight="bold", anchor="end")
    fig.rect(1935, 1278, 450, 22, fill="teal_light", stroke="teal", sw=1.2, r=10)
    fig.text(2160, 1289, "Inspect | Protect | Consolidate | Repair", size=17, fill="teal", weight="bold")

    # Contribution box.
    fig.rect(2495, 275, 390, 430, fill="white", stroke="teal", sw=2.1, r=18)
    fig.text(2690, 326, "Key Contributions", size=30, fill="ink", weight="bold")
    contributions = [
        "Signal Preservation",
        "Structural Calibration",
        "Explainable Prioritization",
        "Decomposable Audit Decisions",
        "Fixed-Budget Review",
    ]
    for i, item in enumerate(contributions):
        y = 385 + i * 58
        fig.text(2535, y, "-", size=24, fill="teal", weight="bold", anchor="start")
        fig.text(2570, y, item, size=21, fill="ink", anchor="start")

    fig.save()


if __name__ == "__main__":
    draw_main()
