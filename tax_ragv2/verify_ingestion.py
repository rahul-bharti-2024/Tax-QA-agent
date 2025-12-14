import os
import psycopg2
from urllib.parse import urlparse
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# DB
# ============================================================
def get_db_connection():
    db_url = os.getenv("DATABASE_URL2")
    if not db_url:
        raise ValueError("DATABASE_URL2 not set")
    r = urlparse(db_url)
    return psycopg2.connect(
        dbname=r.path[1:],
        user=r.username,
        password=r.password,
        host=r.hostname,
        port=r.port
    )

# ============================================================
# ASSERT HELPERS
# ============================================================
def assert_true(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"✅ {msg}")

def fetch_one(cur, q):
    cur.execute(q)
    return cur.fetchone()[0]

# ============================================================
# VERIFICATION
# ============================================================
def verify():
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        print("\n=== SCHEMA CHECKS ===")

        # Tables
        tables = fetch_one(cur, """
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_name IN ('documents','sections','chunks');
        """)
        assert_true(tables == 3, "All core tables exist")

        # Sections.path
        path_col = fetch_one(cur, """
            SELECT COUNT(*) FROM information_schema.columns
            WHERE table_name='sections' AND column_name='path';
        """)
        assert_true(path_col == 1, "`sections.path` exists")

        # Chunks.embedding
        emb_col = fetch_one(cur, """
            SELECT COUNT(*) FROM information_schema.columns
            WHERE table_name='chunks' AND column_name='embedding';
        """)
        assert_true(emb_col == 1, "`chunks.embedding` exists")

        # TSVECTOR
        tsv_col = fetch_one(cur, """
            SELECT COUNT(*) FROM information_schema.columns
            WHERE table_name='chunks' AND column_name='content_tsv';
        """)
        assert_true(tsv_col == 1, "`chunks.content_tsv` exists")

        print("\n=== BASIC COUNTS ===")

        docs = fetch_one(cur, "SELECT COUNT(*) FROM documents;")
        sections = fetch_one(cur, "SELECT COUNT(*) FROM sections;")
        chunks = fetch_one(cur, "SELECT COUNT(*) FROM chunks;")

        assert_true(docs >= 1, "At least one document ingested")
        assert_true(sections > 0, "Sections ingested")
        assert_true(chunks > 0, "Chunks ingested")

        print(f"   documents: {docs}")
        print(f"   sections : {sections}")
        print(f"   chunks   : {chunks}")

        print("\n=== UNIQUENESS & FK CHECKS ===")

        dup_paths = fetch_one(cur, """
            SELECT COUNT(*) FROM (
                SELECT doc_id, path, COUNT(*)
                FROM sections
                GROUP BY doc_id, path
                HAVING COUNT(*) > 1
            ) t;
        """)
        assert_true(dup_paths == 0, "No duplicate (doc_id, path) in sections")

        orphan_chunks = fetch_one(cur, """
            SELECT COUNT(*) FROM chunks c
            LEFT JOIN sections s ON c.section_id = s.section_id
            WHERE s.section_id IS NULL;
        """)
        assert_true(orphan_chunks == 0, "No chunks with missing section")

        print("\n=== LEAF-ONLY CHUNK CHECK ===")

        non_leaf_chunks = fetch_one(cur, """
            SELECT COUNT(*)
            FROM chunks c
            JOIN sections s ON c.section_id = s.section_id
            WHERE EXISTS (
                SELECT 1 FROM sections child
                WHERE child.parent_section_id = s.section_id
            );
        """)
        assert_true(non_leaf_chunks == 0, "Chunks only attached to leaf sections")

        print("\n=== CONTENT SANITY ===")

        empty_chunks = fetch_one(cur, """
            SELECT COUNT(*) FROM chunks
            WHERE LENGTH(TRIM(content)) = 0;
        """)
        assert_true(empty_chunks == 0, "No empty / trivial chunks")

        bad_citations = fetch_one(cur, """
            SELECT COUNT(*) FROM chunks
            WHERE citations @> ARRAY[NULL::text];
        """)
        assert_true(bad_citations == 0, "No NULL values in citations array")

        print("\n=== EMBEDDING CHECKS ===")

        bad_dim = fetch_one(cur, """
            SELECT COUNT(*) FROM chunks
            WHERE embedding IS NULL OR vector_dims(embedding) != 768;
        """)
        assert_true(bad_dim == 0, "All embeddings present and 768-dim")

        print("\n=== DISTRIBUTION CHECKS ===")

        max_depth = fetch_one(cur, """
            SELECT MAX(array_length(string_to_array(path, ' > '), 1))
            FROM sections;
        """)
        print(f"   max hierarchy depth: {max_depth}")
        assert_true(max_depth <= 10, "Hierarchy depth is sane")

        avg_tokens = fetch_one(cur, """
            SELECT ROUND(AVG(token_count)) FROM chunks;
        """)
        print(f"   avg chunk tokens: {avg_tokens}")
        assert_true(avg_tokens > 100, "Chunks are non-trivially sized")

        print("\n🎉 ALL CHECKS PASSED — INGESTION IS SOUND 🎉")

    finally:
        cur.close()
        conn.close()

# ============================================================
# RUN
# ============================================================
if __name__ == "__main__":
    verify()
