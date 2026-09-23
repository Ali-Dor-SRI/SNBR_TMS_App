"""Tests for the body-page composition: each chosen graph occupies half a
portrait US-Letter page.

These assert on the built page figures (how many pages, where each slot's
axes actually sits), never on the source text of ``pdf_layout.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reports.pdf_layout import (
    ITEMS_PER_PAGE,
    PAGE_MARGIN,
    PAGE_SIZE,
    ReportItem,
    compose_two_per_page,
)


def _items(n: int, caption: str | None = None) -> list[ReportItem]:
    return [
        ReportItem(figure=plt.figure(figsize=(4, 3)), caption=caption, section_key="x")
        for _ in range(n)
    ]


def _close(items, pages):
    for item in items:
        plt.close(item.figure)
    for page in pages:
        plt.close(page)


def test_two_items_per_page():
    assert ITEMS_PER_PAGE == 2


def test_page_count_is_two_items_per_page():
    for count, expected_pages in [(1, 1), (2, 1), (3, 2), (4, 2), (5, 3)]:
        items = _items(count)
        pages = compose_two_per_page(items)
        assert len(pages) == expected_pages, f"{count} items"
        _close(items, pages)


def test_no_items_gives_no_pages():
    assert compose_two_per_page([]) == []


def test_each_slot_spans_the_full_content_width():
    items = _items(2)
    pages = compose_two_per_page(items)
    content_width = 1.0 - 2.0 * (PAGE_MARGIN / PAGE_SIZE[0])

    # ``original=True`` reports the slot rectangle the layout asked for;
    # ``imshow`` then shrinks the drawn axes inside it to keep the figure's
    # aspect ratio, which is deliberate (a graph is never stretched).
    for ax in pages[0].axes:
        box = ax.get_position(original=True)
        assert box.width == pytest_approx(content_width), (
            "a half-page slot must span the whole content width"
        )
    _close(items, pages)


def test_each_slot_occupies_about_half_the_page_height():
    items = _items(2)
    pages = compose_two_per_page(items)
    content_height = 1.0 - 2.0 * (PAGE_MARGIN / PAGE_SIZE[1])

    boxes = sorted((ax.get_position(original=True) for ax in pages[0].axes), key=lambda b: b.y0)
    assert len(boxes) == 2, "one image axis per slot when there are no captions"
    for box in boxes:
        # Half the content height, minus the caption band and the inter-slot gap.
        assert 0.40 * content_height < box.height < 0.50 * content_height

    bottom, top = boxes
    assert top.y0 > bottom.y1, "the two slots must not overlap vertically"
    _close(items, pages)


def test_first_item_is_the_top_half_and_second_the_bottom_half():
    items = _items(2)
    pages = compose_two_per_page(items)
    first_ax, second_ax = pages[0].axes
    assert first_ax.get_position(original=True).y0 > second_ax.get_position(original=True).y0
    _close(items, pages)


def test_odd_item_count_leaves_the_last_bottom_half_blank():
    items = _items(3)
    pages = compose_two_per_page(items)
    assert len(pages[0].axes) == 2
    assert len(pages[1].axes) == 1
    _close(items, pages)


def test_caption_sits_directly_beneath_its_image():
    items = _items(1, caption="patient 1.0 | controls 2.0")
    pages = compose_two_per_page(items)
    image_ax, caption_ax = pages[0].axes
    image_box = image_ax.get_position(original=True)
    caption_box = caption_ax.get_position(original=True)

    assert caption_box.y1 == pytest_approx(image_box.y0)
    assert caption_box.x0 == pytest_approx(image_box.x0)
    assert caption_box.width == pytest_approx(image_box.width)
    texts = [t.get_text() for t in caption_ax.texts]
    assert "patient 1.0 | controls 2.0" in texts
    _close(items, pages)


def pytest_approx(value, tol: float = 1e-9):
    import pytest

    return pytest.approx(value, abs=tol)
