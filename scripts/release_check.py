"""Run the checks required before publishing a release."""

from __future__ import annotations

import subprocess
import sys


def run(command: list[str]) -> None:
    """Run one check and stop immediately if it fails."""
    print(f"+ {' '.join(command)}", flush=True)
    subprocess.run(command, check=True)


def main() -> None:
    """Run syntax, lint, typing, coverage, and UI smoke checks."""
    python = sys.executable
    run([python, "-m", "compileall", "-q", "."])
    run([python, "-m", "ruff", "check", "."])
    run([python, "-m", "mypy", "restaurant_pos"])
    run(
        [
            python,
            "-m",
            "pytest",
            "--cov=restaurant_pos",
            "--cov-report=term-missing",
        ]
    )
    run([python, "-m", "scripts.smoke_test"])
    print("Release checks passed.")


if __name__ == "__main__":
    main()
