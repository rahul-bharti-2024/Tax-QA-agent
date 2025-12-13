
import os
import re
import psycopg2
from dotenv import load_dotenv
from urllib.parse import urlparse
from sentence_transformers import SentenceTransformer

# 1. Load Environment Variables
load_dotenv()

# 2. Model Setup
print("Loading Embedding Model...")
retriever_model = SentenceTransformer('BAAI/bge-base-en-v1.5')

def get_db_connection():
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        result = urlparse(db_url)
        return psycopg2.connect(
            dbname=result.path[1:], user=result.username,
            password=result.password, host=result.hostname, port=result.port
        )
    return psycopg2.connect(
        dbname=os.getenv("DB_NAME", "postgres"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "password"),
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432").strip())
    )

def extract_references(text):
    pattern = r"(?:Section|Clause|Article|§)\s+([\d\.]+[a-z]?)"
    matches = re.findall(pattern, text, re.IGNORECASE)
    clean_matches = [m.rstrip('.') for m in matches]
    return list(set(clean_matches))

def chunk_text(text, chunk_size=500):
    words = text.split()
    for i in range(0, len(words), chunk_size):
        yield " ".join(words[i:i + chunk_size])

def parse_markdown_structure(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    current_level = 0
    current_heading = "Preamble / Introduction"
    current_content = []
    
    # Regex 1: Explicit Markdown Headers (# CHAPTER I, # 20. Income...)
    header_pattern = re.compile(r"^(#+)\s+(.*)")
    
    # Regex 2: Clause Definitions at start of line (e.g., "1. Short title...")
    clause_pattern = re.compile(r"^(\d+)\.\s+(.*)")

    for line in lines:
        stripped_line = line.strip()
        if not stripped_line: continue

        md_match = header_pattern.match(line)
        clause_match = clause_pattern.match(line) if not md_match else None

        is_new_section = False
        new_heading = ""
        new_level = 0

        if md_match:
            hashes, title = md_match.groups()
            new_level = len(hashes)
            new_heading = title.strip()
            is_new_section = True
        elif clause_match:
            num, title = clause_match.groups()
            new_level = 2 
            new_heading = f"{num}. {title.strip()}"
            is_new_section = True

        if is_new_section:
            if current_content:
                yield current_level, current_heading, "\n".join(current_content)
            
            current_level = new_level
            current_heading = new_heading
            current_content = []
        else:
            current_content.append(line)
            
    if current_content:
        yield current_level, current_heading, "\n".join(current_content)

def ingest_structured(md_file_path, title, jurisdiction, year):
    if not os.path.exists(md_file_path):
        print(f"❌ File not found: {md_file_path}")
        return

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        print(f"🚀 Ingesting {md_file_path}...")
        cursor.execute("""
            INSERT INTO documents (title, jurisdiction, year, source_path)
            VALUES (%s, %s, %s, %s) RETURNING doc_id;
        """, (title, jurisdiction, year, md_file_path))
        doc_id = cursor.fetchone()[0]

        section_stack = {} 
        sections_found = 0
        chunks_inserted = 0
        
        # --- NEW: Counter for sections without numbers ---
        unnumbered_counter = 0

        for level, heading, content in parse_markdown_structure(md_file_path):
            sections_found += 1
            
            parent_id = None
            if level > 1:
                for l in range(level - 1, 0, -1):
                    if l in section_stack:
                        parent_id = section_stack[l]
                        break
            
            # --- FIXED LOGIC ---
            sec_num_match = re.search(r"^(\d+)\.", heading)
            if sec_num_match:
                sec_number = sec_num_match.group(1)
            else:
                # Assign unique ID to avoid duplicates (e.g., "0-1", "0-2")
                unnumbered_counter += 1
                sec_number = f"0-{unnumbered_counter}"

            cursor.execute("""
                INSERT INTO sections (doc_id, section_number, heading, level, parent_section_id)
                VALUES (%s, %s, %s, %s, %s) RETURNING section_id;
            """, (doc_id, sec_number, heading, level, parent_id))
            section_id = cursor.fetchone()[0]

            section_stack[level] = section_id
            
            chunk_batches = list(chunk_text(content))
            for i, chunk_text_str in enumerate(chunk_batches):
                if not chunk_text_str.strip(): continue 
                
                emb = retriever_model.encode(chunk_text_str).tolist()
                
                cursor.execute("""
                    INSERT INTO chunks (doc_id, section_id, chunk_index, text, token_count, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s);
                """, (doc_id, section_id, i, chunk_text_str, len(chunk_text_str.split()), emb))
                
                refs = extract_references(chunk_text_str)
                for r in refs:
                    cursor.execute("""
                        INSERT INTO cross_references (from_section_id, raw_text)
                        VALUES (%s, %s);
                    """, (section_id, r))
                
                chunks_inserted += 1

            if sections_found % 50 == 0:
                conn.commit()
                print(f"   -> Processed {sections_found} sections...")

        conn.commit()
        print(f"✅ Finished! Sections: {sections_found}, Chunks: {chunks_inserted}")
        
        print("🔗 Linking Cross-References...")
        cursor.execute("""
            UPDATE cross_references cr
            SET to_section_id = s.section_id
            FROM sections s
            WHERE s.doc_id = %s
              AND TRIM(s.section_number) = TRIM(cr.raw_text);
        """, (doc_id,))
        conn.commit()
        print("🎉 Done.")

    except Exception as e:
        conn.rollback()
        print(f"❌ Error: {e}")
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    # IMPORTANT: Wipe the DB one last time
    # docker exec -it tax-pg psql -U taxuser -d taxrag -c "TRUNCATE documents CASCADE;"
    path = "parsed_cache/The_Income-tax_Bill_2025.md"
    ingest_structured(path, "Income Tax Bill", "India", 2025)