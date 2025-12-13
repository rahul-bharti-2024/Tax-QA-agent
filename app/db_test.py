# check_data.py
import os
import psycopg2
from dotenv import load_dotenv
from urllib.parse import urlparse

load_dotenv()

def get_db_connection():
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        result = urlparse(db_url)
        return psycopg2.connect(
            dbname=result.path[1:],
            user=result.username,
            password=result.password,
            host=result.hostname,
            port=result.port
        )

    return psycopg2.connect(
        dbname=os.getenv("DB_NAME", "postgres"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "password"),
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432").strip())
    )

conn = get_db_connection()
cur = conn.cursor()

print("🔍 Checking for 'Person' definition...")

# Find definition-like phrases
cur.execute("""
    SELECT text
    FROM chunks
    WHERE text ILIKE '%person means%'
       OR text ILIKE '%"person" means%'
       OR text ILIKE '%person includes%'
       OR text ILIKE '%"person" includes%'
    LIMIT 5;
""")

rows = cur.fetchall()

if not rows:
    print("❌ No definition for 'Person' found in your database.")
else:
    print(f"✅ Found {len(rows)} possible definition(s):")
    for r in rows:
        print(f"---\n{r[0][:300]}...\n")

cur.close()
conn.close()
