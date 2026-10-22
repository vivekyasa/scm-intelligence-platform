"""
Load the policy documents into the database for search.

Reads docs/policies/*.md, splits them into chunks, embeds every chunk with
Gemini, and stores text plus vector in the policy_chunks table.
Safe to run again: it clears the table and reloads it.

Needs DATABASE_URL (the owner connection, because it creates a table) and
GEMINI_API_KEY.

Usage:
    py ingest_docs.py
"""

import os
import sys
from contextlib import closing
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

from chunking import split_markdown
from embeddings import DIMENSIONS, EMBED_MODEL, EmbeddingError, embed
from retrieval import vector_literal

ROOT = Path(__file__).parent
DOCS = ROOT / "docs" / "policies"
SCHEMA = ROOT / "sql" / "03_policy_chunks.sql"


def main():
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is not set (this script needs the owner connection).")

    files = sorted(DOCS.glob("*.md"))
    if not files:
        sys.exit(f"No documents found in {DOCS}")

    chunks = []
    for f in files:
        chunks.extend(split_markdown(f.read_text(encoding="utf-8"), f.name))
    print(f"{len(files)} documents -> {len(chunks)} chunks")

    print(f"Embedding with {EMBED_MODEL} ({DIMENSIONS} dimensions)...")
    try:
        vectors = embed([c["content"] for c in chunks], task_type="RETRIEVAL_DOCUMENT")
    except EmbeddingError as e:
        sys.exit(f"\n{e}")
    print(f"Got {len(vectors)} vectors")

    rows = [
        (c["doc_name"], c["doc_title"], c["section"], c["chunk_index"],
         c["content"], vector_literal(v))
        for c, v in zip(chunks, vectors)
    ]

    with closing(psycopg2.connect(url)) as conn:
        with conn, conn.cursor() as cur:
            cur.execute(SCHEMA.read_text(encoding="utf-8"))
            cur.execute("TRUNCATE policy_chunks RESTART IDENTITY")
            execute_values(
                cur,
                "INSERT INTO policy_chunks "
                "(doc_name, doc_title, section, chunk_index, content, embedding) "
                "VALUES %s",
                rows,
                template="(%s, %s, %s, %s, %s, %s::vector)",
            )
            cur.execute("SELECT COUNT(*) FROM policy_chunks")
            stored = cur.fetchone()[0]

    print(f"Stored {stored} chunks in policy_chunks. Done.")


if __name__ == "__main__":
    main()
