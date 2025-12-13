import os
import psycopg2
from dotenv import load_dotenv
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from urllib.parse import urlparse

# 1. Setup
load_dotenv()
embed_model = HuggingFaceEmbedding(model_name="BAAI/bge-base-en-v1.5")

def get_db_connection():
    db_url = os.getenv("DATABASE_URL")
    result = urlparse(db_url)
    return psycopg2.connect(
        dbname=result.path[1:], user=result.username,
        password=result.password, host=result.hostname, port=result.port
    )

def fix_null_embeddings():
    conn = get_db_connection()
    cursor = conn.cursor()

    print("🔍 Looking for chunks with NULL embeddings...")
    
    # Select chunks that have text but NO embedding
    cursor.execute("SELECT chunk_id, text FROM chunks WHERE embedding IS NULL AND text IS NOT NULL;")
    rows = cursor.fetchall()
    
    if not rows:
        print("✅ All chunks already have embeddings! Nothing to do.")
        return

    print(f"⚠️ Found {len(rows)} chunks without vectors. Generating now...")

    for chunk_id, text in rows:
        print(f"   -> Processing Chunk ID {chunk_id}...")
        
        # Generate Vector
        embedding = embed_model.get_text_embedding(text)
        
        # Update DB
        cursor.execute(
            "UPDATE chunks SET embedding = %s::vector WHERE chunk_id = %s;",
            (embedding, chunk_id)
        )
        conn.commit()
        
    print("🎉 Success! All manual chunks are now visible to Vector Search.")
    cursor.close()
    conn.close()

if __name__ == "__main__":
    fix_null_embeddings()