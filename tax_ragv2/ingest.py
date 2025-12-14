
# # # # # import os
# # # # # import re
# # # # # import psycopg2
# # # # # from dotenv import load_dotenv
# # # # # from urllib.parse import urlparse
# # # # # from sentence_transformers import SentenceTransformer

# # # # # # ============================================================
# # # # # # Setup
# # # # # # ============================================================
# # # # # load_dotenv()

# # # # # print("Loading Embedding Model...")
# # # # # retriever_model = SentenceTransformer("BAAI/bge-base-en-v1.5")

# # # # # # ============================================================
# # # # # # DB
# # # # # # ============================================================
# # # # # def get_db_connection():
# # # # #     db_url = os.getenv("DATABASE_URL2")
# # # # #     result = urlparse(db_url)
# # # # #     return psycopg2.connect(
# # # # #         dbname=result.path[1:],
# # # # #         user=result.username,
# # # # #         password=result.password,
# # # # #         host=result.hostname,
# # # # #         port=result.port
# # # # #     )

# # # # # # ============================================================
# # # # # # Regex & helpers
# # # # # # ============================================================
# # # # # CHAPTER_RE = re.compile(
# # # # #     r"^\s*(?:#\s*)?CHAPTER\s+([IVXLC]+)(?:\s|$|[-–—])",
# # # # #     re.IGNORECASE
# # # # # )

# # # # # SECTION_RE = re.compile(r"^(\d+)\.\s+[A-Z]")

# # # # # IGNORE_HEADINGS = {
# # # # #     "ARRANGEMENT OF CLAUSES",
# # # # #     "CLAUSES",
# # # # #     "SCHEDULE I", "SCHEDULE II", "SCHEDULE III",
# # # # #     "SCHEDULE IV", "SCHEDULE V", "SCHEDULE VI",
# # # # #     "SCHEDULE VII", "SCHEDULE VIII", "SCHEDULE IX",
# # # # #     "SCHEDULE X", "SCHEDULE XI", "SCHEDULE XII",
# # # # #     "SCHEDULE XIII", "SCHEDULE XIV", "SCHEDULE XV",
# # # # #     "SCHEDULE XVI"
# # # # # }

# # # # # # ============================================================
# # # # # # Governing detection (heading + content)
# # # # # # ============================================================
# # # # # def is_governing_text(heading: str, text: str) -> bool:
# # # # #     h = heading.lower()
# # # # #     t = text.lower()
# # # # #     return (
# # # # #         "definition" in h
# # # # #         or "total income" in h
# # # # #         or "total income" in t
# # # # #         or "shall be included" in t
# # # # #         or "shall not be included" in t
# # # # #         or "in computing the total income" in t
# # # # #         or "chargeable to income-tax" in t
# # # # #     )

# # # # # def is_real_content_start(line):
# # # # #     s = line.strip()
# # # # #     return (
# # # # #         s.startswith("1.")
# # # # #         or s.startswith("CHAPTER")
# # # # #         or s.startswith("# CHAPTER")
# # # # #     )

# # # # # # ============================================================
# # # # # # Chunking limits (HARD guarantees)
# # # # # # ============================================================
# # # # # MAX_CHUNKS_PER_SECTION = 6
# # # # # MAX_WORDS_PER_CHUNK = 900
# # # # # MAX_CHARS_PER_CHUNK = 3200   # 🔒 DB-safe hard cap

# # # # # def smart_chunking(text, size=450):
# # # # #     words = text.split()
# # # # #     for i in range(0, len(words), size):
# # # # #         yield " ".join(words[i:i + size])

# # # # # def governing_chunking(text, max_words=MAX_WORDS_PER_CHUNK):
# # # # #     paragraphs = re.split(r"\n\s*\n", text)
# # # # #     buf, cnt = [], 0

# # # # #     for p in paragraphs:
# # # # #         w = len(p.split())
# # # # #         if cnt + w > max_words and buf:
# # # # #             yield "\n\n".join(buf)
# # # # #             buf, cnt = [], 0
# # # # #         buf.append(p)
# # # # #         cnt += w

# # # # #     if buf:
# # # # #         yield "\n\n".join(buf)

# # # # # # ============================================================
# # # # # # Ingestion
# # # # # # ============================================================
# # # # # def ingest_structured(md_file_path, title, jurisdiction, year):
# # # # #     conn = get_db_connection()
# # # # #     cur = conn.cursor()

# # # # #     with open(md_file_path, encoding="utf-8") as f:
# # # # #         lines = f.readlines()

# # # # #     # Create document
# # # # #     cur.execute("""
# # # # #         INSERT INTO documents (title, jurisdiction, year, source_path)
# # # # #         VALUES (%s, %s, %s, %s)
# # # # #         RETURNING doc_id;
# # # # #     """, (title, jurisdiction, year, md_file_path))
# # # # #     doc_id = cur.fetchone()[0]

# # # # #     current_chapter = None
# # # # #     chapter_title = None
# # # # #     current_section = None
# # # # #     current_section_heading = None
# # # # #     buffer = []
# # # # #     in_real_content = False
# # # # #     section_id = None
# # # # #     section_chunk_count = 0   # 🔒 global per-section counter

# # # # #     def flush_section():
# # # # #         nonlocal buffer, section_id, section_chunk_count

# # # # #         if not section_id or not buffer:
# # # # #             buffer = []
# # # # #             return

# # # # #         text = "\n".join(buffer).strip()
# # # # #         buffer = []

# # # # #         if len(text.split()) < 30:
# # # # #             return

# # # # #         is_gov = (
# # # # #             current_section_heading
# # # # #             and is_governing_text(current_section_heading, text)
# # # # #         )

# # # # #         if is_gov:
# # # # #             chunks = list(governing_chunking(text))
# # # # #         else:
# # # # #             chunks = list(smart_chunking(text))

# # # # #         for chunk in chunks:
# # # # #             if section_chunk_count < MAX_CHUNKS_PER_SECTION:
# # # # #                 continue

# # # # #             # 🔒 HARD character cap (cannot be bypassed)
# # # # #             chunk = chunk[:MAX_CHARS_PER_CHUNK]

# # # # #             enriched = f"""
# # # # # Chapter: {current_chapter}
# # # # # Title: {chapter_title}
# # # # # Section: {current_section}

# # # # # {chunk}
# # # # # """.strip()

# # # # #             emb = retriever_model.encode(enriched).tolist()

