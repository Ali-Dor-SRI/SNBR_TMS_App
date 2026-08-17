"""
Shared post-styling for report plots: enlarge axis text and add breathing room.

The plotting engines (``processing._v1_visualization`` and
``reports.report_builder``) draw each figure with their own hard-coded font
sizes.  Rather than editing dozens of scattered size literals, this module
applies one uniform, tunable pass over a *finished* figure — multiplying every
text element by :data:`FONT_SCALE` and widening the gap between the text and the
plot.

It is applied once to each **plot** figure at the two render boundaries so the
in-app previews and the exported PDF / CLI reports stay in sync:

* GUI path  — ``gui.controller.AppController.generate_figure``
* CLI path  — ``reports.report_builder.build_report_figures``

Table figures (CMAP / MUNIX / visit table) and the letterhead summary have
hand-tuned layouts, so callers skip them.

To change the look, edit the four constants below in this one place.
"""
from __future__ import annotations

# ── House style ────────────────────────────────────────────────────────────
# Every text element is multiplied by FONT_SCALE; the *_PAD values are the gap
# (in points) placed between the text and the plot.
FONT_SCALE = 1.5        # multiplier applied to every font size on the figure
TICK_PAD = 11.0         # gap: tick numbers  ↔ axis
AXIS_LABEL_PAD = 22.0   # gap: x/y axis label ↔ tick numbers
TITLE_PAD = 34.0        # gap: title          ↔ top of the plot

# Marker set on a figure once it has been enlarged, so a figure that is somehow
# passed through twice is not scaled twice.
_ENLARGED_FLAG = "_snbr_fonts_enlarged"


def _default_tick_size() -> float:
    """Resolve the default tick-label size to points.

    ``rcParams['xtick.labelsize']`` may be a keyword like ``'medium'`` (used as
    the fallback when an axis has no visible tick labels), which is not directly
    float()-able — resolve it through matplotlib's font machinery.
    """
    import matplotlib.pyplot as plt
    from matplotlib.font_manager import FontProperties

    raw = plt.rcParams.get("xtick.labelsize", 10)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return FontProperties(size=raw).get_size_in_points()


def enlarge_axes_fonts(
    fig,
    scale: float = FONT_SCALE,
    tick_pad: float = TICK_PAD,
    label_pad: float = AXIS_LABEL_PAD,
    title_pad: float = TITLE_PAD,
):
    """Scale every text element on *fig* by *scale* and add axis-to-text margin.

    Safe to call on any single figure; idempotent per figure (guarded by a
    marker attribute).  Returns *fig* for convenient chaining.

    Tick-label sizes and pads are set through the durable ``set_tick_params``
    API so they survive the redraw that ``savefig`` triggers; the title is
    re-applied with the new pad while preserving its (already-scaled) size and
    colour.
    """
    if fig is None or getattr(fig, _ENLARGED_FLAG, False):
        return fig

    try:
        fig.canvas.draw()  # materialise tick labels so their base size is readable
    except Exception:
        pass

    for ax in fig.get_axes():
        # Tick labels: size + pad via the durable API (re-applied on redraw).
        for axis_obj, get_labels in (
            (ax.xaxis, ax.get_xticklabels), (ax.yaxis, ax.get_yticklabels),
        ):
            sized = [lbl.get_fontsize() for lbl in get_labels() if lbl.get_text()]
            base = sized[0] if sized else _default_tick_size()
            axis_obj.set_tick_params(labelsize=base * scale, pad=tick_pad)

        # Gap between the axis label and the tick numbers.
        ax.xaxis.labelpad = label_pad
        ax.yaxis.labelpad = label_pad

        # Scale the persistent Text objects (labels, title, offset text).
        for text_obj in (
            ax.title, ax.xaxis.label, ax.yaxis.label,
            ax.xaxis.get_offset_text(), ax.yaxis.get_offset_text(),
        ):
            text_obj.set_fontsize(text_obj.get_fontsize() * scale)

        # Re-apply the title with more headroom, preserving the scaled props.
        if ax.title.get_text():
            title = ax.title
            ax.set_title(
                title.get_text(), fontsize=title.get_fontsize(),
                color=title.get_color(), fontweight=title.get_fontweight(),
                loc="center", pad=title_pad,
            )

        # In-plot annotations / ax.text (reference-line labels, cohort stats…).
        for text_obj in ax.texts:
            text_obj.set_fontsize(text_obj.get_fontsize() * scale)

        # Legend entries + legend title.
        legend = ax.get_legend()
        if legend is not None:
            for text_obj in legend.get_texts():
                text_obj.set_fontsize(text_obj.get_fontsize() * scale)
            if legend.get_title() is not None:
                legend.get_title().set_fontsize(legend.get_title().get_fontsize() * scale)

    # Figure-level text (suptitle, fig.text).
    for text_obj in fig.texts:
        text_obj.set_fontsize(text_obj.get_fontsize() * scale)
    if getattr(fig, "_suptitle", None) is not None:
        fig._suptitle.set_fontsize(fig._suptitle.get_fontsize() * scale)

    # Re-tighten so the larger text / wider pads don't collide with the axes.
    try:
        fig.tight_layout()
    except Exception:
        pass

    setattr(fig, _ENLARGED_FLAG, True)
    return fig


def enlarge_result_figures(result, **kwargs):
    """Enlarge every figure in a plot result and return it unchanged in shape.

    Accepts the ``(fig_or_figs, axes, data)`` tuple returned by the plotting
    functions, a bare ``Figure``, or a list of figures — so it can wrap a
    plotting call directly::

        return enlarge_result_figures(plot_mem_graph(...))
    """
    if result is None:
        return result

    if isinstance(result, tuple) and result:
        figs = result[0]
    else:
        figs = result

    if isinstance(figs, list):
        for fig in figs:
            enlarge_axes_fonts(fig, **kwargs)
    else:
        enlarge_axes_fonts(figs, **kwargs)

    return result
