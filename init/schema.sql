
CREATE TABLE IF NOT EXISTS documents (
    doc_id        SERIAL PRIMARY KEY,
    title         TEXT NOT NULL,
    year          INT,
    jurisdiction  TEXT,
    version_label TEXT,
    source_path   TEXT,
    created_at    TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sections (
    section_id        SERIAL PRIMARY KEY,
    doc_id            INT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    heading           TEXT NOT NULL,
    section_number    TEXT,
    level             INT NOT NULL,
    parent_section_id INT REFERENCES sections(section_id),
    path              TEXT NOT NULL,
    UNIQUE (doc_id, path)
);

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id     SERIAL PRIMARY KEY,
    doc_id       INT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    section_id   INT REFERENCES sections(section_id),
    content      TEXT NOT NULL,
    embedding    VECTOR(768),
    content_tsv  TSVECTOR,
    chunk_index  INT,
    token_count  INT,
    section_path TEXT,
    citations    TEXT[],
    created_at   TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS chunks_embedding_ivfflat_idx
ON chunks USING ivfflat (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS chunks_tsv_idx
ON chunks USING GIN (content_tsv);

CREATE INDEX IF NOT EXISTS chunks_doc_id_idx ON chunks (doc_id);
CREATE INDEX IF NOT EXISTS chunks_section_id_idx ON chunks (section_id);

CREATE OR REPLACE FUNCTION chunks_tsv_trigger() RETURNS trigger AS $$
BEGIN
  NEW.content_tsv := to_tsvector('english', NEW.content);
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS tsv_update ON chunks;

CREATE TRIGGER tsv_update
BEFORE INSERT OR UPDATE ON chunks
FOR EACH ROW EXECUTE FUNCTION chunks_tsv_trigger();