# # # # #             cur.execute("""
# # # # #                 INSERT INTO chunks (
# # # # #                     doc_id, section_id, chunk_index,
# # # # #                     text, token_count,
# # # # #                     embedding, source_type,
# # # # #                     citation_code
# # # # #                 )
# # # # #                 VALUES (%s, %s, %s, %s, %s, %s, 'statute', %s);
# # # # #             """, (
# # # # #                 doc_id,
# # # # #                 section_id,
# # # # #                 section_chunk_count,
# # # # #                 chunk,
# # # # #                 len(chunk.split()),
# # # # #                 emb,
# # # # #                 f"Section {current_section}"
# # # # #             ))

# # # # #             section_chunk_count += 1

# # # # #     for line in lines:
# # # # #         line = line.rstrip()

# # # # #         if not in_real_content and is_real_content_start(line):
# # # # #             in_real_content = True
# # # # #         if not in_real_content:
# # # # #             continue

# # # # #         m = CHAPTER_RE.match(line)
# # # # #         if m:
# # # # #             flush_section()
# # # # #             current_chapter = f"CHAPTER {m.group(1)}"
# # # # #             chapter_title = None
# # # # #             continue

# # # # #         if line.startswith("#") and current_chapter and not chapter_title:
# # # # #             t = line.replace("#", "").strip()
# # # # #             if t not in IGNORE_HEADINGS:
# # # # #                 chapter_title = t
# # # # #             continue

# # # # #         s = SECTION_RE.match(line)
# # # # #         if s:
# # # # #             flush_section()
# # # # #             section_chunk_count = 0   # 🔒 reset per section

# # # # #             current_section = s.group(1)
# # # # #             current_section_heading = line.split(".", 1)[1].strip()

# # # # #             if current_chapter is None:
# # # # #                 current_chapter = "CHAPTER I"

# # # # #             cur.execute("""
# # # # #                 INSERT INTO sections (
# # # # #                     doc_id, section_number,
# # # # #                     heading, level, parent_section_id, chapter
# # # # #                 )
# # # # #                 VALUES (%s, %s, %s, %s, NULL, %s)
# # # # #                 RETURNING section_id;
# # # # #             """, (
# # # # #                 doc_id,
# # # # #                 current_section,
# # # # #                 current_section_heading,
# # # # #                 1,
# # # # #                 current_chapter
# # # # #             ))
# # # # #             section_id = cur.fetchone()[0]
# # # # #             continue

# # # # #         if section_id:
# # # # #             if re.match(r"^\(\d+\)", line.strip()):
# # # # #                 continue
# # # # #             if line.lstrip().startswith("#"):
# # # # #                 continue
# # # # #             buffer.append(line)

# # # # #     flush_section()
# # # # #     conn.commit()
# # # # #     cur.close()
# # # # #     conn.close()

# # # # #     print("✅ Ingestion complete")

# # # # # # ============================================================
# # # # # # Run
# # # # # # ============================================================
# # # # # if __name__ == "__main__":
# # # # #     ingest_structured(
# # # # #         "parsed_cache/The_Income-tax_Bill_2025.md",
# # # # #         "Income-tax Act, 2025",
# # # # #         "India",
# # # # #         2025
# # # # #     )


# # # # # # import os
# # # # # # import re
# # # # # # import psycopg2
# # # # # # from dotenv import load_dotenv
# # # # # # from urllib.parse import urlparse
# # # # # # from sentence_transformers import SentenceTransformer

# # # # # # # ============================================================
# # # # # # # Setup
# # # # # # # ============================================================
# # # # # # load_dotenv()

# # # # # # print("Loading Embedding Model...")
# # # # # # retriever_model = SentenceTransformer("BAAI/bge-base-en-v1.5")

# # # # # # # ============================================================
# # # # # # # DB
# # # # # # # ============================================================
# # # # # # def get_db_connection():
# # # # # #     db_url = os.getenv("DATABASE_URL2")
# # # # # #     if not db_url:
# # # # # #         raise ValueError("DATABASE_URL2 is not set in env")
# # # # # #     result = urlparse(db_url)
# # # # # #     return psycopg2.connect(
# # # # # #         dbname=result.path[1:],
# # # # # #         user=result.username,
# # # # # #         password=result.password,
# # # # # #         host=result.hostname,
# # # # # #         port=result.port
# # # # # #     )

# # # # # # # ============================================================
# # # # # # # Regex & helpers
# # # # # # # ============================================================
# # # # # # # Improved Regex to be more permissive with spacing and casing
# # # # # # CHAPTER_RE = re.compile(
# # # # # #     r"^\s*(?:#\s*)?CHAPTER\s+([IVXLC\d]+)", 
# # # # # #     re.IGNORECASE
# # # # # # )

# # # # # # # Matches "123. Heading" or "123. heading"
# # # # # # SECTION_RE = re.compile(r"^(\d+)\.\s+(.*)") 

# # # # # # IGNORE_HEADINGS = {
# # # # # #     "ARRANGEMENT OF CLAUSES", "CLAUSES",
# # # # # #     # Add Schedules if necessary, or handle them as sections
# # # # # # }

# # # # # # # ============================================================
# # # # # # # Chunking limits
# # # # # # # ============================================================
# # # # # # # REMOVED: MAX_CHUNKS_PER_SECTION (Don't limit depth of law)
# # # # # # MAX_CHARS_PER_CHUNK = 3500  # Hard DB Safe Cap
# # # # # # TARGET_CHUNK_SIZE = 500     # Target words

# # # # # # def smart_chunking(text, target_words=TARGET_CHUNK_SIZE):
# # # # # #     """
# # # # # #     Splits by paragraphs first to preserve sentence structure where possible.
# # # # # #     Aggregates paragraphs until target size is reached.
# # # # # #     """
# # # # # #     paragraphs = text.split("\n")
# # # # # #     buf = []
# # # # # #     current_word_count = 0

# # # # # #     for p in paragraphs:
# # # # # #         p = p.strip()
# # # # # #         if not p:
# # # # # #             continue
            
# # # # # #         w_count = len(p.split())
        
# # # # # #         # If adding this paragraph exceeds limit significantly, flush current buffer
# # # # # #         if current_word_count + w_count > target_words and buf:
# # # # # #             yield "\n\n".join(buf)
# # # # # #             buf = [p]
# # # # # #             current_word_count = w_count
# # # # # #         else:
# # # # # #             buf.append(p)
# # # # # #             current_word_count += w_count
    
