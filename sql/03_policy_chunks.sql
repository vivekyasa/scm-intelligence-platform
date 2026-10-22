-- Storage for the RAG side: one row per document chunk, with its embedding.
-- Safe to run more than once.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS policy_chunks (
    chunk_id    SERIAL PRIMARY KEY,
    doc_name    TEXT    NOT NULL,
    doc_title   TEXT    NOT NULL,
    section     TEXT    NOT NULL,
    chunk_index INTEGER NOT NULL,
    content     TEXT    NOT NULL,
    embedding   vector(768) NOT NULL,
    UNIQUE (doc_name, chunk_index)
);

-- Approximate nearest neighbour index, cosine distance. At a few dozen rows an
-- exact scan is just as fast, but this is the index you would need at scale.
CREATE INDEX IF NOT EXISTS idx_policy_chunks_embedding
    ON policy_chunks USING hnsw (embedding vector_cosine_ops);

-- The API connects as the read-only user, so it needs permission to read this
-- table. Tables created after the original GRANT are not covered by it.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'planner_ro') THEN
        GRANT SELECT ON policy_chunks TO planner_ro;
    END IF;
END
$$;
