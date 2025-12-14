# import os
# import re
# import psycopg2
# from dotenv import load_dotenv
# from urllib.parse import urlparse
# from pathlib import Path
# from sentence_transformers import SentenceTransformer

# load_dotenv()

# # ============================================================
# # DB
# # ============================================================
# def get_db_connection():
#     db_url = os.getenv("DATABASE_URL2")
#     if not db_url:
#         raise ValueError("DATABASE_URL2 not set")
#     r = urlparse(db_url)
#     return psycopg2.connect(
#         dbname=r.path[1:],
#         user=r.username,
#         password=r.password,
#         host=r.hostname,
#         port=r.port
#     )

# # ============================================================
# # CONFIG
# # ============================================================
# MD_PATH = "/Users/rahulbharti/Desktop/Tax_QA/parsed_cache/The_Income-tax_Bill_2025.md"

# CHUNK_TOKENS = 500
# CHUNK_OVERLAP = 80
# MIN_SECTION_CHARS = 200

# HEADER_RE = re.compile(r"^(#+)\s+(.*)$")

# embedder = SentenceTransformer("BAAI/bge-base-en-v1.5")

# # ============================================================
# # HELPERS
# # ============================================================
# class Section:
#     def __init__(self, section_id, level, heading, path):
#         self.section_id = section_id
#         self.level = level
#         self.heading = heading
#         self.path = path
#         self.buffer = []

# def extract_section_number(text):
#     m = re.search(r"\b(\d+(\(\d+\))?)\b", text)
#     return m.group(1) if m else None

# def chunk_text(text, size, overlap):
#     words = text.split()
#     chunks = []
#     i = 0
#     while i < len(words):
#         chunks.append(" ".join(words[i:i+size]))
#         i += size - overlap
#     return chunks

# def build_embedding_input(section, chunk):
#     return f"""
# [Hierarchy]
# {section.path}

# [Legal Unit]
# {section.heading}

# [Text]
# {chunk}
# """.strip()

# # ============================================================
# # INGESTION
# # ============================================================
# def ingest():
#     conn = get_db_connection()
#     cur = conn.cursor()

#     try:
#         # Reset
#         cur.execute("""
#             TRUNCATE chunks, sections, documents
#             RESTART IDENTITY CASCADE;
#         """)

#         # Insert document
#         cur.execute("""
#             INSERT INTO documents (title, year, jurisdiction, version_label, source_path)
#             VALUES (%s, %s, %s, %s, %s)
#             RETURNING doc_id;
#         """, (
#             "Income-tax Act, 2025",
#             2025,
#             "India",
#             "As introduced in Lok Sabha",
#             MD_PATH
#         ))
#         doc_id = cur.fetchone()[0]

#         section_stack = []
#         all_sections = []

#         lines = Path(MD_PATH).read_text(encoding="utf-8").splitlines()

#         # ---------------- Parse MD ----------------
#         for line in lines:
#             line = line.rstrip()

#             m = HEADER_RE.match(line)
#             if m:
#                 hashes, heading = m.groups()
#                 level = len(hashes)

#                 while section_stack and section_stack[-1].level >= level:
#                     section_stack.pop()

#                 parent = section_stack[-1] if section_stack else None
#                 path = heading if not parent else f"{parent.path} > {heading}"

#                 section_number = extract_section_number(heading)

#                 cur.execute("""
#                     INSERT INTO sections (
#                         doc_id, heading, section_number, level,
#                         parent_section_id, path
#                     )
#                     VALUES (%s, %s, %s, %s, %s, %s)
#                     RETURNING section_id;
#                 """, (
#                     doc_id,
#                     heading,
#                     section_number,
#                     level,
#                     parent.section_id if parent else None,
#                     path
#                 ))

#                 section_id = cur.fetchone()[0]
#                 section = Section(section_id, level, heading, path)

#                 section_stack.append(section)
#                 all_sections.append(section)
#                 continue

#             if section_stack:
#                 section_stack[-1].buffer.append(line)

#         # ---------------- Chunk leaf sections ----------------
#         chunk_index = 0
#         for section in all_sections:
#             text = "\n".join(section.buffer).strip()
#             if len(text) < MIN_SECTION_CHARS:
#                 continue

#             chunks = chunk_text(text, CHUNK_TOKENS, CHUNK_OVERLAP)
#             for chunk in chunks:
#                 emb_input = build_embedding_input(section, chunk)
#                 embedding = embedder.encode(emb_input).tolist()

#                 cur.execute("""
#                     INSERT INTO chunks (
#                         doc_id, section_id, content,
#                         embedding, chunk_index,
#                         token_count, section_path, citations
#                     )
#                     VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
#                 """, (
#                     doc_id,
#                     section.section_id,
#                     chunk,
#                     embedding,
#                     chunk_index,
#                     len(chunk.split()),
#                     section.path,
#                     [extract_section_number(section.heading)]
#                 ))

