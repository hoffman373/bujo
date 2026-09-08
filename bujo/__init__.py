"""bujo -- a bullet journal domain specific language and compiler.

    >>> from bujo import parse, emit
    >>> doc = parse("day 2026-09-05:\\n  . Write it down\\n")
    >>> print(emit(doc, "markdown"), end="")
    ## 2026-09-05 · Saturday
    <BLANKLINE>
    - [ ] Write it down
"""

from __future__ import annotations

from .emit import EMITTERS, EXTENSIONS, emit
from .errors import BujoError, Diagnostic
from .model import Document, Entry, Kind, Signifier, State
from .parser import parse

__version__ = "0.1.0"

__all__ = [
    "BujoError",
    "Diagnostic",
    "Document",
    "EMITTERS",
    "EXTENSIONS",
    "Entry",
    "Kind",
    "Signifier",
    "State",
    "__version__",
    "emit",
    "parse",
]
