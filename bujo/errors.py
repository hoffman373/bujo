"""Error types for the bullet journal DSL."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Diagnostic:
    """A single problem found in a source file."""

    line: int
    column: int
    message: str
    hint: str = ""
    source_line: str = ""

    def render(self, filename: str = "<input>") -> str:
        out = [f"{filename}:{self.line}:{self.column}: error: {self.message}"]
        if self.source_line:
            out.append(f"  {self.line:>4} | {self.source_line}")
            out.append(f"       | {' ' * max(self.column - 1, 0)}^")
        if self.hint:
            out.append(f"  hint: {self.hint}")
        return "\n".join(out)


class BujoError(Exception):
    """Raised when a source file cannot be compiled."""

    def __init__(self, diagnostics: list[Diagnostic], filename: str = "<input>"):
        self.diagnostics = diagnostics
        self.filename = filename
        super().__init__(self.render())

    def render(self) -> str:
        return "\n\n".join(d.render(self.filename) for d in self.diagnostics)
