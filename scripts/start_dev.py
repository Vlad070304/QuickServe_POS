"""Start a local development instance with a persistent, seeded database."""

from __future__ import annotations

import argparse
import os

from restaurant_pos.app import RestaurantPOSApp


def main() -> None:
    """Start the local development application with a seeded database."""
    parser = argparse.ArgumentParser(description="Start QuickServe POS for local development.")
    parser.add_argument("--db", default=os.getenv("QUICKSERVE_DB", "quickserve-dev.db"))
    args = parser.parse_args()
    app = RestaurantPOSApp(args.db)
    try:
        app.mainloop()
    finally:
        app.destroy()


if __name__ == "__main__":
    main()
