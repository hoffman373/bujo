"""JSON backend -- the parsed AST, for tooling and tests."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from enum import Enum

from ..model import Collection, Document, Entry, Group


def emit(doc: Document, *, indent: int = 2, **_ignored) -> str:
    payload = {
        "meta": doc.meta,
        "collections": [_collection(c) for c in doc.collections],
    }
    return json.dumps(payload, indent=indent, ensure_ascii=False) + "\n"


def _collection(collection: Collection) -> dict:
    data = {
        "type": type(collection).__name__,
        "title": collection.title,
        "slug": collection.slug,
        "line": collection.line,
        "items": [_item(i) for i in collection.items],
    }
    for key in ("date", "year", "month", "heading", "name", "start", "end"):
        if hasattr(collection, key):
            data[key] = _plain(getattr(collection, key))
    return data


def _item(item) -> dict:
    if isinstance(item, Group):
        return {
            "type": "Group",
            "title": item.title,
            "line": item.line,
            "entries": [_item(e) for e in item.entries],
        }
    return _entry(item)


def _entry(entry: Entry) -> dict:
    return {
        "type": "Entry",
        "kind": entry.kind.value,
        "state": entry.state.value if entry.state else None,
        "signifiers": [s.value for s in entry.signifiers],
        "time": entry.time,
        "target": entry.target,
        "text": entry.text,
        "spans": [_plain(s) for s in entry.spans],
        "line": entry.line,
        "children": [_entry(c) for c in entry.children],
    }


def _plain(value):
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {"type": type(value).__name__, **asdict(value)}
    if isinstance(value, tuple):
        return list(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value
