"""Output backends."""

from __future__ import annotations

from ..model import Document
from . import jsonout, latex, markdown

EMITTERS = {
    "latex": latex.emit,
    "markdown": markdown.emit,
    "json": jsonout.emit,
}

#: Conventional file extension per format.
EXTENSIONS = {"latex": ".tex", "markdown": ".md", "json": ".json"}


def emit(doc: Document, fmt: str, **options) -> str:
    try:
        backend = EMITTERS[fmt]
    except KeyError:
        raise ValueError(f"unknown format {fmt!r}; choose from {', '.join(EMITTERS)}") from None
    return backend(doc, **options)
