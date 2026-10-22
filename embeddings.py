"""
Text embeddings through the Gemini API.

An embedding turns a piece of text into a list of numbers so that texts with
similar meaning end up close together. That closeness is what pgvector
searches on.

Vectors are shortened to 768 numbers and normalised to length 1. Shortening
keeps storage small, and normalising is required for accurate similarity at
reduced sizes.
"""

import math
import os
import time

from google.genai import errors, types

from gemini import get_client

EMBED_MODEL = os.environ.get("EMBED_MODEL", "gemini-embedding-001")
DIMENSIONS = 768
BATCH_SIZE = 50
MAX_ATTEMPTS = 4


class EmbeddingError(RuntimeError):
    """Raised with a message that is safe and useful to show the user."""


def _normalize(vector: list[float]) -> list[float]:
    length = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / length for x in vector]


def list_embedding_models(client=None) -> list[str]:
    """Names of models on this key that look like embedding models."""
    client = client or get_client()
    names = []
    for m in client.models.list():
        actions = getattr(m, "supported_actions", None) or []
        if "embedContent" in actions or "embed" in m.name.lower():
            names.append(m.name.replace("models/", ""))
    return names


def _embed_batch(client, batch: list[str], task_type: str) -> list[list[float]]:
    for attempt in range(MAX_ATTEMPTS):
        try:
            result = client.models.embed_content(
                model=EMBED_MODEL,
                contents=batch,
                config=types.EmbedContentConfig(
                    task_type=task_type,
                    output_dimensionality=DIMENSIONS,
                ),
            )
            return [_normalize(list(e.values)) for e in result.embeddings]
        except errors.APIError as e:
            last_attempt = attempt == MAX_ATTEMPTS - 1
            if e.code == 404:
                try:
                    found = ", ".join(list_embedding_models(client)) or "none found"
                except Exception:
                    found = "could not list models"
                raise EmbeddingError(
                    f"Embedding model '{EMBED_MODEL}' was not found for your key. "
                    f"Models that look like embedding models: {found}. "
                    f"Set the EMBED_MODEL environment variable to one of them."
                ) from e
            if e.code == 429 and not last_attempt:
                time.sleep(10 * (attempt + 1))  # per-minute limit: wait it out
                continue
            if e.code in (500, 503, 504) and not last_attempt:
                time.sleep(2 * (attempt + 1))
                continue
            raise EmbeddingError(f"Embedding request failed: {e}") from e
    raise EmbeddingError("Embedding request failed after several attempts.")


def embed(
    texts: list[str],
    task_type: str = "RETRIEVAL_DOCUMENT",
    client=None,
) -> list[list[float]]:
    """
    Embed a list of texts. Use RETRIEVAL_DOCUMENT for stored passages and
    RETRIEVAL_QUERY for the user's question: the model is trained to match
    the two kinds against each other.
    """
    client = client or get_client()
    vectors: list[list[float]] = []
    for i in range(0, len(texts), BATCH_SIZE):
        vectors.extend(_embed_batch(client, texts[i:i + BATCH_SIZE], task_type))
    return vectors
