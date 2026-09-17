"""Generate four physical PDF pages of clearly synthetic project-plan facts."""

from __future__ import annotations

from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas


ROWS = (
    ("项目背景", "项目背景：示例研发项目需要统一管理需求、开发、测试和验收材料。"),
    ("项目目标", "项目目标：完成结构化研发文档整理，并形成可人工审核的项目计划草稿。"),
    ("阶段划分", "阶段划分：项目分为需求梳理、方案设计、开发测试、验收准备四个阶段。"),
    ("验收依据", "验收依据：以需求规格说明书、测试报告和验收检查表为依据。"),
)


def main() -> None:
    output = Path(__file__).resolve().parents[1] / "data/rd_v2_corpus/raw/safe-project-plan.pdf"
    if output.exists():
        raise RuntimeError("safe synthetic PDF already exists; refusing overwrite")
    output.parent.mkdir(parents=True, exist_ok=True)
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    pdf = canvas.Canvas(str(output))
    pdf.setTitle("Synthetic Project Plan")
    for title, content in ROWS:
        pdf.setFont("STSong-Light", 15)
        pdf.drawString(72, 760, title)
        pdf.setFont("STSong-Light", 12)
        pdf.drawString(72, 720, content)
        pdf.showPage()
    pdf.save()
    print(f"SAFE_PDF=PASS pages={len(ROWS)}")


if __name__ == "__main__":
    main()
