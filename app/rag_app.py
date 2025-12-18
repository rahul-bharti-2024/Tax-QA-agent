import os
import psycopg2
from dotenv import load_dotenv
from llama_index.llms.gemini import Gemini
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from sentence_transformers import CrossEncoder
from urllib.parse import urlparse
import re
import math

# ============================================================
# ENV + UTILS
# ============================================================
load_dotenv()

def sigmoid(x):
    return 1 / (1 + math.exp(-x))

if not os.getenv("GOOGLE_API_KEY"):
    raise ValueError("❌ GOOGLE_API_KEY not found")

# ============================================================
# MODELS
# ============================================================
print("Loading LLMs...")

#Query optimization 
llm_optimizer = Gemini(
    model="models/gemma-3-27b-it",
    temperature=0.10,
    top_p=0.9,
    max_tokens=150
)

#Reasoning
llm_reasoning = Gemini(
    model="models/gemma-3-27b-it",
    temperature=0.15,
    top_p=0.9,
    max_tokens=1000
)

#Final answer formatting
llm_answer = Gemini(
    model="models/gemma-3-27b-it",
    temperature=0.0,
    top_p=1.0,
    max_tokens=200
)


print("Loading Embedding Model...")
embed_model = HuggingFaceEmbedding(model_name="BAAI/bge-base-en-v1.5")

# print("Loading Reranker...")
# reranker_model = CrossEncoder("BAAI/bge-reranker-base")

reranker_model = CrossEncoder("sentence-transformers/all-MiniLM-L6-v2")

# reranker_model = CrossEncoder(
#     "nlpaueb/legal-bert-base-uncased",
#     max_length=512
# )
# reranker_model = CrossEncoder("law-ai/InLegalBERT", max_length=512)

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

def run_vector_search(cursor, query_embedding, limit=50):
    cursor.execute("""
        SELECT
            c.chunk_id,
            s.heading,
            s.section_number,
            c.content,
            GREATEST(0, 1 - (c.embedding <=> %s::vector)) AS score
        FROM chunks c
        JOIN sections s ON c.section_id = s.section_id
        ORDER BY c.embedding <=> %s::vector
        LIMIT %s;
    """, (query_embedding, query_embedding, limit))
    return cursor.fetchall()


def run_keyword_search(cursor, query_text, limit=50):
    cursor.execute("""
        SELECT
            c.chunk_id,
            s.heading,
            s.section_number,
            c.content,
            ts_rank_cd(c.content_tsv,
                websearch_to_tsquery('english', %s)
            ) AS score
        FROM chunks c
        JOIN sections s ON c.section_id = s.section_id
        WHERE c.content_tsv @@ websearch_to_tsquery('english', %s)
        ORDER BY score DESC
        LIMIT %s;
    """, (query_text, query_text, limit))
    return cursor.fetchall()


def perform_hybrid_fusion(vector_results, keyword_results, k=20):
    fused = {}

    for rank, row in enumerate(vector_results):
        cid = row[0]
        fused.setdefault(cid, {"row": row, "rrf": 0.0})
        fused[cid]["rrf"] += 1 / (k + rank + 1)

    for rank, row in enumerate(keyword_results):
        cid = row[0]
        fused.setdefault(cid, {"row": row, "rrf": 0.0})
        fused[cid]["rrf"] += 1 / (k + rank + 1)

    results = []
    for v in fused.values():
        r = list(v["row"])
        r[4] = v["rrf"]     
        results.append(tuple(r))

    return sorted(results, key=lambda x: x[4], reverse=True)

# # ============================================================
# # RERANKING 
# # ============================================================
# def apply_advanced_reranking(query, rows, top_k=7, threshold=0.15):
#     if not rows:
#         return []

#     pairs = [[query, r[3]] for r in rows]
#     logits = reranker_model.predict(pairs)

#     RRF_CAP = 0.15  # empirical upper bound

#     query_sec = None
#     m = re.search(r"Sec(?:tion)?\.?\s*(\d+[A-Z]*(?:\(\d+\))?)", query, re.I)
#     if m:
#         query_sec = m.group(1)

#     final = []

#     for i, row in enumerate(rows):
#         rerank_prob = sigmoid(logits[i])  # [0,1]

#         rrf_score = row[4]
#         rrf_norm = min(rrf_score / RRF_CAP, 1.0)

#      
#         # score = 0.85 * rerank_prob + 0.15 * rrf_norm
#         score = rerank_prob

#         # Metadata boost
#         chunk_sec = str(row[2]).strip().lower() if row[2] else ""
#         if query_sec and query_sec == chunk_sec:
#             score += 0.15

#         # if score < threshold:
#         #     continue

#         r = list(row)
#         r[4] = score
#         final.append(tuple(r))

#     final.sort(key=lambda x: x[4], reverse=True)
#     return final[:top_k]
def apply_advanced_reranking(query, rows, top_k=7):
    if not rows:
        return []

    pairs = [[query, r[3]] for r in rows]
    logits = reranker_model.predict(pairs)

    final = []
    for i, row in enumerate(rows):
        r = list(row)
        r[4] = float(logits[i])   
        final.append(tuple(r))

    final.sort(key=lambda x: x[4], reverse=True)
    return final[:top_k]

