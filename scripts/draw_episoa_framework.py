"""Generate the editable draw.io framework figure for the EpiSOA paper.

The script writes a native diagrams.net/draw.io `.drawio` file and exports it
with the draw.io desktop CLI. It intentionally does not fall back to matplotlib:
if draw.io is unavailable, the source file is still written and the exporter
raises a concrete blocker.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

try:
    import winreg
except ImportError:  # pragma: no cover - only used on Windows.
    winreg = None  # type: ignore[assignment]


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs" / "figures"
DRAWIO_PATH = OUT_DIR / "episoa_framework.drawio"
PNG_PATH = OUT_DIR / "episoa_framework.png"
SVG_PATH = OUT_DIR / "episoa_framework.svg"
PDF_PATH = OUT_DIR / "episoa_framework.pdf"

CANVAS_W = 1800
CANVAS_H = 1422
LANE_X = 70
LANE_W = 1660
LANE_H = 230
LANE_GAP = 38
LANE_Y0 = 50

FONT = "Microsoft YaHei"
TEXT = "#1F2937"
MUTED = "#475569"
ARROW = "#64748B"


@dataclass(frozen=True)
class Box:
    id: str
    x: int
    y: int
    w: int
    h: int
    role: str

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h


class DiagramBuilder:
    def __init__(self) -> None:
        self.model = ET.Element(
            "mxGraphModel",
            {
                "dx": "1422",
                "dy": "841",
                "grid": "1",
                "gridSize": "10",
                "guides": "1",
                "tooltips": "1",
                "connect": "1",
                "arrows": "1",
                "fold": "1",
                "page": "1",
                "pageScale": "1",
                "pageWidth": str(CANVAS_W),
                "pageHeight": str(CANVAS_H),
                "math": "0",
                "shadow": "0",
            },
        )
        self.root = ET.SubElement(self.model, "root")
        ET.SubElement(self.root, "mxCell", {"id": "0"})
        ET.SubElement(self.root, "mxCell", {"id": "1", "parent": "0"})
        self.boxes: list[Box] = []

    def vertex(
        self,
        *,
        id: str,
        value: str,
        style: str,
        x: int,
        y: int,
        w: int,
        h: int,
        role: str,
    ) -> None:
        cell = ET.SubElement(
            self.root,
            "mxCell",
            {
                "id": id,
                "value": value,
                "style": style,
                "vertex": "1",
                "parent": "1",
            },
        )
        ET.SubElement(
            cell,
            "mxGeometry",
            {
                "x": str(x),
                "y": str(y),
                "width": str(w),
                "height": str(h),
                "as": "geometry",
            },
        )
        self.boxes.append(Box(id, x, y, w, h, role))

    def edge(
        self,
        *,
        id: str,
        source: str,
        target: str,
        style: str | None = None,
    ) -> None:
        cell = ET.SubElement(
            self.root,
            "mxCell",
            {
                "id": id,
                "value": "",
                "style": style or edge_style(),
                "edge": "1",
                "parent": "1",
                "source": source,
                "target": target,
            },
        )
        ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})

    def point_edge(
        self,
        *,
        id: str,
        source: tuple[int, int],
        target: tuple[int, int],
        style: str | None = None,
    ) -> None:
        cell = ET.SubElement(
            self.root,
            "mxCell",
            {
                "id": id,
                "value": "",
                "style": style or edge_style(),
                "edge": "1",
                "parent": "1",
            },
        )
        geom = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
        ET.SubElement(geom, "mxPoint", {"x": str(source[0]), "y": str(source[1]), "as": "sourcePoint"})
        ET.SubElement(geom, "mxPoint", {"x": str(target[0]), "y": str(target[1]), "as": "targetPoint"})


def base_text_style(extra: str = "") -> str:
    return (
        "rounded=1;whiteSpace=wrap;html=1;arcSize=12;"
        f"fontFamily={FONT};fontColor={TEXT};"
        "align=center;verticalAlign=middle;"
        + extra
    )


def lane_style(fill: str, stroke: str) -> str:
    return base_text_style(
        f"fillColor={fill};strokeColor={stroke};strokeWidth=2;dashed=1;dashPattern=8 6;"
        "spacing=0;fontSize=18;"
    )


def label_style(fill: str, stroke: str) -> str:
    return base_text_style(
        f"fillColor={fill};strokeColor={stroke};strokeWidth=1.2;fontSize=24;fontStyle=1;"
        "spacing=8;"
    )


def card_style(fill: str, stroke: str) -> str:
    return base_text_style(
        f"fillColor={fill};strokeColor={stroke};strokeWidth=1.8;fontSize=22;"
        "spacing=10;spacingTop=4;spacingBottom=4;"
    )


def chip_style(fill: str, stroke: str) -> str:
    return base_text_style(
        f"fillColor={fill};strokeColor={stroke};strokeWidth=1.2;fontSize=16;"
        "spacing=5;"
    )


def edge_style(color: str = ARROW) -> str:
    return (
        "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;"
        f"html=1;endArrow=block;endFill=1;strokeColor={color};strokeWidth=2;"
    )


def html_card(title: str, subtitle: str | None = None) -> str:
    if not subtitle:
        return f"<b>{title}</b>"
    return f"<b>{title}</b><br><font style=\"font-size:16px;color:{MUTED}\">{subtitle}</font>"


def add_lane(builder: DiagramBuilder, index: int, label: str, fill: str, stroke: str) -> int:
    y = LANE_Y0 + index * (LANE_H + LANE_GAP)
    builder.vertex(
        id=f"lane_{index + 1}",
        value="",
        style=lane_style(fill, stroke),
        x=LANE_X,
        y=y,
        w=LANE_W,
        h=LANE_H,
        role="lane",
    )
    builder.vertex(
        id=f"label_{index + 1}",
        value=label,
        style=label_style("#FFFFFF", stroke),
        x=LANE_X + 24,
        y=y + 35,
        w=150,
        h=160,
        role="label",
    )
    return y


def add_card_row(
    builder: DiagramBuilder,
    *,
    ids: list[str],
    values: list[str],
    fills: list[str],
    stroke: str,
    x0: int,
    y: int,
    widths: list[int],
    h: int = 88,
    gap: int = 34,
) -> None:
    x = x0
    for id, value, fill, w in zip(ids, values, fills, widths):
        builder.vertex(
            id=id,
            value=value,
            style=card_style(fill, stroke),
            x=x,
            y=y,
            w=w,
            h=h,
            role="card",
        )
        x += w + gap


def build_diagram() -> tuple[ET.ElementTree, list[Box]]:
    builder = DiagramBuilder()

    lane_specs = [
        ("数据构建", "#F8FBFF", "#8FAAD8"),
        ("证据链与图骨架", "#F7FCF5", "#91B98F"),
        ("SOA归因", "#FFFDF4", "#C9B45D"),
        ("忠实性验证", "#FFF7F5", "#CA8A8A"),
        ("输出与评估", "#FBF8FF", "#A58BCB"),
    ]
    lane_y = [add_lane(builder, i, label, fill, stroke) for i, (label, fill, stroke) in enumerate(lane_specs)]

    # Layer 1: data construction.
    data_ids = [
        "data_events",
        "data_cfsm",
        "data_norm",
        "data_silver",
        "data_adjudication",
        "data_human_gold",
    ]
    add_card_row(
        builder,
        ids=data_ids,
        values=[
            html_card("事件注册", "events.jsonl"),
            html_card("C-FSM采集", "公开多源证据"),
            html_card("证据规范化", "evidence.jsonl"),
            html_card("LLM silver", "预标注"),
            html_card("人工裁决", "三人审阅"),
            html_card("human_gold_v2", "正式gold"),
        ],
        fills=["#EAF2FF"] * 6,
        stroke="#8FAAD8",
        x0=285,
        y=lane_y[0] + 67,
        widths=[195] * 6,
        h=86,
        gap=28,
    )
    # Layer 2: event chain and graph skeleton.
    graph_ids = ["graph_chain", "graph_selector", "graph_skeleton"]
    add_card_row(
        builder,
        ids=graph_ids,
        values=[
            html_card("六阶段事件链", "trigger / diffusion / conflict<br>response / resolution / follow_up"),
            html_card("coverage_optimized", "阶段 / 主体 / 来源覆盖"),
            html_card("规则 evidence graph", "可审计图骨架"),
        ],
        fills=["#ECF8EA"] * 3,
        stroke="#91B98F",
        x0=322,
        y=lane_y[1] + 62,
        widths=[405, 365, 365],
        h=96,
        gap=70,
    )
    # Layer 3: SOA attribution.
    attr_ids = ["attr_extract", "attr_candidates", "attr_merge", "attr_tuples"]
    add_card_row(
        builder,
        ids=attr_ids,
        values=[
            html_card("stage_extract", "阶段级候选抽取"),
            html_card("stage_soa_candidates", "候选记录"),
            html_card("canonical_merge", "主体规范化合并"),
            html_card("candidate_soa_tuples", "最终候选tuple"),
        ],
        fills=["#FFF4D9"] * 4,
        stroke="#C9B45D",
        x0=305,
        y=lane_y[2] + 64,
        widths=[285, 315, 300, 330],
        h=92,
        gap=34,
    )
    # Layer 4: faithfulness verification.
    verifier_ids = ["verifier_decomposed", "verifier_diagnosis", "verifier_gate"]
    add_card_row(
        builder,
        ids=verifier_ids,
        values=[
            html_card("decomposed verifier", "字段级检查"),
            html_card("verification_diagnosis", "支持 / 越界 / 矛盾"),
            html_card("质量门控", "过滤弱支持tuple"),
        ],
        fills=["#FCE8E6"] * 3,
        stroke="#CA8A8A",
        x0=390,
        y=lane_y[3] + 66,
        widths=[360, 410, 330],
        h=90,
        gap=65,
    )

    # Layer 5: outputs and evaluation.
    output_ids = ["out_schema", "out_metrics", "out_ablation", "out_audit"]
    add_card_row(
        builder,
        ids=output_ids,
        values=[
            html_card(
                "SOA结构化输出",
                "&lt;Event, Stakeholder, Opinion, Sentiment,<br>Rationale, EventChain, EvidenceIDs&gt;",
            ),
            html_card("metrics / summary", "主实验产物"),
            html_card("ablation outputs", "消融对比"),
            html_card("可审计 / 可复现", "证据ID回溯"),
        ],
        fills=["#F0E6FB"] * 4,
        stroke="#A58BCB",
        x0=285,
        y=lane_y[4] + 64,
        widths=[480, 260, 260, 260],
        h=96,
        gap=38,
    )
    builder.vertex(
        id="chip_evidence",
        value="EvidenceIDs 支撑",
        style=chip_style("#FFFFFF", "#A58BCB"),
        x=318,
        y=lane_y[4] + 174,
        w=260,
        h=34,
        role="chip",
    )

    for ids in (data_ids, graph_ids, attr_ids, verifier_ids, output_ids):
        for idx, (source, target) in enumerate(zip(ids[:-1], ids[1:]), start=1):
            builder.edge(id=f"edge_{source}_{target}_{idx}", source=source, target=target)

    for i in range(4):
        y1 = lane_y[i] + LANE_H
        y2 = lane_y[i + 1]
        builder.point_edge(id=f"edge_lane_{i + 1}_{i + 2}", source=(900, y1), target=(900, y2))

    validate_layout(builder.boxes)
    return ET.ElementTree(wrap_mxfile(builder.model)), builder.boxes


def wrap_mxfile(model: ET.Element) -> ET.Element:
    mxfile = ET.Element(
        "mxfile",
        {
            "host": "Electron",
            "agent": "draw.io Desktop",
            "version": "30.0.4",
            "type": "device",
        },
    )
    diagram = ET.SubElement(mxfile, "diagram", {"id": "episoa-framework", "name": "Page-1"})
    diagram.append(model)
    return mxfile


def overlap(a: Box, b: Box) -> bool:
    return a.x < b.right and a.right > b.x and a.y < b.bottom and a.bottom > b.y


def validate_layout(boxes: list[Box]) -> None:
    lanes = [box for box in boxes if box.role == "lane"]
    foreground = [box for box in boxes if box.role != "lane"]

    for box in boxes:
        if box.x < 0 or box.y < 0 or box.right > CANVAS_W or box.bottom > CANVAS_H:
            raise ValueError(f"Box outside page bounds: {box.id}")

    for box in foreground:
        if box.x < LANE_X + 20 or box.right > LANE_X + LANE_W - 20:
            raise ValueError(f"Foreground box too close to swimlane edge: {box.id}")

    for i, a in enumerate(lanes):
        for b in lanes[i + 1 :]:
            if overlap(a, b):
                raise ValueError(f"Lane overlap: {a.id} overlaps {b.id}")

    for i, a in enumerate(foreground):
        for b in foreground[i + 1 :]:
            if overlap(a, b):
                raise ValueError(f"Foreground overlap: {a.id} overlaps {b.id}")


def write_drawio(path: Path) -> None:
    tree, _ = build_diagram()
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(tree, space="  ")
    tree.write(path, encoding="utf-8", xml_declaration=True)
    validate_drawio(path)


def validate_drawio(path: Path) -> None:
    tree = ET.parse(path)
    root = tree.getroot()
    if root.tag != "mxfile":
        raise ValueError(f"{path} is not an mxfile")
    model = root.find(".//mxGraphModel")
    if model is None:
        raise ValueError("Missing mxGraphModel")
    ids: set[str] = set()
    for cell in model.findall(".//mxCell"):
        id_value = cell.attrib.get("id")
        if not id_value:
            raise ValueError("mxCell without id")
        if id_value in ids:
            raise ValueError(f"Duplicate mxCell id: {id_value}")
        ids.add(id_value)

        if id_value in {"0", "1"}:
            continue
        if "style" not in cell.attrib:
            raise ValueError(f"mxCell without style: {id_value}")
        if cell.find("mxGeometry") is None:
            raise ValueError(f"mxCell without geometry: {id_value}")


def find_drawio_exe(explicit: str | None = None) -> Path:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    env_exe = os.environ.get("DRAWIO_EXE")
    if env_exe:
        candidates.append(Path(env_exe))

    for name in ("drawio", "draw.io", "diagrams.net"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))

    local = os.environ.get("LOCALAPPDATA")
    program_files = [os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")]
    for root in [local, *program_files]:
        if not root:
            continue
        candidates.extend(
            [
                Path(root) / "Programs" / "draw.io" / "draw.io.exe",
                Path(root) / "Programs" / "diagrams.net" / "diagrams.net.exe",
                Path(root) / "draw.io" / "draw.io.exe",
                Path(root) / "diagrams.net" / "diagrams.net.exe",
            ]
        )

    candidates.extend(query_drawio_registry())

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    raise FileNotFoundError(
        "draw.io CLI not found. Install diagrams.net/draw.io or pass --drawio-exe "
        "pointing to draw.io.exe. The .drawio source file was still generated."
    )


def query_drawio_registry() -> list[Path]:
    if winreg is None:
        return []
    roots = [
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    paths: list[Path] = []
    for hive, base in roots:
        try:
            with winreg.OpenKey(hive, base) as base_key:
                for i in range(winreg.QueryInfoKey(base_key)[0]):
                    try:
                        sub_name = winreg.EnumKey(base_key, i)
                        with winreg.OpenKey(base_key, sub_name) as key:
                            display_name = read_reg_value(key, "DisplayName")
                            display_icon = read_reg_value(key, "DisplayIcon")
                    except OSError:
                        continue
                    if display_name and "draw.io" in display_name.lower() and display_icon:
                        exe = display_icon.split(",")[0].strip().strip('"')
                        paths.append(Path(exe))
        except OSError:
            continue
    return paths


def read_reg_value(key: object, name: str) -> str | None:
    try:
        value, _ = winreg.QueryValueEx(key, name)  # type: ignore[union-attr]
    except OSError:
        return None
    return str(value)


def export_with_drawio(drawio_exe: Path, drawio_path: Path) -> None:
    commands = [
        [
            str(drawio_exe),
            "-x",
            "-f",
            "png",
            "-s",
            "3",
            "-b",
            "30",
            "-o",
            str(PNG_PATH),
            str(drawio_path),
        ],
        [
            str(drawio_exe),
            "-x",
            "-f",
            "svg",
            "--embed-svg-fonts",
            "true",
            "-b",
            "30",
            "-o",
            str(SVG_PATH),
            str(drawio_path),
        ],
        [
            str(drawio_exe),
            "-x",
            "-f",
            "pdf",
            "--crop",
            "-b",
            "30",
            "-o",
            str(PDF_PATH),
            str(drawio_path),
        ],
    ]
    for command in commands:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise RuntimeError(
                "draw.io export failed\n"
                f"command: {' '.join(command)}\n"
                f"exit_code: {result.returncode}\n"
                f"stdout: {result.stdout}\n"
                f"stderr: {result.stderr}"
            )

    for path in (PNG_PATH, SVG_PATH, PDF_PATH):
        if not path.exists() or path.stat().st_size == 0:
            raise RuntimeError(f"draw.io export produced a missing or empty file: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the EpiSOA framework draw.io figure.")
    parser.add_argument("--drawio-exe", help="Path to draw.io.exe / diagrams.net executable.")
    parser.add_argument("--no-export", action="store_true", help="Only write and validate the .drawio source.")
    args = parser.parse_args()

    write_drawio(DRAWIO_PATH)
    print(f"Saved draw.io source: {DRAWIO_PATH}")

    if args.no_export:
        return

    drawio_exe = find_drawio_exe(args.drawio_exe)
    print(f"Using draw.io CLI: {drawio_exe}")
    export_with_drawio(drawio_exe, DRAWIO_PATH)
    print(f"Saved PNG: {PNG_PATH}")
    print(f"Saved SVG: {SVG_PATH}")
    print(f"Saved PDF: {PDF_PATH}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise
