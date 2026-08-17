"""
Assemble matplotlib figures into a multi-page PDF file.

This module is the final step in the report pipeline:

    parser -> df_builder -> report_builder (figures) -> **pdf_renderer** (PDF)

Every page is rendered as portrait US Letter (8.5" x 11") with up to two
visualizations per page.  The first page carries an institutional
letterhead banner with the participant summary beneath it.  Each
subsequent visualization may carry a short caption line showing raw
values (patient, controls, ALS).

Public API
----------
render_figures_to_pdf(items_or_figures, output_path) -> Path
generate_participant_report(participant_id, data_df, ...) -> Path
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from reports.pdf_layout import (
    ReportItem,
    build_letterhead_banner_page,
    compose_four_per_page,
    generation_date_string,
    stamp_page_footer,
)
from reports.report_builder import build_report_figures


# ---------------------------------------------------------------------------
# Output path helpers
# ---------------------------------------------------------------------------

def resolve_report_output_path(
    participant_label: str,
    output_pdf: str | Path | None = None,
    reports_dir: str | Path | None = None,
) -> Path:
    """Resolve the PDF output path, using a timestamped default when needed."""
    if output_pdf is not None:
        path = Path(output_pdf)
        if path.suffix.lower() != ".pdf":
            path = path.with_suffix(".pdf")
    else:
        target = Path(reports_dir) if reports_dir is not None else _default_reports_dir()
        ts = datetime.now().strftime("%Y%m%d%H%M")
        path = target / f"{participant_label}_MEM_report_{ts}.pdf"

    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _default_reports_dir() -> Path:
    """Return a sensible default reports directory relative to the project."""
    from core.config import PROJECT_ROOT
    return PROJECT_ROOT / "5_Reports"


# ---------------------------------------------------------------------------
# Input coercion
# ---------------------------------------------------------------------------

def _coerce_to_items(inputs: list) -> list[ReportItem]:
    """Accept either bare matplotlib figures or ``ReportItem``s and return items.

    Bare figures become items with no caption or section key.  This keeps
    the GUI's ``render_figures_to_pdf(list[Figure])`` call path working.
    """
    coerced: list[ReportItem] = []
    for entry in inputs:
        if entry is None:
            continue
        if isinstance(entry, ReportItem):
            if entry.figure is not None:
                coerced.append(entry)
        else:
            coerced.append(ReportItem(figure=entry, caption=None, section_key=None))
    return coerced


def _split_summary_and_body(items: list[ReportItem]) -> tuple[ReportItem | None, list[ReportItem]]:
    """If the first item is the participant summary, separate it from the rest."""
    if items and items[0].section_key == "summary":
        return items[0], items[1:]
    return None, items


# ---------------------------------------------------------------------------
# PDF assembly
# ---------------------------------------------------------------------------

def render_figures_to_pdf(
    items_or_figures: list,
    output_path: str | Path,
) -> Path:
    """Save a list of visualizations to a multi-page portrait-Letter PDF.

    Parameters
    ----------
    items_or_figures : list
        Either a list of ``ReportItem`` (from
        :func:`report_builder.build_report_figures`) or a plain list of
        matplotlib figures (GUI export path).  Both are accepted.
    output_path : path
        Destination PDF file.

    Returns
    -------
    Path
        The resolved output path.
    """
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    items = _coerce_to_items(items_or_figures)
    summary_item, body_items = _split_summary_and_body(items)

    first_page = build_letterhead_banner_page(
        summary_fig=summary_item.figure if summary_item is not None else None,
    )
    body_pages = compose_four_per_page(body_items)

    # Stamp every page (cover included) with the generation date and page
    # number. The count includes the cover, so the cover reads "Page 1 of N".
    all_pages = [first_page, *body_pages]
    date_generated = generation_date_string()
    total_pages = len(all_pages)
    for page_number, page in enumerate(all_pages, start=1):
        stamp_page_footer(page, page_number, total_pages, date_generated)

    with PdfPages(output_path) as pdf:
        for page in all_pages:
            pdf.savefig(page)

    # Clean up the composed page figures (originals are owned by the caller).
    for page in all_pages:
        plt.close(page)

    return output_path.resolve()


# ---------------------------------------------------------------------------
# Convenience: full report in one call
# ---------------------------------------------------------------------------

def _build_all_target_figures(
    participant_id,
    data_df: pd.DataFrame,
    **kwargs,
) -> list:
    """Build report figures, once per recording target when there is more than one.

    A visit recorded from several muscles (left FDI, right FDI, right TA) would
    otherwise draw all of them onto the same axes as if they were repeats of
    one recording. Each target instead gets its own set of sections, named in
    the figure titles; the title page is built once, from the first target's
    pass, and already lists every muscle recorded.
    """
    from processing.df_builder import target_labels_in

    rows = data_df[pd.to_numeric(data_df["ID"], errors="coerce") == participant_id]
    targets = target_labels_in(rows)
    if len(targets) < 2:
        return build_report_figures(
            participant_id=participant_id, data_df=data_df, **kwargs,
        )

    items: list = []
    sections = kwargs.pop("included_sections", None)
    for index, target in enumerate(targets):
        target_items = build_report_figures(
            participant_id=participant_id,
            data_df=data_df,
            included_sections=sections,
            recording_target=target,
            **kwargs,
        )
        if index > 0:
            # One title page for the whole report, not one per muscle.
            target_items = [
                it for it in target_items
                if getattr(it, "section_key", None) != "summary"
            ]
        items.extend(target_items)
    return items


def generate_participant_report(
    participant_id,
    data_df: pd.DataFrame,
    output_pdf: str | Path | None = None,
    reports_dir: str | Path | None = None,
    included_sections=None,
    age_window: int = 5,
    show: bool = False,
    mem_date: str | None = None,
    mem_dir=None,
) -> Path:
    """Generate a multi-page PDF report for one participant.

    This is the main entry point for the V2 report pipeline.  It:

    1. Calls :func:`report_builder.build_report_figures` to generate all
       requested section figures (as :class:`ReportItem` objects).
    2. Calls :func:`render_figures_to_pdf` to assemble them into a PDF
       with portrait Letter pages, letterhead banner, and raw-value
       captions beneath each visualization.

    Parameters
    ----------
    participant_id : int
        SNBR participant ID.
    data_df : pd.DataFrame
        Full parsed MEM DataFrame (from ``df_builder``).
    output_pdf : path, optional
        Explicit output path.  When ``None``, a timestamped name is generated
        inside *reports_dir*.
    reports_dir : path, optional
        Directory for report output.  Ignored when *output_pdf* is set.
    included_sections : str or list, optional
        Which sections to include (``None`` = default set).
    age_window : int
        Window for age-matched comparisons.
    show : bool
        Whether to display figures interactively.
    mem_date : str, optional
        Visit date to anchor group comparisons on.  When ``None`` or when
        the date has no data for this participant, the most recent visit is
        used.

    Returns
    -------
    Path
        The path of the generated PDF file.
    """
    from processing.visualizer import format_participant_label

    plabel = format_participant_label(participant_id)
    output_path = resolve_report_output_path(
        participant_label=plabel,
        output_pdf=output_pdf,
        reports_dir=reports_dir,
    )

    import matplotlib.pyplot as plt

    items = _build_all_target_figures(
        participant_id=participant_id,
        data_df=data_df,
        included_sections=included_sections,
        age_window=age_window,
        show=show,
        mem_date=mem_date,
        mem_dir=mem_dir,
    )

    try:
        return render_figures_to_pdf(items, output_path)
    finally:
        # Close the per-section figures built above so matplotlib doesn't
        # hold onto 20+ open figures after the report is written.
        for item in items:
            fig = getattr(item, "figure", None)
            if fig is not None:
                plt.close(fig)
