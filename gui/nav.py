"""Pure workflow-navigation helpers.

Kept free of any GUI imports so the linear Next/Back logic (which must skip
pages the user has hidden via "Skip this page in future runs") can be unit
tested without a Tk root.
"""

from __future__ import annotations


def next_visible_page(page_order: list[str], skipped: set[str], current: str) -> str:
    """Return the next page after *current* that is not in *skipped*.

    Falls back to the last page when every later page is skipped, and to
    *current* itself when it isn't in *page_order* (defensive — navigation only
    ever passes known page names).
    """
    if current not in page_order:
        return current
    idx = page_order.index(current)
    for name in page_order[idx + 1:]:
        if name not in skipped:
            return name
    return page_order[-1]


def prev_visible_page(page_order: list[str], skipped: set[str], current: str) -> str:
    """Return the previous page before *current* that is not in *skipped*."""
    if current not in page_order:
        return current
    idx = page_order.index(current)
    for name in reversed(page_order[:idx]):
        if name not in skipped:
            return name
    return page_order[0]
