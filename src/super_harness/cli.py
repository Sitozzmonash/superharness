"""Command-line entry point for early project diagnostics."""

from __future__ import annotations

from super_harness import __version__


def main() -> None:
    """Print the installed Super Harness version.

    The full diagnostics and ecosystem CLI is delivered in Phase 12.
    """
    print(f"super-harness {__version__}")
