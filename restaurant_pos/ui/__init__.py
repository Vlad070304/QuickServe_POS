"""Tkinter view components for the QuickServe POS desktop application.

The application window in :mod:`restaurant_pos.app` acts as a thin
controller: it owns the domain objects (menu, order, processor, reports)
and wires them to the view components defined in this package. Each
component is a self-contained ``ttk`` widget that only knows how to render
itself and report user intent through plain callbacks, which keeps
``app.py`` small and keeps the widgets independently testable.
"""

from .settings import AppSettings
from .dialogs import DialogService

__all__ = ["AppSettings", "DialogService"]
