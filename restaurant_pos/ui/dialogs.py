"""Centralized dialog and message-box helpers for the POS UI.

Every widget that needs to show an error, ask for confirmation, or prompt
for a value goes through a single :class:`DialogService` instance instead
of calling ``tkinter.messagebox``/``simpledialog`` directly. That keeps the
wording and behavior (for example, always confirming destructive actions)
consistent across the whole application and gives tests one place to
monkeypatch.
"""

from __future__ import annotations

from tkinter import filedialog, messagebox, simpledialog


class DialogService:
    """Wrap Tkinter dialogs behind one consistent, easily-testable interface."""

    def info(self, title: str, message: str) -> None:
        """Show an informational message box."""
        messagebox.showinfo(title, message)

    def error(self, title: str, message: str) -> None:
        """Show an error message box."""
        messagebox.showerror(title, message)

    def confirm(self, title: str, message: str) -> bool:
        """Ask the user to confirm a destructive or hard-to-reverse action."""
        return bool(messagebox.askyesno(title, message, icon="warning"))

    def ask_string(self, title: str, prompt: str) -> str | None:
        """Prompt for a short line of text, returning ``None`` if cancelled."""
        return simpledialog.askstring(title, prompt)

    def ask_float(
        self, title: str, prompt: str, *, minvalue: float | None = None,
        initialvalue: float | None = None,
    ) -> float | None:
        """Prompt for a floating point value, returning ``None`` if cancelled."""
        return simpledialog.askfloat(
            title, prompt, minvalue=minvalue, initialvalue=initialvalue)

    def ask_int(
        self, title: str, prompt: str, *, minvalue: int | None = None,
    ) -> int | None:
        """Prompt for an integer value, returning ``None`` if cancelled."""
        return simpledialog.askinteger(title, prompt, minvalue=minvalue)

    def ask_save_path(self, default_extension: str) -> str | None:
        """Prompt for a destination file path, returning ``None`` if cancelled."""
        path = filedialog.asksaveasfilename(defaultextension=default_extension)
        return path or None