#                 chunk_index += 1

#         conn.commit()
#         print("✅ Ingestion complete")

#     except Exception:
#         conn.rollback()
#         raise
#     finally:
#         cur.close()
#         conn.close()

# # ============================================================
# # RUN
# # ============================================================
# if __name__ == "__main__":
#     ingest()
import os
import re
import psycopg2
from dotenv import load_dotenv
from urllib.parse import urlparse
from pathlib import Path
from sentence_transformers import SentenceTransformer
from collections import defaultdict
path_counter = defaultdict(int)

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
# CONFIG
# ============================================================
MD_PATH = "/Users/rahulbharti/Desktop/Tax_QA/parsed_cache/The_Income-tax_Bill_2025.md"

CHUNK_TOKENS = 500
CHUNK_OVERLAP = 80
MIN_SECTION_CHARS = 200

HEADER_RE = re.compile(r"^(#+)\s+(.*)$")

embedder = SentenceTransformer("BAAI/bge-base-en-v1.5")

# ============================================================
# HELPERS
# ============================================================
class Section:
    def __init__(self, section_id, level, heading, path):
        self.section_id = section_id
        self.level = level
        self.heading = heading
        self.path = path
        self.buffer = []
        self.children = []

def extract_section_number(text):
    m = re.search(r"\b(\d+(\(\d+\))?)\b", text)
    return m.group(1) if m else None

def chunk_text(text, size, overlap):
    words = text.split()
    chunks = []
    i = 0
    step = max(1, size - overlap)
    while i < len(words):
        chunk = " ".join(words[i:i + size]).strip()
        if chunk:
            chunks.append(chunk)
        i += step
    return chunks

def build_embedding_input(section, chunk):
    return f"""
[Hierarchy]
{section.path}

[Legal Unit]
{section.heading}

[Text]
{chunk}
""".strip()

# ============================================================
# INGESTION
# ============================================================
def ingest():
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        # Reset (dev-mode ingestion)
        cur.execute("""
            TRUNCATE chunks, sections, documents
            RESTART IDENTITY CASCADE;
        """)

        # Insert document
        cur.execute("""
            INSERT INTO documents (title, year, jurisdiction, version_label, source_path)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING doc_id;
        """, (
            "Income-tax Act, 2025",
            2025,
            "India",
            "As introduced in Lok Sabha",
            MD_PATH
        ))
        doc_id = cur.fetchone()[0]

        section_stack = []
        all_sections = []

        lines = Path(MD_PATH).read_text(encoding="utf-8").splitlines()

        # ---------------- Parse Markdown ----------------
        for line in lines:
            line = line.rstrip()
            if not line:
                continue

            m = HEADER_RE.match(line)
            if m:
                hashes, heading = m.groups()
                level = len(hashes)

                while section_stack and section_stack[-1].level >= level:
                    section_stack.pop()

                parent = section_stack[-1] if section_stack else None
                base_path = heading if not parent else f"{parent.path} > {heading}"
                path_counter[base_path] += 1

                if path_counter[base_path] > 1:
                    path = f"{base_path} [#{path_counter[base_path]}]"
                else:
                    path = base_path


                section_number = extract_section_number(heading)

                cur.execute("""
                    INSERT INTO sections (
                        doc_id, heading, section_number, level,
                        parent_section_id, path
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING section_id;
                """, (
                    doc_id,
                    heading,
                    section_number,
                    level,
                    parent.section_id if parent else None,
                    path
                ))

                section_id = cur.fetchone()[0]
                section = Section(section_id, level, heading, path)

                if parent:
                    parent.children.append(section)

                section_stack.append(section)
                all_sections.append(section)
                continue

            if section_stack:
                section_stack[-1].buffer.append(line)

        # ---------------- Chunk ONLY leaf sections ----------------
        chunk_index = 0

        for section in all_sections:
            if section.children:
                continue  # skip non-leaf sections

            text = "\n".join(section.buffer).strip()
            if len(text) < MIN_SECTION_CHARS:
                continue

            chunks = chunk_text(text, CHUNK_TOKENS, CHUNK_OVERLAP)

            for chunk in chunks:
                emb_input = build_embedding_input(section, chunk)
                embedding = embedder.encode(emb_input).tolist()

                sn = extract_section_number(section.heading)
                citations = [sn] if sn else []

                cur.execute("""
                    INSERT INTO chunks (
                        doc_id, section_id, content,
                        embedding, chunk_index,
                        token_count, section_path, citations
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                """, (
                    doc_id,
                    section.section_id,
                    chunk,
                    embedding,
                    chunk_index,
                    len(chunk.split()),
                    section.path,
                    citations
                ))

                chunk_index += 1

        conn.commit()
        print("✅ Ingestion complete")

    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()

# ============================================================
# RUN
# ============================================================
if __name__ == "__main__":
    ingest()
