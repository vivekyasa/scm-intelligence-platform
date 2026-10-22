"""Tests for chunking, embeddings and retrieval. Offline, with fakes."""

import math
from pathlib import Path
from types import SimpleNamespace

import pytest
from google.genai import errors

import embeddings
import retrieval
from chunking import split_markdown

DOCS = Path(__file__).parent / "docs" / "policies"

SAMPLE = """# Sample Policy

Document owner: Someone. Applies to everyone.

## First section

Alpha beta gamma.

## Second section

Delta epsilon.

- point one
- point two
"""


# ------------------------------------------------------------------ chunking

def test_chunks_follow_sections():
    chunks = split_markdown(SAMPLE, "sample.md")
    assert [c["section"] for c in chunks] == ["Scope", "First section", "Second section"]
    assert [c["chunk_index"] for c in chunks] == [0, 1, 2]
    assert all(c["doc_title"] == "Sample Policy" for c in chunks)
    assert all(c["content"].startswith("Sample Policy > ") for c in chunks)
    assert "point two" in chunks[2]["content"]


def test_long_section_is_split_on_paragraphs():
    body = "\n\n".join(f"Paragraph number {i} " + "word " * 40 for i in range(10))
    chunks = split_markdown(f"# T\n\n## Big\n\n{body}", "t.md", max_chars=500)
    assert len(chunks) > 1
    assert all(len(c["content"]) < 900 for c in chunks)
    assert [c["chunk_index"] for c in chunks] == list(range(len(chunks)))


def test_empty_sections_are_skipped():
    chunks = split_markdown("# T\n\n## Empty\n\n## Full\n\ntext", "t.md")
    assert [c["section"] for c in chunks] == ["Full"]


def test_real_documents_chunk_sensibly():
    files = sorted(DOCS.glob("*.md"))
    assert len(files) == 8
    total = 0
    for f in files:
        chunks = split_markdown(f.read_text(encoding="utf-8"), f.name)
        assert len(chunks) >= 3, f.name
        assert all(len(c["content"]) <= 1500 for c in chunks), f.name
        assert all(c["doc_title"].endswith(("Policy",)) for c in chunks), f.name
        total += len(chunks)
    assert 30 <= total <= 80


# ---------------------------------------------------------------- embeddings

class FakeEmbedClient:
    def __init__(self, script=None, dims=4):
        self.script = list(script or [])
        self.dims = dims
        self.batches = []
        self.models = self

    def embed_content(self, model, contents, config):
        self.batches.append(list(contents))
        if self.script:
            item = self.script.pop(0)
            if isinstance(item, Exception):
                raise item
        vectors = [SimpleNamespace(values=[3.0, 4.0] + [0.0] * (self.dims - 2))
                   for _ in contents]
        return SimpleNamespace(embeddings=vectors)

    def list(self):
        return [
            SimpleNamespace(name="models/gemini-2.5-flash", supported_actions=["generateContent"]),
            SimpleNamespace(name="models/gemini-embedding-9", supported_actions=["embedContent"]),
        ]


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(embeddings.time, "sleep", lambda s: None)


def test_vectors_are_normalised_to_unit_length():
    out = embeddings.embed(["a", "b"], client=FakeEmbedClient())
    assert len(out) == 2
    for v in out:
        assert math.isclose(math.sqrt(sum(x * x for x in v)), 1.0)
    assert math.isclose(out[0][0], 0.6) and math.isclose(out[0][1], 0.8)


def test_large_inputs_are_batched(monkeypatch):
    monkeypatch.setattr(embeddings, "BATCH_SIZE", 3)
    client = FakeEmbedClient()
    out = embeddings.embed([str(i) for i in range(7)], client=client)
    assert len(out) == 7
    assert [len(b) for b in client.batches] == [3, 3, 1]


def test_rate_limit_is_retried():
    limited = errors.ClientError(429, {"error": {"message": "slow down", "status": "RESOURCE_EXHAUSTED"}}, None)
    client = FakeEmbedClient(script=[limited, limited])
    out = embeddings.embed(["a"], client=client)
    assert len(out) == 1
    assert len(client.batches) == 3


def test_missing_model_gives_a_helpful_error():
    missing = errors.ClientError(404, {"error": {"message": "not found", "status": "NOT_FOUND"}}, None)
    client = FakeEmbedClient(script=[missing])
    with pytest.raises(embeddings.EmbeddingError) as exc:
        embeddings.embed(["a"], client=client)
    message = str(exc.value)
    assert "gemini-embedding-9" in message
    assert "EMBED_MODEL" in message


def test_persistent_failure_raises_embedding_error():
    busy = errors.ServerError(503, {"error": {"message": "busy", "status": "UNAVAILABLE"}}, None)
    client = FakeEmbedClient(script=[busy] * embeddings.MAX_ATTEMPTS)
    with pytest.raises(embeddings.EmbeddingError):
        embeddings.embed(["a"], client=client)


# ----------------------------------------------------------------- retrieval

def test_vector_literal_format():
    assert retrieval.vector_literal([0.5, -0.25, 1.0]) == "[0.500000,-0.250000,1.000000]"


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.executed = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params):
        self.executed = (sql, params)

    def fetchall(self):
        return self.rows


class FakeConn:
    def __init__(self, rows):
        self.cursor_obj = FakeCursor(rows)
        self.closed = False

    def cursor(self, cursor_factory=None):
        return self.cursor_obj

    def close(self):
        self.closed = True


def test_search_documents_builds_query_and_shapes_results(monkeypatch):
    monkeypatch.setenv("DATABASE_URL_RO", "postgresql://fake")
    monkeypatch.setattr(retrieval, "embed", lambda texts, task_type: [[1.0, 0.0]])
    rows = [{"doc_name": "a.md", "doc_title": "A Policy", "section": "S",
             "content": "text", "score": 0.912345}]
    conn = FakeConn(rows)
    monkeypatch.setattr(retrieval.psycopg2, "connect", lambda url, connect_timeout: conn)

    out = retrieval.search_documents("what is the rule?", k=3)

    sql, params = conn.cursor_obj.executed
    assert "<=>" in sql and "ORDER BY" in sql and "LIMIT" in sql
    assert params == ("[1.000000,0.000000]", "[1.000000,0.000000]", 3)
    assert out == [{"doc_name": "a.md", "doc_title": "A Policy", "section": "S",
                    "content": "text", "score": 0.9123}]
    assert conn.closed


def test_search_requires_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL_RO", raising=False)
    with pytest.raises(RuntimeError):
        retrieval.search_documents("anything")


def test_query_embedding_uses_the_query_task_type(monkeypatch):
    monkeypatch.setenv("DATABASE_URL_RO", "postgresql://fake")
    seen = {}

    def fake_embed(texts, task_type):
        seen["task_type"] = task_type
        return [[1.0, 0.0]]

    monkeypatch.setattr(retrieval, "embed", fake_embed)
    monkeypatch.setattr(retrieval.psycopg2, "connect", lambda url, connect_timeout: FakeConn([]))
    retrieval.search_documents("q")
    assert seen["task_type"] == "RETRIEVAL_QUERY"
