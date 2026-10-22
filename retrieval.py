"""Search the policy documents by meaning, using pgvector."""

import os
from contextlib import closing
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor

from embeddings import embed

DEFAULT_K = 4


def vector_literal(vector: list[float]) -> str:
    """pgvector reads vectors written as '[0.1,0.2,...]'."""
    return "[" + ",".join(f"{x:.6f}" for x in vector) + "]"


def search_documents(query: str, k: int = DEFAULT_K) -> list[dict[str, Any]]:
    """
    Return the k passages closest in meaning to the query.

    score is cosine similarity: closer to 1 means a closer match.
    The <=> operator is cosine distance, so similarity is 1 minus distance.
    """
    url = os.environ.get("DATABASE_URL_RO")
    if not url:
        raise RuntimeError("DATABASE_URL_RO is not set")

    query_vector = vector_literal(embed([query], task_type="RETRIEVAL_QUERY")[0])

    sql = """
        SELECT doc_name, doc_title, section, content,
               1 - (embedding <=> %s::vector) AS score
        FROM policy_chunks
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """
    with closing(psycopg2.connect(url, connect_timeout=10)) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, (query_vector, query_vector, k))
            rows = cur.fetchall()

    return [
        {
            "doc_name": r["doc_name"],
            "doc_title": r["doc_title"],
            "section": r["section"],
            "content": r["content"],
            "score": round(float(r["score"]), 4),
        }
        for r in rows
    ]
