"""dispatch/batch.py -- attachment names, part packing, email text, the folder."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from dispatch.batch import (
    MB, BatchEntry, attachment_filename, mailto_url, mark_part_sent, plan_parts,
    render_body, render_subject, write_batch,
)
from dispatch.identity import Identity, ParticipantKey
from dispatch.ledger import STATUS_REVISION, STATUS_SENT, STATUS_UNSENT, Ledger
from dispatch.report_index import ReportFile
from dispatch.worklist import WorklistItem


def _item(number, name="John Smith", mrn="1234567", status=STATUS_UNSENT, path=None, reason="", size=10):
    key = ParticipantKey("SNBR", number)
    report = ReportFile(
        path=path or Path(f"report_SNBR_{number:03d}_20260818.pdf"), key=key,
        visit_date=date(2026, 8, 18), sha256=f"{number:064d}", size=size,
        mtime=datetime(2026, 9, 8, 9),
    )
    identity = Identity(key, f"AA-SNBR-{number:03d}", name, mrn) if name is not None else None
    return WorklistItem(report=report, identity=identity, status=status, unresolved_reason=reason)


def _entry(name, size=10, item=None):
    return BatchEntry(item=item or _item(1), filename=name, path=Path(name), size=size)


def test_attachment_name_is_name_as_written_then_mrn_then_visit():
    assert attachment_filename(_item(80, "John Smith", "1234567")) == "John_Smith_1234567_20260818.pdf"
    assert attachment_filename(_item(80, "Mary-Anne O'Neil", "7")) == "Mary-Anne_O'Neil_7_20260818.pdf"


def test_a_missing_field_is_dropped_from_the_name_not_the_whole_identity():
    """A blank MRN used to send the report out under its anonymous name."""
    assert attachment_filename(_item(80, "John Smith", "")) == "John_Smith_20260818.pdf"
    assert attachment_filename(_item(80, "  ", "1234567")) == "1234567_20260818.pdf"


def test_only_a_wholly_unidentified_report_keeps_the_deidentified_source_name():
    assert attachment_filename(_item(80, None)) == "report_SNBR_080_20260818.pdf"
    assert attachment_filename(_item(80, "", "")) == "report_SNBR_080_20260818.pdf"


def test_parts_fill_first_fit_and_oversize_goes_alone():
    cap = 20 * MB
    entries = [_entry("a", 8 * MB), _entry("b", 8 * MB), _entry("c", 8 * MB),
               _entry("d", 25 * MB), _entry("e", 1 * MB)]
    parts, warnings = plan_parts(entries, cap)
    assert [[e.filename for e in p] for p in parts] == [["a", "b"], ["c"], ["d"], ["e"]]
    assert len(warnings) == 1 and "d is 25.0 MB" in warnings[0]


def test_everything_fits_in_one_part_when_under_the_cap():
    parts, warnings = plan_parts([_entry("a", MB), _entry("b", MB)], 20 * MB)
    assert len(parts) == 1 and warnings == []


def test_subject_template():
    t = "SNBR TMS reports - week of {week_start}{part}"
    assert render_subject(t, date(2026, 9, 7), 1, 1, 3) == "SNBR TMS reports - week of 07/09/2026"
    assert render_subject(t, date(2026, 9, 7), 2, 3, 3) == "SNBR TMS reports - week of 07/09/2026 (part 2 of 3)"
    assert render_subject("{count} reports", date(2026, 9, 7), 1, 1, 3) == "3 reports"


def test_body_is_a_count_plus_only_the_blocks_that_apply():
    plain = [_entry("a.pdf"), _entry("b.pdf")]
    assert render_body(plain, 1, 1) == "2 reports attached.\n"
    assert render_body(plain[:1], 1, 1) == "1 report attached.\n"
    assert "Part 2 of 3." in render_body(plain, 2, 3)

    revised = _entry("r.pdf", 1, _item(5, status=STATUS_REVISION))
    unresolved = _entry("report_SNBR_006_20260818.pdf", 1, _item(6, None, reason="not in the roster"))
    body = render_body(plain + [revised, unresolved], 1, 1)
    assert "4 reports attached." in body
    assert "Revised reports" in body and "  - r.pdf" in body
    assert "de-identified" in body
    assert "  - report_SNBR_006_20260818.pdf  (not in the roster)" in body


def test_partly_identified_reports_are_listed_apart_from_de_identified_ones():
    """A report carrying a name but no MRN is identified, just incompletely --
    listing it under "sent de-identified" misdescribes what the recipient has."""
    partial = _entry("John_Smith_20260818.pdf", 1,
                     _item(7, "John Smith", "", reason="roster row lacks MRN"))
    anonymous = _entry("report_SNBR_008_20260818.pdf", 1,
                       _item(8, None, reason="SNBR-008 is not in the roster"))
    body = render_body([partial, anonymous], 1, 1)

    assert "Reports with incomplete identification:" in body
    assert "  - John_Smith_20260818.pdf  (roster row lacks MRN)" in body
    assert "Reports sent de-identified (no patient identity could be resolved):" in body
    assert "  - report_SNBR_008_20260818.pdf  (SNBR-008 is not in the roster)" in body
    # The partial one must not appear under the de-identified heading.
    tail = body[body.index("Reports sent de-identified"):]
    assert "John_Smith" not in tail

    # Neither block appears when every report is fully identified.
    clean = render_body([_entry("a.pdf")], 1, 1)
    assert "incomplete identification" not in clean and "de-identified" not in clean


def test_mailto_encodes_subject_and_body():
    url = mailto_url(["a@sunnybrook.ca", "b@sunnybrook.ca"], "week of 07/09", "2 reports attached.\n")
    assert url.startswith("mailto:a@sunnybrook.ca,b@sunnybrook.ca?subject=week%20of%2007%2F09&body=")
    assert "%0A" in url


# -- the folder ------------------------------------------------------------

pypdf = pytest.importorskip("pypdf")


@pytest.fixture
def report_pdf(tmp_path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    import numpy as np

    def make(name, big=False):
        """A one-page PDF; *big* embeds incompressible noise (~1.2 MB)."""
        path = tmp_path / "exports" / name
        path.parent.mkdir(exist_ok=True)
        fig = plt.figure(figsize=(8.5, 11))
        fig.text(0.1, 0.9, name)
        if big:
            ax = fig.add_axes((0.1, 0.1, 0.8, 0.6))
            ax.imshow(np.random.default_rng(0).random((450, 450, 3)))
            ax.set_axis_off()
        fig.savefig(path, format="pdf")
        plt.close(fig)
        return path
    return make


def test_write_batch_builds_parts_email_files_and_records_the_run(tmp_path, report_pdf):
    items = [
        _item(80, "John Smith", "1", path=report_pdf("report_SNBR_080_20260818.pdf")),
        _item(81, "Jane Doe", "2", path=report_pdf("report_SNBR_081_20260818.pdf"), status=STATUS_REVISION),
        _item(82, None, path=report_pdf("report_SNBR_082_20260818.pdf"), reason="not in the roster"),
    ]
    ledger = Ledger(tmp_path / "ledger.jsonl")
    batch = write_batch(
        items, tmp_path / "identified", ["dr@sunnybrook.ca"], 20,
        "Reports {week_start}{part}", ledger=ledger, when=datetime(2026, 9, 8, 14, 0),
    )
    assert batch.folder.parent == tmp_path / "identified"
    assert batch.folder.name.startswith("2026-09-08_batch_20260908-140000-")
    assert batch.count == 3 and len(batch.parts) == 1 and batch.warnings == []
    assert not (batch.folder / "_staging").exists()

    part = batch.parts[0]
    assert part.folder == batch.folder / "part_1_of_1"
    assert sorted(p.name for p in part.folder.iterdir()) == [
        "Jane_Doe_2_20260818.pdf", "John_Smith_1_20260818.pdf", "report_SNBR_082_20260818.pdf",
    ]
    assert part.subject == "Reports 07/09/2026"
    email = part.email_path.read_text(encoding="utf-8")
    assert email.startswith("To: dr@sunnybrook.ca\nSubject: Reports 07/09/2026\n\n3 reports attached.")
    assert "  - Jane_Doe_2_20260818.pdf" in email
    assert "  - report_SNBR_082_20260818.pdf  (not in the roster)" in email

    cover = pypdf.PdfReader(str(part.folder / "John_Smith_1_20260818.pdf")).pages[0].extract_text()
    assert "PATIENT IDENTIFICATION" in cover and "John Smith" in cover
    unresolved = pypdf.PdfReader(str(part.folder / "report_SNBR_082_20260818.pdf")).pages[0].extract_text()
    assert "IDENTITY NOT RESOLVED" in unresolved

    run = ledger.state().last_run()
    assert run["run_id"] == batch.run_id and run["count"] == 3 and run["parts"] == 1
    # Writing the batch marks nothing sent: the operator declares that.
    assert all(ledger.state().status(i.report) in (STATUS_UNSENT, STATUS_REVISION) for i in items)


def test_write_batch_splits_at_the_cap_and_names_parts(tmp_path, report_pdf):
    items = [_item(n, f"P {n}", str(n), path=report_pdf(f"report_SNBR_{n:03d}_20260818.pdf", big=True)) for n in (1, 2, 3)]
    one_pdf = items[0].report.path.stat().st_size
    cap_mb = 2
    assert one_pdf < cap_mb * MB < 3 * one_pdf, "fixture sizing assumption"
    batch = write_batch(items, tmp_path / "identified", [], cap_mb, "s{part}", when=datetime(2026, 9, 8))
    assert len(batch.parts) >= 2
    assert [p.folder.name for p in batch.parts] == [f"part_{i}_of_{len(batch.parts)}" for i in range(1, len(batch.parts) + 1)]
    assert batch.parts[0].subject == f"s (part 1 of {len(batch.parts)})"
    assert all(p.total_bytes <= cap_mb * MB for p in batch.parts)


def test_duplicate_attachment_names_are_uniquified(tmp_path, report_pdf):
    a = _item(80, "John Smith", "1", path=report_pdf("report_SNBR_080_20260818.pdf"))
    b = _item(80, "John Smith", "1", path=report_pdf("report_SNBR_080_20260818_2.pdf"))
    batch = write_batch([a, b], tmp_path / "identified", [], 20, "s", when=datetime(2026, 9, 8))
    names = sorted(e.filename for e in batch.parts[0].entries)
    assert names == ["John_Smith_1_20260818.pdf", "John_Smith_1_20260818_2.pdf"]


def test_empty_selection_is_refused(tmp_path):
    with pytest.raises(ValueError):
        write_batch([], tmp_path, [], 20, "s")


def test_mark_part_sent_records_each_and_refuses_repeats(tmp_path, report_pdf):
    items = [_item(80, "J S", "1", path=report_pdf("report_SNBR_080_20260818.pdf"))]
    ledger = Ledger(tmp_path / "ledger.jsonl")
    batch = write_batch(items, tmp_path / "identified", ["dr@sunnybrook.ca"], 20, "s", ledger=ledger)
    results = mark_part_sent(ledger, batch, batch.parts[0])
    assert [(r[1], r[2]) for r in results] == [(True, "recorded")]
    assert ledger.state().status(items[0].report) == STATUS_SENT
    again = mark_part_sent(ledger, batch, batch.parts[0])
    assert again[0][1] is False and "already marked sent" in again[0][2]