def collapse_by_section(rows):
    section_map = {}
    for r in rows:
        sec = r[2]
        if not sec:
            continue
        if sec not in section_map:
            section_map[sec] = {
                "row": r,
                "best_score": r[4]
            }
        else:
            section_map[sec]["best_score"] = max(
                section_map[sec]["best_score"],
                r[4]
            )

    collapsed = []
    for v in section_map.values():
        r = list(v["row"])
        r[4] = v["best_score"]
        collapsed.append(tuple(r))

    return sorted(collapsed, key=lambda x: x[4], reverse=True)


# ============================================================
# RETRIEVE CONTEXT
# ============================================================
def retrieve_context(query, mode="hybrid", use_reranker=True, final_k=7):
    fetch_k = 10 if use_reranker else final_k
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        emb = embed_model.get_text_embedding(query)

        if mode == "vector":
            rows = run_vector_search(cur, emb, fetch_k)
        else:
            vec = run_vector_search(cur, emb, fetch_k)
            kw = run_keyword_search(cur, query, fetch_k)
            rows = perform_hybrid_fusion(vec, kw)

        if use_reranker:
            rows = apply_advanced_reranking(query, rows, 7)
        else:
            rows = rows[:final_k]
        
        rows = rows[:final_k]

        return rows

    finally:
        cur.close()
        conn.close()

# ============================================================
# QUERY OPTIMIZER 
# ============================================================


def generate_optimized_query(original_question: str) -> str:
    """
    Transforms a user question into a keyword-rich legal search query.
    """
    prompt = f"""
You are a query-optimization module for a Retrieval-Augmented Generation (RAG) system
operating on statutory legal texts under income-tax law.

Task:
Given a short, generic user question, rewrite it into a retrieval-optimized query
to maximize recall for:
- dense vector (bi-encoder) retrieval
- keyword / BM25 retrieval

Rules:
1. Do NOT answer the question.
2. Do NOT cite section numbers explicitly unless semantically intrinsic
   (e.g., search and seizure, faceless assessment).
3. Expand using statutory terminology:
   legal powers, rights, conditions, procedures, limits, authorities.
4. Prefer noun phrases and legal concepts over conversational language.
5. Do NOT include definitions, examples, or conclusions.
6. Assume the corpus is hierarchical statutory text with sections and sub-sections.
7. Length limit: maximum 70 tokens.

Output:
Return ONLY the optimized query text. No explanations. No formatting.

Example 1:
Input Question:
Can an assessment order be appealed?

Optimized Query:
Right of an assessee to appeal against orders of the Assessing Officer, types of
appealable orders, prescribed appellate authorities, and statutory time limits
for filing appeals under income-tax law.

Example 2:
Input Question:
How are lottery winnings taxed?

Optimized Query:
Tax treatment of winnings from lotteries and prize-based games, classification
as income from other sources, applicable special tax rates, withholding
requirements, and restrictions on deductions under income-tax law.


Input Question:
{original_question}

Optimize this question:

"""
    response = llm_optimizer.complete(prompt)
    
    return response.text.strip().replace('"', '')


def format_final_answer(raw_answer, user_question):
    prompt = f"""
You are a statutory question answering system for the Income-tax Act, 2025.

Answer STRICTLY in the following format and no other:

Direct Answer: <1-2> factual sentences derived only from the provided context.>

Key Provisions (Mention sections here):
- Section X: <single clause-level fact>
- Section Y: <single clause-level fact>

Rules:
- Use ONLY the provided statutory content
- Use the term "tax year", never "assessment year" or "previous year"
- Do NOT add explanations, examples, confidence, or reasoning
- Do NOT mention retrieval, scores, or AI behavior
- Cite ONLY sections that appear verbatim in the provided statutory content
- If the answer is not explicitly found in the context, write exactly:
Direct Answer: Information not found.

Key Provisions:
- None.

QUESTION:
{user_question}

RAW STATUTORY CONTENT:
{raw_answer}

Return ONLY the formatted answer.
"""
    return llm_answer.complete(prompt).text.strip()


def ask_tax_question(question, mode="hybrid", use_reranker=True):
    print(f"\n❓ {question}")

    #Query optimization
    search_query = generate_optimized_query(question)
    print(f"🔍 Optimized Query: {search_query}")

    #Retrieval 
    rows = retrieve_context(
        search_query,
        mode=mode,
        use_reranker=use_reranker,
        final_k=7
    )

    if not rows:
        print("\nFinal Answer:")
        print("Information not found in the provided legal text.")
        return

    # Context assembly
    context = ""
    for r in rows:
        context += f"""
--- CONTEXT ---
Section {r[2]} - {r[1]}
{r[3]}
"""

    top_score = rows[0][4]

   
    raw_prompt = f"""
Answer strictly from the context below.
If the answer is not explicitly present, say "Information not found".

CONTEXT:
{context}

QUESTION:
{question}
"""
    raw_answer = llm_reasoning.complete(raw_prompt).text

    #Formatting
    final_answer = format_final_answer(raw_answer, question)

    print("\nFinal Answer:\n")
    print(final_answer)
    return final_answer

# ============================================================
if __name__ == "__main__":
    ask_tax_question("What is the meaning of assessment year?", mode="hybrid", use_reranker=True)