# # # # # #     if buf:
# # # # # #         yield "\n\n".join(buf)

# # # # # # # ============================================================
# # # # # # # Ingestion
# # # # # # # ============================================================
# # # # # # def ingest_structured(md_file_path, title, jurisdiction, year):
# # # # # #     conn = get_db_connection()
# # # # # #     cur = conn.cursor()

# # # # # #     with open(md_file_path, encoding="utf-8") as f:
# # # # # #         lines = f.readlines()

# # # # # #     # Create document
# # # # # #     cur.execute("""
# # # # # #         INSERT INTO documents (title, jurisdiction, year, source_path)
# # # # # #         VALUES (%s, %s, %s, %s)
# # # # # #         RETURNING doc_id;
# # # # # #     """, (title, jurisdiction, year, md_file_path))
# # # # # #     doc_id = cur.fetchone()[0]

# # # # # #     current_chapter = "PRELIMINARY"
# # # # # #     chapter_title = ""
# # # # # #     current_section = None
# # # # # #     current_section_heading = None
# # # # # #     buffer = []
# # # # # #     in_real_content = False
# # # # # #     section_id = None
# # # # # #     section_chunk_count = 0 

# # # # # #     def flush_section():
# # # # # #         nonlocal buffer, section_id, section_chunk_count

# # # # # #         if not section_id or not buffer:
# # # # # #             buffer = []
# # # # # #             return

# # # # # #         text = "\n".join(buffer).strip()
# # # # # #         buffer = []

# # # # # #         if not text:
# # # # # #             return

# # # # # #         # Use the safer chunking logic for all text
# # # # # #         chunks = list(smart_chunking(text))

# # # # # #         for chunk in chunks:
# # # # # #             # 🔒 HARD character cap for DB safety
# # # # # #             chunk = chunk[:MAX_CHARS_PER_CHUNK]

# # # # # #             # Contextual Enrichment
# # # # # #             enriched = f"Chapter: {current_chapter} - {chapter_title}\nSection: {current_section} - {current_section_heading}\n\n{chunk}"

# # # # # #             emb = retriever_model.encode(enriched).tolist()

# # # # # #             cur.execute("""
# # # # # #                 INSERT INTO chunks (
# # # # # #                     doc_id, section_id, chunk_index,
# # # # # #                     text, token_count,
# # # # # #                     embedding, source_type,
# # # # # #                     citation_code
# # # # # #                 )
# # # # # #                 VALUES (%s, %s, %s, %s, %s, %s, 'statute', %s);
# # # # # #             """, (
# # # # # #                 doc_id,
# # # # # #                 section_id,
# # # # # #                 section_chunk_count,
# # # # # #                 chunk,
# # # # # #                 len(chunk.split()),
# # # # # #                 emb,
# # # # # #                 f"Section {current_section}"
# # # # # #             ))

# # # # # #             section_chunk_count += 1

# # # # # #     for line in lines:
# # # # # #         line = line.strip() # Strip immediately to handle indentations
# # # # # #         if not line: continue

# # # # # #         # Detect Start of Real Content (Skip Indexes)
# # # # # #         if not in_real_content:
# # # # # #             if line.startswith("CHAPTER") or line.startswith("# CHAPTER") or line.startswith("1. "):
# # # # # #                 in_real_content = True
# # # # # #             else:
# # # # # #                 continue

# # # # # #         # 1. Detect Chapter
# # # # # #         m = CHAPTER_RE.match(line)
# # # # # #         if m:
# # # # # #             flush_section()
# # # # # #             current_chapter = f"CHAPTER {m.group(1)}"
# # # # # #             # Reset title, wait for next line or extract if on same line
# # # # # #             chapter_title = "" 
# # # # # #             continue

# # # # # #         # 2. Detect Chapter Title (Heuristic: All caps line after Chapter or lines starting with #)
# # # # # #         if line.startswith("#") and current_chapter and not chapter_title:
# # # # # #             t = line.replace("#", "").strip()
# # # # # #             if t not in IGNORE_HEADINGS:
# # # # # #                 chapter_title = t
# # # # # #             continue

# # # # # #         # 3. Detect Section
# # # # # #         s = SECTION_RE.match(line)
# # # # # #         if s:
# # # # # #             flush_section()
# # # # # #             section_chunk_count = 0

# # # # # #             current_section = s.group(1)
# # # # # #             current_section_heading = s.group(2).strip()

# # # # # #             cur.execute("""
# # # # # #                 INSERT INTO sections (
# # # # # #                     doc_id, section_number,
# # # # # #                     heading, level, parent_section_id, chapter
# # # # # #                 )
# # # # # #                 VALUES (%s, %s, %s, %s, NULL, %s)
# # # # # #                 RETURNING section_id;
# # # # # #             """, (
# # # # # #                 doc_id,
# # # # # #                 current_section,
# # # # # #                 current_section_heading,
# # # # # #                 1,
# # # # # #                 current_chapter
# # # # # #             ))
# # # # # #             section_id = cur.fetchone()[0]
# # # # # #             continue

# # # # # #         # 4. Accumulate Content
# # # # # #         if section_id:
# # # # # #             # CRITICAL FIX: Removed the "if (d) continue" check
# # # # # #             # Also filtering out markdown artifacts if needed
# # # # # #             if line.startswith("###"): continue 
# # # # # #             buffer.append(line)

# # # # # #     # Final flush
# # # # # #     flush_section()
# # # # # #     conn.commit()
# # # # # #     cur.close()
# # # # # #     conn.close()

# # # # # #     print("✅ Ingestion complete")

# # # # # # if __name__ == "__main__":
# # # # # #     # Ensure your Markdown file exists at this path
# # # # # #     ingest_structured(
# # # # # #         "parsed_cache/The_Income-tax_Bill_2025.md",
# # # # # #         "Income-tax Act, 2025",
# # # # # #         "India",
# # # # # #         2025
# # # # # #     )


# # # # import os
# # # # import re
# # # # import psycopg2
# # # # from dotenv import load_dotenv
# # # # from urllib.parse import urlparse
# # # # from sentence_transformers import SentenceTransformer

# # # # # ============================================================
# # # # # Setup
# # # # # ============================================================
# # # # load_dotenv()

# # # # print("Loading Embedding Model...")
# # # # retriever_model = SentenceTransformer("BAAI/bge-base-en-v1.5")

