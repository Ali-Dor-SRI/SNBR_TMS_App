"""Page 6 — Email Report: send the freshly-exported PDF to recipients."""

from __future__ import annotations

import threading
from pathlib import Path

import customtkinter as ctk

from gui.theme import (
    FONT_TITLE, FONT_HEADING, FONT_BODY, FONT_SMALL, FONT_SUBTITLE, FONT_BUTTON,
    ACCENT_COLOR, ACCENT_HOVER, ERROR_COLOR, SUCCESS_COLOR, DISABLED_FG, SUBTITLE_COLOR,
    PAD_X, PAD_Y, SECTION_PAD_Y, ENTRY_HEIGHT, BUTTON_HEIGHT, CORNER_RADIUS,
)


def _split_addrs(raw: str) -> list[str]:
    return [a.strip() for a in raw.split(",") if a.strip()]


class EmailPanel(ctk.CTkFrame):
    """Email Report page — fill recipients, send the exported PDF via SMTP."""

    def __init__(self, parent, controller, on_next, on_back, footer=None):
        super().__init__(parent, fg_color="transparent")
        # The pinned bar at the bottom of the window (gui.page_shell.PageShell).
        # Panels grid their Back/Next, action buttons, progress bar and status
        # line into it so those never scroll away with the content. Falling back
        # to a row of its own keeps a panel constructible standalone.
        self._footer = footer
        if self._footer is None:
            self._footer = ctk.CTkFrame(self, fg_color="transparent")
            self._footer.grid(row=99, column=0, sticky="ew")
        self._controller = controller
        self._on_next = on_next
        self._on_back = on_back

        self._sending = False
        self._attachment_var = ctk.StringVar()
        self._remember_var = ctk.BooleanVar(value=False)
        self._status_var = ctk.StringVar()

        self._build_ui()
        self._load_defaults()

    # ── UI ─────────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self, text="Email Report", font=FONT_TITLE, anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=PAD_X, pady=(SECTION_PAD_Y, 4))

        ctk.CTkLabel(
            self,
            text="Send the exported PDF report to recipients via SMTP.",
            font=FONT_SUBTITLE, text_color=SUBTITLE_COLOR, anchor="w",
        ).grid(row=1, column=0, sticky="w", padx=PAD_X, pady=(0, SECTION_PAD_Y))

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=2, column=0, sticky="nsew", padx=PAD_X)
        body.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # SMTP host + port (one row)
        ctk.CTkLabel(body, text="SMTP server", font=FONT_HEADING).grid(
            row=0, column=0, sticky="w", pady=(0, 4),
        )
        smtp_row = ctk.CTkFrame(body, fg_color="transparent")
        smtp_row.grid(row=0, column=1, sticky="ew", pady=(0, 4))
        smtp_row.grid_columnconfigure(0, weight=1)
        self._host_entry = ctk.CTkEntry(
            smtp_row, height=ENTRY_HEIGHT, corner_radius=CORNER_RADIUS,
            font=FONT_BODY, placeholder_text="smtp.gmail.com",
        )
        self._host_entry.grid(row=0, column=0, sticky="ew")
        self._port_entry = ctk.CTkEntry(
            smtp_row, height=ENTRY_HEIGHT, corner_radius=CORNER_RADIUS,
            font=FONT_BODY, width=80, placeholder_text="587",
        )
        self._port_entry.grid(row=0, column=1, padx=(PAD_Y, 0))

        # Username / password
        self._username_entry = self._row(body, "Username", 1)
        self._password_entry = self._row(body, "Password", 2, show="*")

        # Remember password checkbox
        ctk.CTkCheckBox(
            body, text="Remember password on this machine",
            variable=self._remember_var, font=FONT_SMALL,
        ).grid(row=3, column=1, sticky="w", pady=(0, PAD_Y))

        # From / To / Cc / Bcc / Subject
        self._from_entry = self._row(body, "From", 4)
        self._to_entry = self._row(body, "To  (comma-separated)", 5)
        self._cc_entry = self._row(body, "Cc  (comma-separated)", 6)
        self._bcc_entry = self._row(body, "Bcc  (comma-separated)", 7)
        self._subject_entry = self._row(body, "Subject", 8)

        # Body
        ctk.CTkLabel(body, text="Body", font=FONT_HEADING).grid(
            row=9, column=0, sticky="nw", pady=(0, 4),
        )
        self._body_box = ctk.CTkTextbox(
            body, height=110, corner_radius=CORNER_RADIUS, font=FONT_BODY,
        )
        self._body_box.grid(row=9, column=1, sticky="ew", pady=(0, PAD_Y))

        # Attachment — always the PDF produced by the Export page this session.
        ctk.CTkLabel(body, text="Attachment (PDF)", font=FONT_HEADING).grid(
            row=10, column=0, sticky="w", pady=(0, 4),
        )
        self._attachment_entry = ctk.CTkEntry(
            body, height=ENTRY_HEIGHT, corner_radius=CORNER_RADIUS,
            font=FONT_BODY, textvariable=self._attachment_var, state="readonly",
        )
        self._attachment_entry.grid(row=10, column=1, sticky="ew", pady=(0, PAD_Y))

        # Footer note
        self._security_note = ctk.CTkLabel(
            self, text="", font=FONT_SMALL, text_color=DISABLED_FG, anchor="w",
            wraplength=900,
        )
        self._security_note.grid(row=3, column=0, sticky="w", padx=PAD_X, pady=(0, 4))

        # Indeterminate progress bar (hidden until sending)
        self._progress = ctk.CTkProgressBar(
            self._footer, mode="indeterminate", width=400,
        )
        self._progress.grid(row=0, column=0, padx=PAD_X, pady=(PAD_Y, 0))
        self._progress.grid_remove()

        # Status label
        self._status_label = ctk.CTkLabel(
            self._footer, textvariable=self._status_var, font=FONT_SMALL,
            text_color=DISABLED_FG, anchor="w", wraplength=900, justify="left",
        )
        self._status_label.grid(row=1, column=0, sticky="w", padx=PAD_X, pady=(2, 0))

        # Navigation (pinned; see gui.page_shell)
        nav = ctk.CTkFrame(self._footer, fg_color="transparent")
        nav.grid(row=2, column=0, sticky="ew", padx=PAD_X, pady=(PAD_Y, PAD_Y))
        nav.grid_columnconfigure(2, weight=1)

        self._back_btn = ctk.CTkButton(
            nav, text="Back", width=100, height=BUTTON_HEIGHT,
            corner_radius=CORNER_RADIUS, font=FONT_BUTTON,
            fg_color=ACCENT_COLOR, hover_color=ACCENT_HOVER,
            command=self._on_back,
        )
        self._back_btn.grid(row=0, column=0, sticky="w")

        self._save_btn = ctk.CTkButton(
            nav, text="Save Defaults", width=140, height=BUTTON_HEIGHT,
            corner_radius=CORNER_RADIUS, font=FONT_BUTTON,
            fg_color="transparent", border_width=1, border_color=ACCENT_COLOR,
            text_color=ACCENT_COLOR, hover_color=ACCENT_HOVER,
            command=self._on_save_defaults,
        )
        self._save_btn.grid(row=0, column=1, padx=(PAD_Y, 0))

        self._send_btn = ctk.CTkButton(
            nav, text="Send Email", width=130, height=BUTTON_HEIGHT,
            corner_radius=CORNER_RADIUS, font=FONT_BUTTON,
            fg_color=ACCENT_COLOR, hover_color=ACCENT_HOVER,
            command=self._on_send,
        )
        self._send_btn.grid(row=0, column=3)

        self._next_btn = ctk.CTkButton(
            nav, text="Next", width=100, height=BUTTON_HEIGHT,
            corner_radius=CORNER_RADIUS, font=FONT_BUTTON,
            fg_color=ACCENT_COLOR, hover_color=ACCENT_HOVER,
            command=self._on_next,
        )
        self._next_btn.grid(row=0, column=4, padx=(PAD_Y, 0))

    def _row(self, parent, label: str, row: int, *, show: str = "") -> ctk.CTkEntry:
        ctk.CTkLabel(parent, text=label, font=FONT_HEADING).grid(
            row=row, column=0, sticky="w", pady=(0, 4),
        )
        e = ctk.CTkEntry(
            parent, height=ENTRY_HEIGHT, corner_radius=CORNER_RADIUS,
            font=FONT_BODY, show=show,
        )
        e.grid(row=row, column=1, sticky="ew", pady=(0, 4))
        return e

    # ── Defaults ───────────────────────────────────────────

    def _load_defaults(self):
        d = self._controller.get_email_defaults()
        self._host_entry.insert(0, d["smtp_host"] or "smtp.gmail.com")
        self._port_entry.insert(0, d["smtp_port"] or "587")
        self._username_entry.insert(0, d["username"])
        if d["password"]:
            self._password_entry.insert(0, d["password"])
        self._from_entry.insert(0, d["from_addr"])
        self._to_entry.insert(0, d["to"])
        self._cc_entry.insert(0, d["cc"])
        self._bcc_entry.insert(0, d["bcc"])
        self._subject_entry.insert(0, d["subject"] or "SNBR TMS Report")
        self._body_box.delete("1.0", "end")
        self._body_box.insert(
            "1.0",
            d["body"] or
            "Hello,\n\nPlease find attached the SNBR TMS report.\n",
        )
        self._remember_var.set(d["remember_password"])
        self._update_security_note()

    def refresh(self):
        """Called when the page is shown — show what will be attached."""
        existing = self._controller.get_last_exported_pdf() or ""
        if existing and Path(existing).is_file():
            self._attachment_var.set(existing)
        elif self._controller.get_report_figures():
            self._attachment_var.set(
                "Report PDF will be generated automatically when you click Send.",
            )
        else:
            self._attachment_var.set(
                "(no report figures available — visit the Visualization page first)",
            )
        self._update_security_note()

    def _update_security_note(self):
        from emailing.credentials import keyring_backend_name
        if self._remember_var.get():
            self._security_note.configure(
                text=f"Password is stored encrypted in {keyring_backend_name()} "
                     "for the current OS user.",
            )
        else:
            self._security_note.configure(
                text="Password is not saved — you will be asked to enter it each session.",
            )

    # ── Actions ────────────────────────────────────────────

    def _set_status(self, text: str, color: str | None):
        self._status_var.set(text)
        self._status_label.configure(
            text_color=color if color else DISABLED_FG,
        )

    def _collect_form(self) -> dict:
        return {
            "smtp_host": self._host_entry.get().strip(),
            "smtp_port": self._port_entry.get().strip(),
            "username": self._username_entry.get().strip(),
            "password": self._password_entry.get(),
            "from_addr": self._from_entry.get().strip(),
            "to": self._to_entry.get().strip(),
            "cc": self._cc_entry.get().strip(),
            "bcc": self._bcc_entry.get().strip(),
            "subject": self._subject_entry.get().strip(),
            "body": self._body_box.get("1.0", "end").strip(),
            "attachment": self._attachment_var.get().strip(),
            "remember_password": self._remember_var.get(),
        }

    def _on_save_defaults(self):
        f = self._collect_form()
        try:
            self._controller.save_email_defaults(
                smtp_host=f["smtp_host"],
                smtp_port=f["smtp_port"],
                username=f["username"],
                from_addr=f["from_addr"],
                to=f["to"],
                cc=f["cc"],
                bcc=f["bcc"],
                subject=f["subject"],
                body=f["body"],
                remember_password=f["remember_password"],
                password=f["password"] if f["remember_password"] else None,
            )
        except Exception as e:  # noqa: BLE001
            self._set_status(
                f"Save failed — {type(e).__name__}: {e}", ERROR_COLOR,
            )
            return
        self._update_security_note()
        from emailing.credentials import keyring_backend_name
        msg = "Defaults saved."
        if f["remember_password"]:
            msg += f" Password stored in {keyring_backend_name()}."
        self._set_status(msg, SUCCESS_COLOR)

    def _on_send(self):
        if self._sending:
            return
        f = self._collect_form()

        try:
            if not f["smtp_host"]:
                raise ValueError("SMTP host is required.")
            if not f["smtp_port"].isdigit():
                raise ValueError("SMTP port must be an integer.")
            port = int(f["smtp_port"])
            if not f["from_addr"]:
                raise ValueError("From address is required.")
            to_list = _split_addrs(f["to"])
            if not to_list:
                raise ValueError("At least one To address is required.")
        except ValueError as e:
            self._set_status(str(e), ERROR_COLOR)
            return

        cc_list = _split_addrs(f["cc"])
        bcc_list = _split_addrs(f["bcc"])

        self._set_busy(True)
        self._set_status("Preparing PDF report…", None)

        thread = threading.Thread(
            target=self._send_worker,
            args=(
                f["smtp_host"], port, f["username"], f["password"],
                f["from_addr"], to_list, cc_list, bcc_list,
                f["subject"], f["body"],
            ),
            daemon=True,
        )
        thread.start()

    def _send_worker(
        self, host, port, username, password, from_addr,
        to_list, cc_list, bcc_list, subject, body,
    ):
        # Render the report PDF here (off the main thread) so the GUI stays
        # responsive — figure rendering takes a few seconds for full reports.
        try:
            attachment = self._controller.prepare_report_pdf_for_email()
        except Exception as e:  # noqa: BLE001
            err = f"Could not prepare PDF — {type(e).__name__}: {e}"
            self.after(0, self._on_send_done, False, err)
            return
        self.after(0, self._on_prep_done, attachment)

        try:
            self._controller.send_report_email(
                smtp_host=host, smtp_port=port,
                username=username, password=password,
                from_addr=from_addr,
                to_addrs=to_list, cc_addrs=cc_list, bcc_addrs=bcc_list,
                subject=subject, body=body,
                attachment_path=attachment,
            )
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"
            self.after(0, self._on_send_done, False, err)
            return
        self.after(0, self._on_send_done, True, "Sent — check inbox.")

    def _on_prep_done(self, attachment: str):
        """Update UI after the PDF is rendered, before SMTP connects."""
        self._attachment_var.set(attachment)
        self._set_status("Connecting to SMTP server…", None)

    def _on_send_done(self, ok: bool, message: str):
        self._set_busy(False)
        self._set_status(message, SUCCESS_COLOR if ok else ERROR_COLOR)

    def _set_busy(self, busy: bool):
        self._sending = busy
        state = "disabled" if busy else "normal"
        self._send_btn.configure(
            state=state, text="Sending…" if busy else "Send Email",
        )
        self._save_btn.configure(state=state)
        self._back_btn.configure(state=state)
        self._next_btn.configure(state=state)
        if busy:
            self._progress.grid()
            self._progress.start()
        else:
            self._progress.stop()
            self._progress.grid_remove()
