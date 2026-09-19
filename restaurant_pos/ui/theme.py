"""Applies the shared ttk theme and named widget styles for the POS UI.

All widget colors and fonts are defined here, in terms of the tokens in
:class:`~restaurant_pos.ui.settings.AppSettings`, and referenced elsewhere
by style name only (e.g. ``style="Menu.TButton"``). That keeps individual
view components free of hardcoded colors and makes re-theming a one-file
change.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .settings import AppSettings


def apply_theme(root: tk.Tk, settings: AppSettings) -> ttk.Style:
    """Configure the root window and register every named widget style."""
    root.configure(bg=settings.color("background"))
    style = ttk.Style(root)
    if settings.ttk_theme in style.theme_names():
        style.theme_use(settings.ttk_theme)

    surface = settings.color("surface")
    background = settings.color("background")

    style.configure("Surface.TFrame", background=surface)
    style.configure("Background.TFrame", background=background)

    style.configure("Heading.TLabel", background=surface,
                     foreground=settings.color("text"), font=settings.font("heading"))
    style.configure("Body.TLabel", background=surface,
                     foreground=settings.color("text"), font=settings.font("body"))
    style.configure("Small.TLabel", background=surface,
                     foreground=settings.color("muted"), font=settings.font("small"))
    style.configure("Muted.TLabel", background=background,
                     foreground=settings.color("muted"), font=settings.font("small"))
    style.configure("Total.TLabel", background=surface,
                     foreground=settings.color("text"), font=settings.font("subheading"))
    # Kept for backward compatibility with any external code referencing
    # the original single generic label style.
    style.configure("POS.TLabel", background=background,
                     foreground=settings.color("muted"))

    style.configure("Menu.TButton", font=settings.font("button"))
    style.configure("LowStock.Menu.TButton", font=settings.font("button"),
                     foreground=settings.color("warning_text"))
    style.configure("OutOfStock.Menu.TButton", font=settings.font("button"),
                     foreground=settings.color("muted"))

    style.configure("Success.TButton", foreground=settings.color("success_text"))
    style.configure("Danger.TButton", foreground=settings.color("danger_text"))
    style.configure("Primary.TButton", font=settings.font("button"),
                     foreground=settings.color("primary_text"))

    return style
