# SNBR TMS App — Architecture Overview

*A guided tour of how this application is put together. Aimed at readers with moderate
coding/computer knowledge — you do not need to be a Python expert to follow it.*

---

## 1. What the app does, in one paragraph

Research staff in the ALS Neurophysiology & Neuromodulation Lab run nerve/brain-stimulation
sessions using a program called **Qtrack / QtracP**. Each session produces a `.MEM` text file
(and sometimes a nerve-conduction report as a PDF or Word file). This app **reads those files,
pulls out the measurements, and organizes them into a single table** (a spreadsheet-like
structure). From that table it **draws graphs and builds a polished PDF report** for one
participant, comparing them against two reference groups: healthy controls and people with ALS.
It can also export the table as a CSV, push the values into the lab's **REDCap** database,
**email** the report, and **back up** files to another folder. Everything runs offline on a lab
Windows PC — the only feature that touches the internet is the optional email step.

**Who uses it:** lab research staff, not programmers. So the app is a click-through wizard, and
the code is organized to keep the user-facing screens separate from the data-crunching engine.

---

## 2. The big picture: three layers

The code is split into three layers. The golden rule is that **information only flows through the
middle layer** — the screens never talk to the data engine directly.

```
┌───────────────────────────────────────────────────────────────────────────┐
│  LAYER 1 — GUI  (gui/)                                                       │
│  The CustomTkinter wizard the user clicks through: 11 pages + a toolbar.     │
│  Panels: welcome, file, data_mode, exclusion, participant, visualization,   │
│          export, email, redcap, sync, finish, settings                      │
└───────────────────────────────┬───────────────────────────────────────────┘
                                 │  every call goes through ONE object
                                 ▼
┌───────────────────────────────────────────────────────────────────────────┐
│  LAYER 2 — CONTROLLER  (gui/controller.py, AppController)                    │
│  The single "switchboard." Holds the current session state (chosen paths,   │
│  the loaded table, the selected participant, the built figures) and calls    │
│  the backend on the user's behalf. This is the ONLY place the two worlds meet.│
└───────────────────────────────┬───────────────────────────────────────────┘
                                 │
                                 ▼
┌───────────────────────────────────────────────────────────────────────────┐
│  LAYER 3 — BACKEND  (parser/  processing/  reports/  emailing/  back_up_sync/)│
│  Pure data/logic. Reads files, builds the table, draws figures, writes PDFs, │
│  exports REDCap/CSV, sends email, syncs folders. Knows nothing about the GUI. │
│  Can be run headlessly from a script or a test.                              │
└───────────────────────────────────────────────────────────────────────────┘
```

**Why this matters:** because the backend never imports the GUI, you can build a report or parse a
file from a plain script or a unit test — no window required. And because the GUI only ever calls
`AppController`, there is exactly one place to look when wiring a screen to a piece of logic.

**Threading:** the GUI must stay responsive, so any slow work (parsing hundreds of files, drawing
graphs, sending email, syncing) runs on a **background thread**. When it finishes, the result is
handed back to the screen safely via `self.after(0, ...)`. Nothing heavy runs on the main window
thread.

---

## 3. The one idea to hold onto: everything is one table

At the heart of the app is a single **wide table** (a pandas *DataFrame*). Think of a spreadsheet:

- **Each row = one participant on one visit date.** If several `.MEM` files were recorded for the
  same person on the same day (e.g. one file has the resting motor threshold, another has a
  paired-pulse protocol), they are **merged into a single row** so the visit is one line.
- **Each column = one measurement** (e.g. `RMT50`, `T_SICI_1.0ms`, `CSP_120`, `SR_max_cmap_1ms`)
  plus bookkeeping columns like `ID`, `Date`, `Age`, `Sex`, `Study`, and `source_file` (which
  remembers exactly which files produced the row).

The exact list and order of columns is defined in **one place**:
`parser/mem_parser.py → output_column_order()`. Everything downstream — the CSV you export, the
graphs, the REDCap mapping — depends on that schema, which is why it is treated as off-limits to
casual edits.

There is **no** custom "record" class or `models.py`; the DataFrame *is* the data model.

---

## 4. Data pipeline: from raw files to a report

Here is the end-to-end flow. Read it top to bottom.