# # # # # ============================================================
# # # # # DB
# # # # # ============================================================
# # # # def get_db_connection():
# # # #     db_url = os.getenv("DATABASE_URL2")
# # # #     if not db_url:
# # # #         raise ValueError("DATABASE_URL2 not set")
# # # #     result = urlparse(db_url)
# # # #     return psycopg2.connect(
# # # #         dbname=result.path[1:],
# # # #         user=result.username,
# # # #         password=result.password,
# # # #         host=result.hostname,
# # # #         port=result.port
# # # #     )

# # # # # ============================================================
# # # # # Regex
# # # # # ============================================================
# # # # CHAPTER_RE = re.compile(
# # # #     r"^\s*(?:#\s*)?CHAPTER\s+([IVXLC]+)(?:\s|$|[-–—])",
# # # #     re.IGNORECASE
# # # # )
# # # # SECTION_RE = re.compile(r"^(\d+)\.\s+[A-Z]")

# # # # IGNORE_HEADINGS = {
# # # #     "ARRANGEMENT OF CLAUSES", "CLAUSES",
# # # #     "SCHEDULE I", "SCHEDULE II", "SCHEDULE III",
# # # #     "SCHEDULE IV", "SCHEDULE V", "SCHEDULE VI",
# # # #     "SCHEDULE VII", "SCHEDULE VIII", "SCHEDULE IX",
# # # #     "SCHEDULE X", "SCHEDULE XI", "SCHEDULE XII",
# # # #     "SCHEDULE XIII", "SCHEDULE XIV", "SCHEDULE XV",
# # # #     "SCHEDULE XVI"
# # # # }

# # # # # ============================================================
# # # # # Chunking guarantees
# # # # # ============================================================
# # # # MAX_CHUNKS_PER_SECTION = 6
# # # # MAX_WORDS_PER_CHUNK = 900
# # # # MAX_CHARS_PER_CHUNK = 3200

# # # # def smart_chunking(text, size=450):
# # # #     words = text.split()
# # # #     for i in range(0, len(words), size):
# # # #         yield " ".join(words[i:i + size])

# # # # def governing_chunking(text):
# # # #     paragraphs = re.split(r"\n\s*\n", text)
# # # #     buf, cnt = [], 0
# # # #     for p in paragraphs:
# # # #         w = len(p.split())
# # # #         if cnt + w > MAX_WORDS_PER_CHUNK and buf:
# # # #             yield "\n\n".join(buf)
# # # #             buf, cnt = [], 0
# # # #         buf.append(p)
# # # #         cnt += w
# # # #     if buf:
# # # #         yield "\n\n".join(buf)

# # # # def is_governing_text(heading, text):
# # # #     t = text.lower()
# # # #     h = heading.lower()
# # # #     return (
# # # #         "definition" in h or
# # # #         "total income" in h or
# # # #         "total income" in t or
# # # #         "chargeable to income-tax" in t or
# # # #         "shall be included" in t or
# # # #         "shall not be included" in t
# # # #     )

# # # # # ============================================================
# # # # # Ingestion
# # # # # ============================================================
# # # # def ingest_structured(md_path, title, jurisdiction, year):
# # # #     conn = get_db_connection()
# # # #     cur = conn.cursor()

# # # #     try:
# # # #         with open(md_path, encoding="utf-8") as f:
# # # #             lines = f.readlines()

# # # #         # ---------------- DOCUMENT UPSERT ----------------
# # # #         cur.execute("""
# # # #             INSERT INTO documents (title, jurisdiction, year, source_path)
# # # #             VALUES (%s, %s, %s, %s)
# # # #             ON CONFLICT (title, jurisdiction, year)
# # # #             DO UPDATE SET source_path = EXCLUDED.source_path,
# # # #                           created_at = now()
# # # #             RETURNING doc_id;
# # # #         """, (title, jurisdiction, year, md_path))
# # # #         doc_id = cur.fetchone()[0]

# # # #         current_chapter = None
# # # #         chapter_title = None
# # # #         current_section = None
# # # #         current_heading = None
# # # #         buffer = []
# # # #         section_id = None
# # # #         chunk_idx = 0
# # # #         in_content = False

# # # #         def flush_section():
# # # #             nonlocal buffer, section_id, chunk_idx

# # # #             if not section_id or not buffer:
# # # #                 buffer = []
# # # #                 return

# # # #             text = "\n".join(buffer).strip()
# # # #             buffer = []

# # # #             if len(text.split()) < 30:
# # # #                 return

# # # #             if is_governing_text(current_heading, text):
# # # #                 chunks = list(governing_chunking(text))
# # # #             else:
# # # #                 chunks = list(smart_chunking(text))

# # # #             chunks = chunks[:MAX_CHUNKS_PER_SECTION]

# # # #             for i, chunk in enumerate(chunks):
# # # #                 chunk = chunk[:MAX_CHARS_PER_CHUNK]

# # # #                 enriched = f"""Chapter: {current_chapter}
# # # # Section: {current_section} - {current_heading}

# # # # {chunk}"""

# # # #                 emb = retriever_model.encode(enriched).tolist()

# # # #                 cur.execute("""
# # # #                     INSERT INTO chunks (
# # # #                         doc_id, section_id, chunk_index,
# # # #                         text, token_count, embedding,
# # # #                         citation_code
# # # #                     )
# # # #                     VALUES (%s, %s, %s, %s, %s, %s, %s)
# # # #                     ON CONFLICT (section_id, chunk_index)
# # # #                     DO UPDATE SET
# # # #                         text = EXCLUDED.text,
# # # #                         token_count = EXCLUDED.token_count,
# # # #                         embedding = EXCLUDED.embedding,
# # # #                         citation_code = EXCLUDED.citation_code;
# # # #                 """, (
# # # #                     doc_id,
# # # #                     section_id,
# # # #                     i,
# # # #                     chunk,
# # # #                     len(chunk.split()),
# # # #                     emb,
# # # #                     f"Section {current_section}"
# # # #                 ))

# # # #         # ---------------- PARSE ----------------
# # # #         for raw in lines:
# # # #             line = raw.rstrip()

# # # #             if not in_content:
# # # #                 if line.startswith("CHAPTER") or line.startswith("# CHAPTER") or line.startswith("1."):
# # # #                     in_content = True
# # # #                 else:
# # # #                     continue

# # # #             m = CHAPTER_RE.match(line)
# # # #             if m:
# # # #                 flush_section()
# # # #                 current_chapter = f"CHAPTER {m.group(1)}"
# # # #                 chapter_title = None
# # # #                 continue

