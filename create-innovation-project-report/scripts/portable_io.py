"""Consistent UTF-8 output for CLI tools across terminals and redirected pipes."""

from __future__ import annotations

import sys


def configure_utf8() -> None:
    """Configure real text streams; leave embedding hosts' custom streams untouched."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")