```
  RAW FILES (chosen by the user)                     WHAT HAPPENS
  ────────────────────────────                       ────────────
  .MEM  (TMS cortical)      ─┐
  .MEM  (CSP)               ─┤   parser/*            Each file is read and turned into a
  .MEM  (Stimulus-Response) ─┤   → plain dicts       plain Python dict of values.
  .pdf / .docx (CMAP/MUNIX) ─┘                       (Parsers never build tables themselves.)
                                   │
                                   ▼
                          processing/df_builder.py    Dicts become the one wide table:
                          → the wide DataFrame         • CSP + CMAP data merged in by (ID, date)
                                   │                    • same-day files coalesced into one row
                                   │                    • can rebuild incrementally from a saved CSV
                                   ▼
        ┌──────────────────────────┼───────────────────────────────┐
        ▼                          ▼                               ▼
  processing/visualizer.py   reports/csv_exporter.py     reports/redcap_exporter.py
  (→ _v1_visualization.py)   → timestamped CSV           → REDCap import CSV (only changed cells)
  draws matplotlib figures         │                               │
        │                          │                               │
        ▼                          ▼                               ▼
  reports/report_builder.py    (an archive you can       (import straight into the lab's
  picks which figures go in     reopen later, fast)        REDCap database)
  the report, adds captions
        │
        ▼
  reports/pdf_layout.py  +  reports/pdf_renderer.py
  arranges figures 4-per-page under a letterhead banner,
  writes the multi-page PDF
        │
        ▼
  emailing/  (optional) — email the PDF over SMTP
```

The **archive CSV** is an important shortcut: once files have been parsed, the table is saved as a
timestamped CSV. Next time, the app can reload that CSV instantly and only parse **new** files it
has not seen — so a returning user does not re-parse everything.

---

## 5. The backend pieces in detail

### 5.1 Parsers (`parser/`) — read files, return dicts

Each parser knows how to read one kind of file and returns plain dictionaries (never a table). They
all live in the same `.MEM` folder the user selects (except CMAP, which is separate PDF/DOCX files).

| Parser | Reads | Pulls out |
|---|---|---|
| `mem_parser.py` | TMS cortical `.MEM` | Demographics, RMT, T-SICI/T-SICF/A-SICI/A-SICF, TMS coil, and the SR max scalar. **Also defines the table schema** (`output_column_order`). |
| `CSP_parser.py` | CSP `.MEM` | Cortical silent-period start/end/duration at each %RMT level. |
| `sr_parser.py` | Stimulus-Response `.MEM` | The peripheral recruitment curve + `Max CMAP 1 ms` reference amplitude. |
| `cmap_parser.py` | Nerve-conduction **PDF/DOCX** | CMAP and MUNIX tables, stored as JSON text in the table. |

> **Note on "CMAP":** there are two unrelated things that use the word. `cmap_parser.py` reads
> **motor nerve-conduction** studies from PDF/Word files into `CMAP_table`. The **Stimulus-Response**
> graph's y-axis is *also* labelled "CMAP size (mV)" but comes from the peripheral `.MEM` recruitment
> curve — a different measurement handled by `sr_parser.py`. They are kept under distinct names.

### 5.2 Building the table (`processing/df_builder.py`)

This is the assembler. It takes the parser dicts and:
- normalizes them into the fixed column schema and correct data types,
- **merges** CSP and CMAP data onto the matching visit rows (by participant ID + date),
- **coalesces** multiple same-day files into one row,
- supports **incremental** rebuilds: load a saved archive CSV, detect new/removed files, and only
  re-parse what changed.

### 5.3 Drawing graphs (`processing/visualizer.py` → `_v1_visualization.py`)

`visualizer.py` is a thin façade that re-exports the real plotting engine, `_v1_visualization.py`
(a large matplotlib module). The engine draws a wide range of graphs: per-participant profiles,
over-time trends, and cohort comparisons (participant vs healthy controls vs ALS) for each measure
family (T-SICI, T-SICF, A-SICI, A-SICF, CSP, RMT), plus the participant-only Stimulus-Response
scatter and simple table figures (visit summary, CMAP, MUNIX).

