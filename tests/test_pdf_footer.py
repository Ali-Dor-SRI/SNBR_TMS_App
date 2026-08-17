"""Tests for the report footer (date generated + page N of N) and the cover
'Date generated' field.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reports.pdf_layout import (
    ReportItem,
    generation_date_string,
    stamp_page_footer,
)
from reports import pdf_renderer
from reports.report_builder import build_header_only_figure


def test_generation_date_string_format():
    assert generation_date_string(datetime(2026, 7, 13)) == "13/07/2026"


def test_stamp_page_footer_adds_left_and_right_text():
    fig = plt.figure(figsize=(8.5, 11.0))
    stamp_page_footer(fig, page_number=2, total_pages=5, date_generated="13/07/2026")
    texts = [t.get_text() for t in fig.texts]
    assert "Date generated: 13/07/2026" in texts
    assert "Page 2 of 5" in texts
    # Date stamp is left-aligned, page stamp right-aligned.
    by_text = {t.get_text(): t for t in fig.texts}
    assert by_text["Date generated: 13/07/2026"].get_ha() == "left"
    assert by_text["Page 2 of 5"].get_ha() == "right"
    plt.close(fig)


def test_header_figure_includes_generation_date():
    rows = pd.DataFrame({
        "Study": ["SNBR"],
        "ID": [7],
        "Age": [55],
        "Sex": ["M"],
        "Subject_type": ["Patient"],
        "Stimulated_cortex": ["L"],
    })
    fig = build_header_only_figure(rows, participant_label="SNBR-007")
    labels = [t.get_text() for ax in fig.axes for t in ax.texts]
    assert any("Date generated" in text for text in labels)
    plt.close(fig)


def test_render_stamps_every_page_with_cover_as_page_one(monkeypatch, tmp_path):
    calls: list[tuple[int, int]] = []

    def _fake_stamp(page_fig, page_number, total_pages, date_generated):
        calls.append((page_number, total_pages))
        return page_fig

    monkeypatch.setattr(pdf_renderer, "stamp_page_footer", _fake_stamp)

    summary_fig = plt.figure(figsize=(3, 2))
    items = [ReportItem(figure=summary_fig, caption=None, section_key="summary")]
    body_figs = []
    for _ in range(5):  # 5 body items -> ceil(5/4) = 2 body pages
        f = plt.figure(figsize=(3, 2))
        body_figs.append(f)
        items.append(ReportItem(figure=f, caption=None, section_key="x"))

    out = pdf_renderer.render_figures_to_pdf(items, tmp_path / "report.pdf")

    assert out.is_file()
    assert out.stat().st_size > 0
    # Cover + 2 body pages = 3 pages; cover is page 1 of 3.
    assert calls == [(1, 3), (2, 3), (3, 3)]

    plt.close(summary_fig)
    for f in body_figs:
        plt.close(f)
