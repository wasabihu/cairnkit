"""Split text into chunks along its structure: Markdown headings, then paragraphs, then
sentences, never in the middle of a word unless a sentence is longer than the limit."""

from __future__ import annotations

import re

from cairnkit.knowledge.model import Chunk

MAX_CHARS = 1_500
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_SENTENCE_END = re.compile(r"(?<=[.!?。！？；;])\s*")


def chunk_text(text: str, *, max_chars: int = MAX_CHARS) -> list[tuple[str, str]]:
    """``(heading_path, text)`` pieces. A text within the limit stays one piece."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [("", text)]
    pieces: list[tuple[str, str]] = []
    for path, body in _sections(text):
        for part in _pack(_paragraphs(body), max_chars):
            pieces.append((path, part))
    return pieces


def make_chunks(document_id: str, text: str, *, max_chars: int = MAX_CHARS) -> list[Chunk]:
    return [
        Chunk(id=f"{document_id}#{i}", document_id=document_id, ordinal=i, heading_path=p, text=t)
        for i, (p, t) in enumerate(chunk_text(text, max_chars=max_chars))
    ]


def _sections(text: str) -> list[tuple[str, str]]:
    stack: list[tuple[int, str]] = []
    sections: list[tuple[str, str]] = []
    lines: list[str] = []

    def flush() -> None:
        body = "\n".join(lines).strip()
        if body:
            sections.append((" > ".join(title for _, title in stack), body))
        lines.clear()

    for line in text.splitlines():
        found = _HEADING.match(line)
        if found:
            flush()
            level = len(found.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, found.group(2).strip()))
        else:
            lines.append(line)
    flush()
    return sections


def _paragraphs(body: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]


def _pack(paragraphs: list[str], max_chars: int) -> list[str]:
    """Join paragraphs up to the limit; split a paragraph that is too long by sentences."""
    units: list[str] = []
    for paragraph in paragraphs:
        units.extend([paragraph] if len(paragraph) <= max_chars else _split(paragraph, max_chars))
    out: list[str] = []
    current = ""
    for unit in units:
        joined = f"{current}\n\n{unit}" if current else unit
        if len(joined) <= max_chars:
            current = joined
        else:
            out.append(current)
            current = unit
    if current:
        out.append(current)
    return out


def _split(paragraph: str, max_chars: int) -> list[str]:
    out: list[str] = []
    current = ""
    for sentence in (s for s in _SENTENCE_END.split(paragraph) if s):
        while len(sentence) > max_chars:  # one sentence over the limit: cut it
            out.extend([current] if current else [])
            current = ""
            out.append(sentence[:max_chars])
            sentence = sentence[max_chars:]
        sep = "" if not current or _is_cjk(current[-1]) else " "
        joined = f"{current}{sep}{sentence}" if current else sentence
        if len(joined) <= max_chars:
            current = joined
        else:
            out.append(current)
            current = sentence
    if current:
        out.append(current)
    return out


def _is_cjk(char: str) -> bool:
    return bool(re.match(r"[　-鿿가-힯＀-￯]", char))
