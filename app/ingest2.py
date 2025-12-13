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
        dbname=os.getenv("DB_NAME", "taxrag"),
        user=os.getenv("DB_USER", "taxuser"),
        password=os.getenv("DB_PASSWORD", "password"),
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 5432))
    )

def smart_chunking(text, chunk_size=450):
    lines = text.split('\n')
    current_chunk = []
    current_count = 0
    for line in lines:
        token_count = len(line.split())
        if current_count + token_count > chunk_size and current_chunk:
            yield "\n".join(current_chunk)
            current_chunk = []
            current_count = 0
        current_chunk.append(line)
        current_count += token_count
    if current_chunk:
        yield "\n".join(current_chunk)

def parse_markdown_with_path(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    heading_stack = {} 
    current_level = 0
    current_heading = "Preamble"
    current_content = []
    
    header_pattern = re.compile(r"^(#+)\s+(.*)")
    clause_pattern = re.compile(r"^(\d+)\.\s+([A-Z].*)")

    for line in lines:
        stripped = line.strip()
        if not stripped: continue

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
            new_level = 3 
            new_heading = f"{num}. {title.strip()}"
            is_new_section = True

        if is_new_section:
            if current_content:
                path_parts = [heading_stack[l] for l in sorted(heading_stack.keys())]
                full_path = " > ".join(path_parts)
                yield current_level, full_path, current_heading, "\n".join(current_content)
            
            current_level = new_level
            current_heading = new_heading
            current_content = []
            
            keys_to_remove = [k for k in heading_stack if k >= new_level]
            for k in keys_to_remove: del heading_stack[k]
            heading_stack[new_level] = new_heading
        else:
            current_content.append(line)
            
    if current_content:
        path_parts = [heading_stack[l] for l in sorted(heading_stack.keys())]
        full_path = " > ".join(path_parts)
        yield current_level, full_path, current_heading, "\n".join(current_content)

def ingest_structured(md_file_path, title, jurisdiction, year):
    if not os.path.exists(md_file_path):
        print(f"❌ File not found: {md_file_path}")
        return

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        print(f"🚀 Ingesting {md_file_path}...")
        
        # 1. Create Document
        cursor.execute("""
            INSERT INTO documents (title, jurisdiction, year, source_path)
            VALUES (%s, %s, %s, %s) RETURNING doc_id;
        """, (title, jurisdiction, year, md_file_path))
        doc_id = cursor.fetchone()[0]

        section_stack = {} 
        sections_found = 0
        chunks_inserted = 0
        
        # 2. Ingest Sections from File
        for level, full_path, heading, content in parse_markdown_with_path(md_file_path):
            sections_found += 1
            if len(content.split()) < 15: continue # Skip junk

            parent_id = None
            if level > 1:
                for l in range(level - 1, 0, -1):
                    if l in section_stack:
                        parent_id = section_stack[l]
                        break
            
            sec_num_match = re.search(r"^(\d+)\.", heading)
            sec_number = sec_num_match.group(1) if sec_num_match else None

            cursor.execute("""
                INSERT INTO sections (doc_id, section_number, heading, level, parent_section_id)
                VALUES (%s, %s, %s, %s, %s) RETURNING section_id;
            """, (doc_id, sec_number, heading, level, parent_id))
            section_id = cursor.fetchone()[0]
            section_stack[level] = section_id
            
            chunk_batches = list(smart_chunking(content))
            for i, raw_text in enumerate(chunk_batches):
                if not raw_text.strip(): continue 
                
                # Context Injection
                if not full_path: full_path = heading 
                enriched_text = f"Context: {full_path}\n---\n{raw_text}"
                
                emb = retriever_model.encode(enriched_text).tolist()
                
                cursor.execute("""
                    INSERT INTO chunks (doc_id, section_id, chunk_index, text, token_count, embedding, text_search)
                    VALUES (%s, %s, %s, %s, %s, %s, to_tsvector('english', %s));
                """, (doc_id, section_id, i, raw_text, len(raw_text.split()), emb, raw_text))
                
                chunks_inserted += 1

            if sections_found % 50 == 0:
                conn.commit()
                print(f"   -> Processed {sections_found} sections...")

        # --- 3. AUTO-INSERT MANUAL SLABS ---
        print("📝 Injecting Manual Tax Slabs...")
        
        # Text for the manual chunk
        slab_text = """Current Income Tax Slabs (New Regime): 
        - Up to Rs. 3,00,000: Nil
        - Rs. 3,00,000 to Rs. 6,00,000: 5%
        - Rs. 6,00,000 to Rs. 9,00,000: 10%
        - Rs. 9,00,000 to Rs. 12,00,000: 15%
        - Rs. 12,00,000 to Rs. 15,00,000: 20%
        - Above Rs. 15,00,000: 30%."""
        
        # Generate embedding for it
        slab_embedding = retriever_model.encode(slab_text).tolist()
        
        # Insert using the doc_id we just created
        # We attach it to NULL section_id (or you could create a "Summary" section if you prefer)
        cursor.execute("""
            INSERT INTO chunks (doc_id, section_id, chunk_index, text, token_count, embedding, text_search)
            VALUES (%s, NULL, 0, %s, %s, %s, to_tsvector('english', %s));
        """, (doc_id, slab_text, len(slab_text.split()), slab_embedding, slab_text))
        
        chunks_inserted += 1
        print("✅ Manual Slabs Injected.")
        # -----------------------------------

        conn.commit()
        print(f"🎉 DONE! Total Sections: {sections_found}, Total Chunks: {chunks_inserted}")

    except Exception as e:
        conn.rollback()
        print(f"❌ Error: {e}")
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    # WARNING: Still run TRUNCATE manually in SQL if you want a totally fresh start!
    # docker exec -it tax-pg psql -U taxuser -d taxrag -c "TRUNCATE documents CASCADE;"
    
    path = "parsed_cache/The_Income-tax_Bill_2025.md"
    ingest_structured(path, "Income Tax Bill", "India", 2025)