"""
Split a markdown policy document into chunks for retrieval.

Strategy: one chunk per section (## heading). A section that is longer than
max_chars is split on paragraph boundaries. Every chunk starts with
"Document title > Section" so that the text carries its own context. Without
that line, a passage that says "Class A items: 2.5 weeks" would not mention
that it comes from the safety stock policy.
"""

import re


def _split_long(body: str, max_chars: int) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    pieces, current = [], ""
    for para in paragraphs:
        candidate = f"{current}\n\n{para}" if current else para
        if current and len(candidate) > max_chars:
            pieces.append(current)
            current = para
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces


def split_markdown(text: str, doc_name: str, max_chars: int = 1200) -> list[dict]:
    title = doc_name
    section = "Scope"
    buffer: list[str] = []
    sections: list[tuple[str, str]] = []

    def flush():
        body = "\n".join(buffer).strip()
        if body:
            sections.append((section, body))

    for line in text.splitlines():
        if line.startswith("# ") and not line.startswith("## "):
            title = line[2:].strip()
        elif line.startswith("## "):
            flush()
            buffer = []
            section = line[3:].strip()
        else:
            buffer.append(line)
    flush()

    chunks = []
    for sec, body in sections:
        for piece in _split_long(body, max_chars):
            chunks.append({
                "doc_name": doc_name,
                "doc_title": title,
                "section": sec,
                "chunk_index": len(chunks),
                "content": f"{title} > {sec}\n\n{piece}",
            })
    return chunks