# # # #             if line.startswith("#") and current_chapter and not chapter_title:
# # # #                 t = line.replace("#", "").strip()
# # # #                 if t not in IGNORE_HEADINGS:
# # # #                     chapter_title = t
# # # #                 continue

# # # #             s = SECTION_RE.match(line)
# # # #             if s:
# # # #                 flush_section()
# # # #                 chunk_idx = 0
# # # #                 current_section = s.group(1)
# # # #                 current_heading = line.split(".", 1)[1].strip()

# # # #                 cur.execute("""
# # # #                     INSERT INTO sections (
# # # #                         doc_id, section_number, heading,
# # # #                         level, chapter
# # # #                     )
# # # #                     VALUES (%s, %s, %s, 1, %s)
# # # #                     ON CONFLICT (doc_id, section_number, chapter)
# # # #                     DO UPDATE SET heading = EXCLUDED.heading
# # # #                     RETURNING section_id;
# # # #                 """, (
# # # #                     doc_id,
# # # #                     current_section,
# # # #                     current_heading,
# # # #                     current_chapter
# # # #                 ))
# # # #                 section_id = cur.fetchone()[0]
# # # #                 continue

# # # #             if section_id:
# # # #                 if re.match(r"^\(\d+\)", line.strip()):
# # # #                     continue
# # # #                 if line.lstrip().startswith("#"):
# # # #                     continue
# # # #                 buffer.append(line)

# # # #         flush_section()
# # # #         conn.commit()
# # # #         print("✅ Ingestion complete")

# # # #     except Exception:
# # # #         conn.rollback()
# # # #         raise
# # # #     finally:
# # # #         cur.close()
# # # #         conn.close()

# # # # # ============================================================
# # # # # Run
# # # # # ============================================================
# # # # if __name__ == "__main__":
# # # #     ingest_structured(
# # # #         "parsed_cache/The_Income-tax_Bill_2025.md",
# # # #         "Income-tax Act, 2025",
# # # #         "India",
# # # #         2025
# # # #     )

# # # import os
# # # import re
# # # import psycopg2
# # # from dotenv import load_dotenv
# # # from urllib.parse import urlparse
# # # from sentence_transformers import SentenceTransformer

# # # # ============================================================
# # # # Setup
# # # # ============================================================
# # # load_dotenv()

# # # print("Loading Embedding Model...")
# # # retriever_model = SentenceTransformer("BAAI/bge-base-en-v1.5")

# # # # ============================================================
# # # # DB
# # # # ============================================================
# # # def get_db_connection():
# # #     db_url = os.getenv("DATABASE_URL2")
# # #     if not db_url:
# # #         raise ValueError("DATABASE_URL2 not set")
# # #     result = urlparse(db_url)
# # #     return psycopg2.connect(
# # #         dbname=result.path[1:],
# # #         user=result.username,
# # #         password=result.password,
# # #         host=result.hostname,
# # #         port=result.port
# # #     )

# # # # ============================================================
# # # # 🔧 ENSURE REQUIRED CONSTRAINTS (THE FIX)
# # # # ============================================================
# # # def ensure_constraints(cur):
# # #     cur.execute("""
# # #         CREATE UNIQUE INDEX IF NOT EXISTS uniq_documents_identity
# # #         ON documents (title, jurisdiction, year);
# # #     """)

# # #     cur.execute("""
# # #         CREATE UNIQUE INDEX IF NOT EXISTS uniq_sections_identity
# # #         ON sections (doc_id, section_number, chapter);
# # #     """)

# # #     cur.execute("""
# # #         CREATE UNIQUE INDEX IF NOT EXISTS uniq_chunks_identity
# # #         ON chunks (section_id, chunk_index);
# # #     """)

# # # # ============================================================
# # # # Regex
# # # # ============================================================
# # # CHAPTER_RE = re.compile(
# # #     r"^\s*(?:#\s*)?CHAPTER\s+([IVXLC]+)(?:\s|$|[-–—])",
# # #     re.IGNORECASE
# # # )
# # # SECTION_RE = re.compile(r"^(\d+)\.\s+[A-Z]")

# # # IGNORE_HEADINGS = {
# # #     "ARRANGEMENT OF CLAUSES", "CLAUSES",
# # #     "SCHEDULE I", "SCHEDULE II", "SCHEDULE III",
# # #     "SCHEDULE IV", "SCHEDULE V", "SCHEDULE VI",
# # #     "SCHEDULE VII", "SCHEDULE VIII", "SCHEDULE IX",
# # #     "SCHEDULE X", "SCHEDULE XI", "SCHEDULE XII",
# # #     "SCHEDULE XIII", "SCHEDULE XIV", "SCHEDULE XV",
# # #     "SCHEDULE XVI"
# # # }

# # # # ============================================================
# # # # Chunking guarantees
# # # # ============================================================
# # # MAX_CHUNKS_PER_SECTION = 6
# # # MAX_WORDS_PER_CHUNK = 900
# # # MAX_CHARS_PER_CHUNK = 3200

# # # def smart_chunking(text, size=450):
# # #     words = text.split()
# # #     for i in range(0, len(words), size):
# # #         yield " ".join(words[i:i + size])

# # # def governing_chunking(text):
# # #     paragraphs = re.split(r"\n\s*\n", text)
# # #     buf, cnt = [], 0
# # #     for p in paragraphs:
# # #         w = len(p.split())
# # #         if cnt + w > MAX_WORDS_PER_CHUNK and buf:
# # #             yield "\n\n".join(buf)
# # #             buf, cnt = [], 0
# # #         buf.append(p)
# # #         cnt += w
# # #     if buf:
# # #         yield "\n\n".join(buf)

# # # def is_governing_text(heading, text):
# # #     t = text.lower()
# # #     h = heading.lower()
# # #     return (
# # #         "definition" in h or
# # #         "total income" in h or
# # #         "chargeable to income-tax" in t or
# # #         "shall be included" in t or
# # #         "shall not be included" in t
# # #     )

# # # # ============================================================
# # # # Ingestion
# # # # ============================================================
# # # def ingest_structured(md_path, title, jurisdiction, year):
# # #     conn = get_db_connection()
# # #     cur = conn.cursor()

# # #     try:
# # #         # 🔧 ENSURE SCHEMA IS SAFE
# # #         ensure_constraints(cur)

# # #         with open(md_path, encoding="utf-8") as f:
# # #             lines = f.readlines()

