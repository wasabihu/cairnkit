"""Turn a PDF, Word, Excel or text file into Markdown for a model to read.

uv sync --extra documents
uv run python examples/read_document.py path/to/file.docx
"""

import sys
from pathlib import Path

from cairnkit.documents import DocumentError, Limits, extract_text


def main(path: str) -> int:
    data = Path(path).read_bytes()
    try:
        doc = extract_text(data, Path(path).name, limits=Limits(max_chars=20_000))
    except DocumentError as exc:
        print(f"cannot read it ({exc.code}): {exc}")
        return 1
    print(f"{doc.kind}, {doc.chars:,} characters, parts={doc.parts}, truncated={doc.truncated}")
    for warning in doc.warnings:
        print("note:", warning)
    print()
    print(doc.text)
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))
