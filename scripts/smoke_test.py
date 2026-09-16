"""Launch the Tkinter application briefly to verify it can initialize."""

from __future__ import annotations

from restaurant_pos.app import RestaurantPOSApp


def main() -> None:
    """Create the application, process one event cycle, and close it."""
    app = RestaurantPOSApp()
    try:
        app.update_idletasks()
        app.update()
    finally:
        app.destroy()


if __name__ == "__main__":
    main()