# # #         # ---------------- DOCUMENT UPSERT ----------------
# # #         cur.execute("""
# # #             INSERT INTO documents (title, jurisdiction, year, source_path)
# # #             VALUES (%s, %s, %s, %s)
# # #             ON CONFLICT (title, jurisdiction, year)
# # #             DO UPDATE SET source_path = EXCLUDED.source_path
# # #             RETURNING doc_id;
# # #         """, (title, jurisdiction, year, md_path))
# # #         doc_id = cur.fetchone()[0]

# # #         current_chapter = None
# # #         current_section = None
# # #         current_heading = None
# # #         buffer = []
# # #         section_id = None
# # #         in_content = False

# # #         def flush_section():
# # #             nonlocal buffer, section_id
# # #             if not section_id or not buffer:
# # #                 buffer = []
# # #                 return

# # #             text = "\n".join(buffer).strip()
# # #             buffer = []

# # #             if len(text.split()) < 30:
# # #                 return

# # #             chunks = (
# # #                 governing_chunking(text)
# # #                 if is_governing_text(current_heading, text)
# # #                 else smart_chunking(text)
# # #             )

# # #             for idx, chunk in enumerate(list(chunks)[:MAX_CHUNKS_PER_SECTION]):
# # #                 chunk = chunk[:MAX_CHARS_PER_CHUNK]
# # #                 emb = retriever_model.encode(chunk).tolist()

# # #                 cur.execute("""
# # #                     INSERT INTO chunks (
# # #                         doc_id, section_id, chunk_index,
# # #                         text, token_count, embedding, citation_code
# # #                     )
# # #                     VALUES (%s, %s, %s, %s, %s, %s, %s)
# # #                     ON CONFLICT (section_id, chunk_index)
# # #                     DO UPDATE SET
# # #                         text = EXCLUDED.text,
# # #                         token_count = EXCLUDED.token_count,
# # #                         embedding = EXCLUDED.embedding,
# # #                         citation_code = EXCLUDED.citation_code;
# # #                 """, (
# # #                     doc_id,
# # #                     section_id,
# # #                     idx,
# # #                     chunk,
# # #                     len(chunk.split()),
# # #                     emb,
# # #                     f"Section {current_section}"
# # #                 ))

# # #         for raw in lines:
# # #             line = raw.rstrip()

# # #             if not in_content:
# # #                 if line.startswith("CHAPTER") or line.startswith("# CHAPTER") or line.startswith("1."):
# # #                     in_content = True
# # #                 else:
# # #                     continue

# # #             m = CHAPTER_RE.match(line)
# # #             if m:
# # #                 flush_section()
# # #                 current_chapter = f"CHAPTER {m.group(1)}"
# # #                 continue

# # #             s = SECTION_RE.match(line)
# # #             if s:
# # #                 flush_section()
# # #                 current_section = s.group(1)
# # #                 current_heading = line.split(".", 1)[1].strip()

# # #                 cur.execute("""
# # #                     INSERT INTO sections (doc_id, section_number, heading, level, chapter)
# # #                     VALUES (%s, %s, %s, 1, %s)
# # #                     ON CONFLICT (doc_id, section_number, chapter)
# # #                     DO UPDATE SET heading = EXCLUDED.heading
# # #                     RETURNING section_id;
# # #                 """, (
# # #                     doc_id,
# # #                     current_section,
# # #                     current_heading,
# # #                     current_chapter
# # #                 ))
# # #                 section_id = cur.fetchone()[0]
# # #                 continue

# # #             if section_id:
# # #                 if line.lstrip().startswith("#"):
# # #                     continue
# # #                 buffer.append(line)

# # #         flush_section()
# # #         conn.commit()
# # #         print("✅ Ingestion complete")

# # #     except Exception:
# # #         conn.rollback()
# # #         raise
# # #     finally:
# # #         cur.close()
# # #         conn.close()

# # # # ============================================================
# # # # Run
# # # # ============================================================
# # # if __name__ == "__main__":
# # #     ingest_structured(
# # #         "parsed_cache/The_Income-tax_Bill_2025.md",
# # #         "Income-tax Act, 2025",
# # #         "India",
# # #         2025
# # #     )
# # import os
# # import re
# # import psycopg2
# # from dotenv import load_dotenv
# # from urllib.parse import urlparse
# # from sentence_transformers import SentenceTransformer

# # # ===============================
# # # Setup
# # # ===============================
# # load_dotenv()
# # embedder = SentenceTransformer("BAAI/bge-base-en-v1.5")

# # def get_db():
# #     url = urlparse(os.getenv("DATABASE_URL2"))
# #     return psycopg2.connect(
# #         dbname=url.path[1:],
# #         user=url.username,
# #         password=url.password,
# #         host=url.hostname,
# #         port=url.port
# #     )

# # # ===============================
# # # Regex
# # # ===============================
# # CHAPTER_RE = re.compile(r"^\s*(?:#\s*)?CHAPTER\s+([IVXLC]+)", re.I)
# # SECTION_RE = re.compile(r"^(\d+)\.\s+(.*)")

# # # ===============================
# # # Chunking
# # # ===============================
# # MAX_CHARS = 3200
# # MAX_CHUNKS = 6

# # def chunk_text(text, size=450):
# #     words = text.split()
# #     for i in range(0, len(words), size):
# #         yield " ".join(words[i:i+size])

# # # ===============================
# # # Ingestion
# # # ===============================
# # def ingest(md_path, title, jurisdiction, year):
# #     conn = get_db()
# #     cur = conn.cursor()

# #     with open(md_path, encoding="utf-8") as f:
# #         lines = f.readlines()

# #     # ---- document upsert ----
# #     cur.execute("""
# #         INSERT INTO documents (title, jurisdiction, year, source_path)
# #         VALUES (%s, %s, %s, %s)
# #         ON CONFLICT (title, jurisdiction, year)
# #         DO UPDATE SET source_path = EXCLUDED.source_path
# #         RETURNING doc_id;
# #     """, (title, jurisdiction, year, md_path))
# #     doc_id = cur.fetchone()[0]

# #     current_chapter = None
# #     section_id = None
# #     buffer = []

# #     def flush_section(section_id, section_number):
# #         if not section_id or not buffer:
# #             buffer.clear()
# #             return

# #         text = "\n".join(buffer).strip()
# #         buffer.clear()

# #         chunks = list(chunk_text(text))[:MAX_CHUNKS]