The catalogue of what the user can pick is the **`GRAPH_REGISTRY`** list in
`gui/visualization_panel.py`. Each entry maps a checkbox to a graph type; the controller turns a
selection into a figure via `plot_mem_graph`.

### 5.4 Assembling the PDF (`reports/`)

- `report_builder.py` decides which figure belongs to which report "section" and attaches a
  short caption (from `captions.py`) with the raw numbers under each figure.
- `pdf_layout.py` defines a `ReportItem` (figure + caption + section) and lays items out **four per
  page** in a 2×2 grid, with the **institutional letterhead** (two PNGs from `icons/`) on page 1.
- `pdf_renderer.py` stitches the pages into the final multi-page PDF using matplotlib's `PdfPages`.

> **Two ways a report gets built (worth knowing):** the interactive **GUI** builds figures as you
> preview them on the Visualization page and reuses those exact figures for the PDF. A separate
> **scripted** path (`generate_participant_report` → `build_report_figures`) can build a report from
> the DataFrame alone, for headless use and tests. They should be kept in sync.

### 5.5 REDCap export (`processing/redcap_mapper.py` + `reports/redcap_exporter.py`)

REDCap is the lab's online database. Its field names, codes, and dates differ from the app's
internal ones, so:
- `redcap_mapper.py` **translates** the internal table into REDCap's naming (e.g. `RMT50` → `rmt50`,
  coil string → a numeric code, dates → ISO format).
- `redcap_exporter.py` is the **diff engine**: it compares the app's values against the current
  REDCap export and writes an import file containing **only the cells that changed or were missing** —
  so it never clobbers edits already in REDCap. It also flips the right "form completed" flags and
  can produce a colour-coded Excel change report for review.

### 5.6 Email (`emailing/`) and Backup/Sync (`back_up_sync/`)

- **Email:** `smtp_sender.py` sends the PDF as an attachment over the user's organizational SMTP
  server (SSL or STARTTLS). `credentials.py` stores the password securely in the OS keyring
  (Windows Credential Manager) so it is never written to disk in plain text.
- **Sync:** `file_sync.py` is a robocopy-style one-way mirror. It copies only new/updated files
  (never touches the source), retries on failure, can be cancelled mid-run, and writes a timestamped
  log. Used to back up raw data to a network/second location.

---

## 6. The user's journey (the GUI wizard)

The app opens on a **Welcome** page offering two modes:
- **Quick Start** — run the whole workflow automatically using previously saved defaults.
- **Custom Workflow** — step through the pages one at a time.

The ordered pages (Next/Back moves between them):

| # | Page | What the user does |
|---|---|---|
| 0 | Welcome | Choose Quick Start or Custom Workflow |
| 1 | Import Settings | Pick MEM / CSP / CMAP folders and an optional archive CSV |
| 2 | Data Mode | Load the archive as-is (fast), archive + merge new files, or fully re-parse |
| 3 | Exclude *(skippable)* | Drop specific tests for specific participants from the group averages |
| 4 | Participant | Choose the participant ID and visit date (and cortex side) |
| 5 | Visualization | Tick which graphs to include and preview them |
| 6 | Export | Save the table to CSV and/or the report to PDF |
| 7 | Email *(skippable)* | Email the PDF to recipients |
| 8 | REDCap *(skippable)* | Generate the REDCap import file |
| 9 | Backup & Sync *(skippable)* | Copy files to a backup location |
| 10 | Finish | Start over with the same data, or close |

Plus a **Settings** page (from the toolbar) showing the saved defaults read-only.

**Toolbar helpers:**
- **Page-jump dropdown** — jump straight to any page (running any required steps in between).
- **Complete All** — run every remaining step automatically from here to Finish.
- **Dark Mode** toggle and **Settings** button.

**Skipping pages:** the four optional pages carry a "Skip this page in future runs" button
(`skip_control.py`). The choice is remembered, and the Next/Back logic (`nav.py`) simply steps over
any skipped page — while the page-jump dropdown can still reach it. This keeps `nav.py` a tiny, pure,
easily-tested function with no GUI code in it.

**The automation engine:** both Quick Start and Complete All are implemented by one method,
`AppController.run_default_phases(from, to)`, which executes phases 1→9 in order using saved
defaults (load data → select most recent participant → generate all available figures → export →
email → REDCap → sync) and returns a summary shown in a pop-up.

