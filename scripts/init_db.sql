-- 1. Enable Vector Extension
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Documents Table
CREATE TABLE IF NOT EXISTS documents (
    doc_id        SERIAL PRIMARY KEY,
    title         TEXT NOT NULL,
    version_label TEXT,
    jurisdiction  TEXT,
    year          INT,
    source_path   TEXT,
    created_at    TIMESTAMPTZ DEFAULT now()
);

-- 3. Sections Table
CREATE TABLE IF NOT EXISTS sections (
    section_id        SERIAL PRIMARY KEY,
    doc_id            INT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    
    -- CHANGE 1: Removed "NOT NULL" so unnumbered intro sections don't crash DB
    section_number    TEXT, 
    
    heading           TEXT,
    level             INT,
    parent_section_id INT REFERENCES sections(section_id),
    page_start        INT,
    page_end          INT,
    summary           TEXT
    
    -- CHANGE 2: Removed "UNIQUE(doc_id, section_number)" to fix the duplicate error
);

-- 4. Chunks Table
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id      BIGSERIAL PRIMARY KEY,
    doc_id        INT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    section_id    INT REFERENCES sections(section_id),
    chunk_index   INT NOT NULL,
    page_number   INT,
    text          TEXT NOT NULL,
    is_table      BOOLEAN DEFAULT FALSE,
    token_count   INT,
    citation_code TEXT,
    embedding     VECTOR(768)  -- Matches BAAI/bge-base-en-v1.5
);

-- 5. Indexes
CREATE INDEX IF NOT EXISTS idx_chunks_doc_section
    ON chunks(doc_id, section_id, chunk_index);

-- CHANGE 3: Switched to HNSW (Hierarchical Navigable Small World)
-- It is faster and more accurate than IVFFLAT for this scale.
CREATE INDEX IF NOT EXISTS idx_chunks_embedding
    ON chunks
    USING hnsw (embedding vector_cosine_ops);

-- 6. Cross References Table
CREATE TABLE IF NOT EXISTS cross_references (
    ref_id          BIGSERIAL PRIMARY KEY,
    from_section_id INT NOT NULL REFERENCES sections(section_id) ON DELETE CASCADE,
    to_section_id   INT REFERENCES sections(section_id),
    raw_text        TEXT NOT NULL,
    note            TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);