# #         for idx, ch in enumerate(chunks):
# #             ch = ch[:MAX_CHARS]
# #             emb = embedder.encode(ch).tolist()

# #             cur.execute("""
# #                 INSERT INTO chunks (
# #                     doc_id, section_id, chunk_index,
# #                     text, token_count, citation, embedding
# #                 )
# #                 VALUES (%s,%s,%s,%s,%s,%s,%s)
# #                 ON CONFLICT (section_id, chunk_index)
# #                 DO UPDATE SET
# #                     text = EXCLUDED.text,
# #                     token_count = EXCLUDED.token_count,
# #                     embedding = EXCLUDED.embedding;
# #             """, (
# #                 doc_id,
# #                 section_id,
# #                 idx,
# #                 ch,
# #                 len(ch.split()),
# #                 f"Section {section_number}",
# #                 emb
# #             ))

# #     # ---- parse ----
# #     for raw in lines:
# #         line = raw.strip()
# #         if not line:
# #             continue

# #         ch = CHAPTER_RE.match(line)
# #         if ch:
# #             flush_section(section_id, current_section)
# #             current_chapter = f"CHAPTER {ch.group(1)}"
# #             section_id = None
# #             continue

# #         sec = SECTION_RE.match(line)
# #         if sec:
# #             flush_section(section_id, current_section)
# #             current_section = sec.group(1)
# #             heading = sec.group(2)

# #             cur.execute("""
# #                 INSERT INTO sections (doc_id, chapter, section_number, heading)
# #                 VALUES (%s,%s,%s,%s)
# #                 ON CONFLICT (doc_id, chapter, section_number)
# #                 DO UPDATE SET heading = EXCLUDED.heading
# #                 RETURNING section_id;
# #             """, (doc_id, current_chapter, current_section, heading))
# #             section_id = cur.fetchone()[0]
# #             continue

# #         if section_id:
# #             buffer.append(line)

# #     flush_section(section_id, current_section)

# #     conn.commit()
# #     cur.close()
# #     conn.close()
# #     print("✅ Ingestion complete")

# # # ===============================
# # # Run
# # # ===============================
# # if __name__ == "__main__":
# #     ingest(
# #         "parsed_cache/The_Income-tax_Bill_2025.md",
# #         "Income-tax Act, 2025",
# #         "India",
# #         2025
# #     )
# import os
# import re
# import psycopg2
# from dotenv import load_dotenv
# from urllib.parse import urlparse
# from sentence_transformers import SentenceTransformer

# # ============================================================
# # Setup
# # ============================================================
# load_dotenv()

# DB_URL = os.getenv("DATABASE_URL2")
# if not DB_URL:
#     raise ValueError("DATABASE_URL2 not set")

# print("Loading embedding model...")
# embedder = SentenceTransformer("BAAI/bge-base-en-v1.5")

# def get_conn():
#     u = urlparse(DB_URL)
#     return psycopg2.connect(
#         dbname=u.path[1:],
#         user=u.username,
#         password=u.password,
#         host=u.hostname,
#         port=u.port
#     )

# # ============================================================
# # Regex
# # ============================================================
# CHAPTER_RE = re.compile(r"^\s*(?:#\s*)?CHAPTER\s+([IVXLC]+)", re.I)
# SECTION_RE = re.compile(r"^(\d+)\.\s+(.*)")

# IGNORE = {
#     "ARRANGEMENT OF CLAUSES", "CLAUSES"
# }

# # ============================================================
# # Chunking (hard guarantees)
# # ============================================================
# MAX_CHUNKS = 6
# MAX_CHARS = 3200
# WORDS_PER_CHUNK = 450

# def chunk_text(text):
#     words = text.split()
#     for i in range(0, len(words), WORDS_PER_CHUNK):
#         yield " ".join(words[i:i+WORDS_PER_CHUNK])

# # ============================================================
# # Ingestion
# # ============================================================
# def ingest(md_path, title, jurisdiction, year):
#     conn = get_conn()
#     cur = conn.cursor()

#     with open(md_path, encoding="utf-8") as f:
#         lines = f.readlines()

#     # ---------------- DOCUMENT ----------------
#     cur.execute("""
#         INSERT INTO documents (title, jurisdiction, year, source_path)
#         VALUES (%s, %s, %s, %s)
#         ON CONFLICT (title, jurisdiction, year)
#         DO UPDATE SET source_path = EXCLUDED.source_path
#         RETURNING doc_id;
#     """, (title, jurisdiction, year, md_path))
#     doc_id = cur.fetchone()[0]

#     current_chapter = None
#     current_section = None
#     current_heading = None
#     buffer = []
#     section_id = None
#     in_content = False

#     def flush_section():
#         nonlocal buffer, section_id

#         if not section_id or not buffer:
#             buffer = []
#             return

#         text = "\n".join(buffer).strip()
#         buffer = []

#         if len(text.split()) < 30:
#             return

#         chunks = list(chunk_text(text))[:MAX_CHUNKS]

#         for idx, chunk in enumerate(chunks):
#             chunk = chunk[:MAX_CHARS]

#             emb = embedder.encode(
#                 f"Chapter: {current_chapter}\n"
#                 f"Section: {current_section} - {current_heading}\n\n{chunk}"
#             ).tolist()

#             cur.execute("""
#                 INSERT INTO chunks (
#                     doc_id, section_id, chunk_index,
#                     text, token_count, embedding, citation
#                 )
#                 VALUES (%s, %s, %s, %s, %s, %s, %s)
#                 ON CONFLICT (section_id, chunk_index)
#                 DO UPDATE SET
#                     text = EXCLUDED.text,
#                     token_count = EXCLUDED.token_count,
#                     embedding = EXCLUDED.embedding,
#                     citation = EXCLUDED.citation;
#             """, (
#                 doc_id,
#                 section_id,
#                 idx,
#                 chunk,
#                 len(chunk.split()),
#                 emb,
#                 f"Section {current_section}"
#             ))

#     # ---------------- PARSE ----------------
#     for raw in lines:
#         line = raw.rstrip()

#         if not in_content:
#             if line.startswith("CHAPTER") or line.startswith("# CHAPTER") or line.startswith("1."):
#                 in_content = True
#             else:
#                 continue

#         m = CHAPTER_RE.match(line)
#         if m:
#             flush_section()
#             current_chapter = f"CHAPTER {m.group(1)}"
#             continue

#         if line.startswith("#") and current_chapter:
#             title_line = line.replace("#", "").strip()
#             if title_line not in IGNORE:
#                 continue