---

## 7. Settings & persistence

User choices (folder paths, export paths, email/REDCap settings, sync pairs, per-participant
exclusions, skipped pages) are saved as a small **JSON file** and reloaded next launch, so the app
remembers a user's setup. This is handled by `core/user_settings.py`, which uses **atomic writes**
(write to a temp file, then rename) so a crash mid-save can never corrupt the settings. In a packaged
build the file lives in a per-user location (`%APPDATA%\SNBR_TMS_App\` on Windows); in development it
sits next to the source. Email passwords are the exception — they go in the OS keyring, not the JSON.

---

## 8. Packaging & deployment

The app ships as a single Windows executable built with **PyInstaller** (`--onefile --windowed`, see
`SNBR_TMS_App.spec` and `build.bat`) — one `SNBR_TMS_App.exe` with no installer and no terminal
window. A macOS `.app` build lives under `macos_build/`. Because a packaged app runs from a
temporary extracted folder, `core/config.py` and `reports/pdf_layout.py` detect the frozen state
(`sys.frozen` / `sys._MEIPASS`) and resolve paths accordingly. Everything works offline; only the
email step reaches the network.

**Dependencies** (see `requirements.txt`): CustomTkinter + tkcalendar (GUI), pandas + numpy (data),
matplotlib (graphs and PDF), openpyxl (Excel reports), pdfplumber + python-docx (reading CMAP
PDFs/Word docs), keyring (password storage), pyinstaller (packaging).

---

## 9. Testing

Unit tests live in `tests/` and are run with the project virtualenv:

```
SNBR_TMS_App/.venv312/Scripts/python.exe -m pytest tests/ -q
```

Most suites are **hermetic** (self-contained, e.g. `test_sr_parser.py`, `test_df_incremental.py`,
`test_file_sync.py`, `test_exclusions.py`). A few need real lab data or extra libraries:
`test_df.py` / `test_report.py` are integration scripts pointing at real data folders, and
`test_cmap_parser.py` needs `pdfplumber`/`python-docx` plus sample files on the lab `Y:` share.

---

## 10. Gotchas & legacy notes

- **`processing/_v1_*` files are legacy but not dead.** The current parsers are in `parser/`. However
  the older `_v1_parse_*` modules are still imported and partly executed by the active plotting engine
  (`_v1_visualization.py`) at render time, so they cannot be deleted without refactoring the visualizer
  first.
- **The Stimulus-Response curve is deliberately not stored in the table** — only the `SR_max_cmap_1ms`
  scalar is. The scatter plot re-reads the full curve from the source `.MEM` when you view it, keeping
  the exported CSV clean.
- **Two REDCap tools exist.** `reports/redcap_exporter.py` is the real engine the app uses.
  `scripts/generate_redcap_import.py` is an older stand-alone CLI that reimplements the same idea and
  does **not** call the engine — treat it as legacy.
- **Adding a graph to the GUI does not automatically add it to the scripted report path** (see §5.4).

---

## 11. Where to make common changes

| I want to… | Start here |
|---|---|
| Add a new measurement parsed from `.MEM` | `parser/mem_parser.py` (add to `output_column_order()` + the record), then `processing/df_builder.py` if it needs merging |
| Add a new graph | `gui/visualization_panel.py` (`GRAPH_REGISTRY`), a builder in `processing/_v1_visualization.py` or `reports/report_builder.py`, and a caption in `reports/captions.py` |
| Change the report layout / cover page | `reports/pdf_layout.py` (grid + letterhead) and `reports/pdf_renderer.py` |
| Add or reorder a wizard page | `gui/app.py` (page wiring + `_page_order`), a new panel in `gui/`, and `AppController.PAGE_NAMES` |
| Add a new saved setting | `core/user_settings.py` (a `KEY_*` constant + `load_defaults`) and the relevant panel/controller methods |
| Wire a screen to backend logic | Add a method to `gui/controller.py`; call it from the panel |

---

*Last reviewed against the codebase as part of the Stimulus-Response module addition. For the
machine-facing coding rules and constraints, see [`CLAUDE.md`](../CLAUDE.md) in the workspace root;
for a GUI quick-start, see [`gui/README.md`](gui/README.md).*
