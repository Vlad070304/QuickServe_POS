"""Presentation configuration for the QuickServe POS desktop UI.

Keeping colors, fonts, and thresholds in one dataclass means a theme or a
business rule (like when to warn about low stock) can change in a single
place instead of being scattered across widget construction code.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AppSettings:
    """Immutable configuration for window chrome, theming, and behavior."""

    title: str = "QuickServe POS"
    geometry: str = "1040x660"
    ttk_theme: str = "clam"

    colors: dict = field(default_factory=lambda: {
        "background": "#f4f7fb",
        "surface": "#ffffff",
        "primary": "#cfe8ff",
        "primary_text": "#143050",
        "text": "#183153",
        "muted": "#314f74",
        "success": "#d9f7e8",
        "success_text": "#113b2d",
        "danger": "#fbe8e8",
        "danger_text": "#5d2323",
        "warning": "#fff2cc",
        "warning_text": "#6b5100",
    })

    fonts: dict = field(default_factory=lambda: {
        "heading": ("Segoe UI", 18, "bold"),
        "subheading": ("Segoe UI", 11, "bold"),
        "body": ("Segoe UI", 11),
        "small": ("Segoe UI", 10),
        "button": ("Segoe UI", 10, "bold"),
    })

    # Business/display thresholds. Centralized so support staff can be told
    # a single number to look for instead of hunting through widget code.
    low_stock_threshold: int = 5
    default_tax_rate: float = 0.08
    default_discount_percentage: float = 10
    default_backup_interval_seconds: float = 300

    def color(self, name: str) -> str:
        """Return a themed color, raising a clear error for unknown keys."""
        try:
            return self.colors[name]
        except KeyError as exc:
            raise KeyError(f"Unknown color token: {name}") from exc

    def font(self, name: str) -> tuple:
        """Return a themed font tuple, raising a clear error for unknown keys."""
        try:
            return self.fonts[name]
        except KeyError as exc:
            raise KeyError(f"Unknown font token: {name}") from exc