#         s = SECTION_RE.match(line)
#         if s:
#             flush_section()

#             current_section = s.group(1)
#             current_heading = s.group(2).strip()

#             cur.execute("""
#                 INSERT INTO sections (
#                     doc_id, chapter, section_number, heading
#                 )
#                 VALUES (%s, %s, %s, %s)
#                 ON CONFLICT (doc_id, chapter, section_number)
#                 DO UPDATE SET heading = EXCLUDED.heading
#                 RETURNING section_id;
#             """, (
#                 doc_id,
#                 current_chapter,
#                 current_section,
#                 current_heading
#             ))
#             section_id = cur.fetchone()[0]
#             continue

#         if section_id:
#             if re.match(r"^\(\d+\)", line.strip()):
#                 continue
#             if line.lstrip().startswith("#"):
#                 continue
#             buffer.append(line)

#     flush_section()
#     conn.commit()
#     cur.close()
#     conn.close()

#     print("✅ Ingestion complete")

# # ============================================================
# # Run
# # ============================================================
# if __name__ == "__main__":
#     ingest(
#         "parsed_cache/The_Income-tax_Bill_2025.md",
#         "Income-tax Act, 2025",
#         "India",
#         2025
#     )
import os
import re
import psycopg2
from dotenv import load_dotenv
from urllib.parse import urlparse
from sentence_transformers import SentenceTransformer


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
# Regex
# ============================================================
CHAPTER_RE = re.compile(
    r"^\s*(?:#\s*)?CHAPTER\s+([IVXLC]+)",
    re.IGNORECASE
)

SECTION_RE = re.compile(r"^(\d+)\.\s+(.*)")

IGNORE_HEADINGS = {
    "ARRANGEMENT OF CLAUSES",
    "CLAUSES",
}

# ============================================================
# Chunking limits
# ============================================================
MAX_CHUNKS_PER_SECTION = 6
MAX_WORDS_PER_CHUNK = 900
MAX_CHARS_PER_CHUNK = 3200

def smart_chunking(text, size=450):
    words = text.split()
    for i in range(0, len(words), size):
        yield " ".join(words[i:i + size])

def governing_chunking(text):
    paras = re.split(r"\n\s*\n", text)
    buf, cnt = [], 0
    for p in paras:
        w = len(p.split())
        if cnt + w > MAX_WORDS_PER_CHUNK and buf:
            yield "\n\n".join(buf)
            buf, cnt = [], 0
        buf.append(p)
        cnt += w
    if buf:
        yield "\n\n".join(buf)

def is_governing(heading, text):
    h = heading.lower()
    t = text.lower()
    return (
        "definition" in h
        or "total income" in h
        or "total income" in t
        or "chargeable to income-tax" in t
        or "shall be included" in t
        or "shall not be included" in t
    )

# ============================================================
# Ingestion
# ============================================================
def ingest(md_path, title, jurisdiction, year):
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        with open(md_path, encoding="utf-8") as f:
            lines = f.readlines()

        # ---------------- Document upsert ----------------
        cur.execute("""
            INSERT INTO documents (title, jurisdiction, year, source_path)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (title, jurisdiction, year)
            DO UPDATE SET source_path = EXCLUDED.source_path
            RETURNING doc_id;
        """, (title, jurisdiction, year, md_path))
        doc_id = cur.fetchone()[0]

        current_chapter = None
        chapter_title = None
        current_section = None
        current_heading = None
        buffer = []
        section_id = None
        in_content = False

        def flush_section():
            nonlocal buffer, section_id
            if not section_id or not buffer:
                buffer = []
                return

            text = "\n".join(buffer).strip()
            buffer = []

            if len(text.split()) < 30:
                return

            if is_governing(current_heading, text):
                chunks = list(governing_chunking(text))
            else:
                chunks = list(smart_chunking(text))

            chunks = chunks[:MAX_CHUNKS_PER_SECTION]

            for idx, chunk in enumerate(chunks):
                chunk = chunk[:MAX_CHARS_PER_CHUNK]

                enriched = f"""
Chapter: {current_chapter}
Section: {current_section} - {current_heading}

{chunk}
""".strip()

                emb = embedder.encode(enriched).tolist()

                cur.execute("""
                    INSERT INTO chunks (
                        doc_id, section_id, chunk_index,
                        text, token_count, embedding, citation
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (section_id, chunk_index)
                    DO UPDATE SET
                        text = EXCLUDED.text,
                        token_count = EXCLUDED.token_count,
                        embedding = EXCLUDED.embedding,
                        citation = EXCLUDED.citation;
                """, (
                    doc_id,
                    section_id,
                    idx,
                    chunk,
                    len(chunk.split()),
                    emb,
                    f"Section {current_section}"
                ))

        # ---------------- Parse file ----------------
        for raw in lines:
            line = raw.rstrip()
            if not line:
                continue

            if not in_content:
                if line.startswith("CHAPTER") or line.startswith("# CHAPTER") or line.startswith("1."):
                    in_content = True
                else:
                    continue

            m = CHAPTER_RE.match(line)
            if m:
                flush_section()
                current_chapter = f"CHAPTER {m.group(1)}"
                chapter_title = None
                continue

            if line.startswith("#") and current_chapter and not chapter_title:
                t = line.replace("#", "").strip()
                if t not in IGNORE_HEADINGS:
                    chapter_title = t
                continue

            s = SECTION_RE.match(line)
            if s:
                flush_section()
                current_section = s.group(1)
                current_heading = s.group(2).strip()

                cur.execute("""
                    INSERT INTO sections (
                        doc_id, chapter, section_number, heading
                    )
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (doc_id, chapter, section_number)
                    DO UPDATE SET heading = EXCLUDED.heading
                    RETURNING section_id;
                """, (
                    doc_id,
                    current_chapter,
                    current_section,
                    current_heading
                ))
                section_id = cur.fetchone()[0]
                continue

            if section_id:
                if re.match(r"^\(\d+\)", line.strip()):
                    continue
                if line.lstrip().startswith("#"):
                    continue
                buffer.append(line)

        flush_section()
        conn.commit()
        print("✅ Ingestion complete")

    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()

# ============================================================
# Run
# ============================================================
if __name__ == "__main__":
    ingest(
        "/Users/rahulbharti/Desktop/Tax_QA/parsed_cache/The_Income-tax_Bill_2025.md",
        "Income-tax Act, 2025",
        "India",
        2025
    )
