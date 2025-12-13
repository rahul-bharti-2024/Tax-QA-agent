
import os
import psycopg2
from dotenv import load_dotenv
from llama_index.llms.gemini import Gemini
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from sentence_transformers import CrossEncoder 
from urllib.parse import urlparse
import re
import math

# --- GLOBAL VARIABLES (CRITICAL FOR LAZY LOADING) ---
# Declare model variables globally, but initialize them to None.
llm = None
embed_model = None
reranker_model = None

# --- HELPER FUNCTIONS ---
def sigmoid(x):
    return 1 / (1 + math.exp(-x))

def initialize_models():
    """Initializes LLM, Embedding, and Reranker models lazily on first call."""
    global llm, embed_model, reranker_model

    if llm and embed_model and reranker_model:
        return # Already loaded

    load_dotenv()
    if not os.getenv("GOOGLE_API_KEY"):
        raise ValueError("❌ GOOGLE_API_KEY not found in .env")

    print("Loading gemma-3-27b-it...")
    llm = Gemini(model="models/gemma-3-27b-it") 

    print("Loading Embedding Model...")
    embed_model = HuggingFaceEmbedding(model_name="BAAI/bge-base-en-v1.5")

    print("Loading Reranker Model (BAAI/bge-reranker-base)...")
    reranker_model = CrossEncoder('BAAI/bge-reranker-base') 

# --- CRITICAL GETTER FOR ABLATION SCRIPT ---
# This function helps the ablation runner grab the initialized model without scope issues.
def get_embed_model():
    """Returns the currently initialized embedding model instance."""
    global embed_model
    if not embed_model:
        initialize_models()
    return embed_model
def get_llm():
    """Returns the currently initialized LLM instance."""
    global llm
    if not llm:
        initialize_models()
    return llm
# --- Connection and Retrieval Functions ---
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

def run_vector_search(cursor, query_embedding, limit=10):
    cursor.execute("""
        SELECT c.chunk_id, s.heading, s.section_number, c.text,
        1 - (c.embedding <=> %s::vector) as score
        FROM chunks c
        LEFT JOIN sections s ON c.section_id = s.section_id
        ORDER BY c.embedding <=> %s::vector
        LIMIT %s;
    """, (query_embedding, query_embedding, limit))
    return cursor.fetchall()

def run_keyword_search(cursor, query_text, limit=10):
    cursor.execute("""
        SELECT c.chunk_id, s.heading, s.section_number, c.text,
        ts_rank_cd(c.text_search, websearch_to_tsquery('english', %s)) as score
        FROM chunks c
        LEFT JOIN sections s ON c.section_id = s.section_id
        WHERE c.text_search @@ websearch_to_tsquery('english', %s)
        ORDER BY score DESC
        LIMIT %s;
    """, (query_text, query_text, limit))
    return cursor.fetchall()

def perform_hybrid_fusion(vector_results, keyword_results, k=10):
    fused_scores = {}
    for rank, row in enumerate(vector_results):
        chunk_id = row[0]
        if chunk_id not in fused_scores: fused_scores[chunk_id] = {"row": row, "score": 0}
        fused_scores[chunk_id]["score"] += 1.0 / (k + rank + 1)
        
    for rank, row in enumerate(keyword_results):
        chunk_id = row[0]
        if chunk_id not in fused_scores: fused_scores[chunk_id] = {"row": row, "score": 0}
        fused_scores[chunk_id]["score"] += 1.0 * (1 / (k + rank + 1)) 
    
    sorted_results = sorted(fused_scores.values(), key=lambda x: x["score"], reverse=True)
    return [item["row"] for item in sorted_results]

# --- RERANKING / SCORING LOGIC ---
def apply_advanced_reranking(query, initial_chunks, top_k=7, threshold=0.05):
    global reranker_model 
    if not initial_chunks:
        return []
        
    pairs = [[query, row[3]] for row in initial_chunks]
    raw_scores = reranker_model.predict(pairs)
    
    query_sec_match = re.search(r"Sec(?:tion)?\.?\s*(\d+[A-Z]?)", query, re.IGNORECASE)
    target_section = query_sec_match.group(1) if query_sec_match else None
    
    final_results = []
    
    for i, row in enumerate(initial_chunks):
        rerank_prob = sigmoid(raw_scores[i])
        vector_score = row[4] 
        
        norm_vec = (vector_score + 1) / 2
        weighted_score = 0.7 * rerank_prob + 0.3 * norm_vec
        
        chunk_sec = str(row[2]) if row[2] else ""
        if target_section and target_section == chunk_sec:
            weighted_score += 0.15
            
        if weighted_score < threshold:
            continue
            
        new_row = list(row)
        new_row[4] = weighted_score
        final_results.append(tuple(new_row))
        
    final_results.sort(key=lambda x: x[4], reverse=True)
    
    return final_results[:top_k]

def retrieve_context(query_text, mode="vector", use_reranker=False, final_k=7):
    global embed_model 
    fetch_k = 50 if use_reranker else final_k
    conn = get_db_connection()
    cursor = conn.cursor()
    candidates = []
    
    try:
        if mode == "vector":
            query_embedding = embed_model.get_text_embedding(query_text)
            candidates = run_vector_search(cursor, query_embedding, limit=fetch_k)
        elif mode == "hybrid":
            query_embedding = embed_model.get_text_embedding(query_text)
            vec_rows = run_vector_search(cursor, query_embedding, limit=fetch_k)
            kw_rows = run_keyword_search(cursor, query_text, limit=fetch_k)
            candidates = perform_hybrid_fusion(vec_rows, kw_rows)[:fetch_k]
            
        if use_reranker and candidates:
            final_results = apply_advanced_reranking(
                query_text, 
                candidates, 
                top_k=final_k, 
                threshold=0.05 
            )
            
            # NOTE: We skip printing the warning in test mode (return_raw_results=True)
            if not final_results:
                print("⚠️  Warning: Reranker dropped ALL chunks below threshold.")
        else:
            final_results = candidates[:final_k]
            
    except Exception as e:
        print(f"❌ Retrieval Error: {e}")
        final_results = []
    finally:
        cursor.close()
        conn.close()
        
    return final_results

# --- STEP 1: QUERY OPTIMIZER ---
def generate_optimized_query(original_question):
    global llm 
    prompt = f"""
    You are a search query optimizer for an Indian Tax Law database.
    1. **Terminology Mapping:**
       - "Assessment Year" -> MUST become "Tax Year"
       - "Previous Year" -> MUST become "Financial Year"
    2. **Preservation:**
       - Keep legal terms like "Block of Assets", "Person" EXACTLY as they are.
    3. **Enhancement:**
       - If user asks for definition, add "meaning", "includes".
    User Question: "{original_question}"
    Output ONLY the optimized search string.
    """
    response = llm.complete(prompt)
    return response.text.strip().replace('"', '')

# --- STEP 3: FORMATTER ---
def format_final_answer(raw_answer, user_question, top_retrieval_score):
    global llm 
    formatting_prompt = f"""
    You are a professional legal editor. Your job is to restructure the raw answer below into a strict, standardized format.
    
    **USER QUESTION:** {user_question}
    **RAW ANSWER:** {raw_answer}
    **RETRIEVAL STRENGTH:** {top_retrieval_score:.2f}

    --------------------------------------------------
    **MANDATORY OUTPUT TEMPLATE:**
    
    ### Direct Answer
    [Provide a direct 1-2 sentence summary of the answer here. No fluff.]

    ### Key Details
    * **[Concept 1]:** [Explanation] [Section Citation]
    * **[Concept 2]:** [Explanation] [Section Citation]
    * **[Concept 3]:** [Explanation] [Section Citation]

    ### Exceptions / Notes (If applicable)
    * [List any specific conditions, exceptions, or important definitions here]
    
    ---
    **Confidence Score:** [Label] ([Score]%)
    **Reasoning:** [1 sentence explaining why]
    --------------------------------------------------

    **RULES FOR FILLING THE TEMPLATE:**
    1. **Direct Answer:** Must be a direct "Yes", "No", or summary statement.
    2. **Key Details:** MUST use bullet points. BOLD the key term at the start of the bullet.
    3. **Exceptions:** If there are no exceptions, write "None identified in context."
    4. **Confidence Logic:**
       - High (>=80%): Exact definition or clear section found.
       - Medium (50-79%): Good context but requires inference.
       - Low (<50%): Answer is "I cannot find this".
    5. **Safety:** If the raw answer says "I cannot find this," the Direct Answer must be "Information not found in the provided legal text." and Confidence MUST be Low.

    Output ONLY the filled template.
    """
    response = llm.complete(formatting_prompt)
    return response.text.strip()

# --- MAIN QA LOGIC (MODIFIED FOR TESTING) ---
def ask_tax_question(question, mode="hybrid", use_reranker=True, return_raw_results=False): 
    
    # CRITICAL: Initialize models FIRST
    initialize_models()
    
    # Only print headers if not in testing mode
    if not return_raw_results:
        print(f"\n❓ User Question: {question}")
        rerank_status = "ON (Top 50->7)" if use_reranker else "OFF"
        print(f"⚙️  Pipeline: {mode.upper()} Search | Reranker: {rerank_status}")
    
    # --- STEP 1: Optimization ---
    if not return_raw_results: print("🧠 Optimizing query with Gemma...")
    search_query = generate_optimized_query(question)
    if not search_query: search_query = question
    if not return_raw_results: print(f"   -> Optimized Query: '{search_query}'")
    
    if not return_raw_results: print(f"🔍 Retrieving context...")
    
    rows = retrieve_context(search_query, mode=mode, use_reranker=use_reranker, final_k=7)
    
    # Handle No Context Found
    if not rows:
        if return_raw_results:
            return "Information not found in the provided legal text.", []
        else:
            print("❌ No relevant context found in database.")
            return

    # Extract Top Score
    top_score = rows[0][4] if rows and len(rows[0]) > 4 else 0.0

    # Only print debug chunks if not in testing mode
    if not return_raw_results:
        print("\n🧐 DEBUG: Best Chunks:")
        for i, r in enumerate(rows):
            sec_num = r[2]
            heading = r[1] or "Introduction"
            text_preview = r[3][:80].replace("\n", " ") + "..."
            score_display = f"{r[4]:.4f}"
            
            if sec_num and sec_num != "N/A":
                display_ref = f"Section {sec_num}"
            else:
                display_ref = heading
                
            print(f"   [{i+1}] {display_ref} (Score: {score_display}): {text_preview}")
        print("-" * 50)

    # Format Context
    context_str = ""
    for r in rows:
        heading = r[1] or "Introduction"
        sec_num = r[2]
        text = r[3]
        
        if sec_num and sec_num != "N/A":
            citation = f"Section {sec_num} - {heading}"
        else:
            citation = f"Section: {heading}"
            
        context_str += f"""
--- START CONTEXT BLOCK ---
{citation}
Content:
{text}
--- END CONTEXT BLOCK ---
"""

    # --- STEP 2: Raw Answer Generation ---
    if not return_raw_results: print("🤖 Generating raw legal answer...")
    
    raw_system_prompt = "You are an expert Indian Tax Consultant AI. Your goal is to extract the correct legal answer from the context."
    
    raw_user_prompt = f"""
### CONTEXT INFORMATION:
{context_str}

### CRITICAL RULES FOR ANSWERING:
1. **TERMINOLOGY OVERRIDE (MANDATORY):** - 'Tax Year' = 'Assessment Year'
   - 'Financial Year' = 'Previous Year'
   - IF context defines 'Tax Year', USE IT for 'Assessment Year'.

2. **DEFINITION EXTRACTION:**
   - If the text says "X includes A, B, C", accept that as the definition.

3. **CITATION:** - Cite Section Numbers [Section X] or Headers.

### USER QUESTION:
{question}
"""
    try:
        raw_response = llm.complete(raw_system_prompt + "\n\n" + raw_user_prompt)
        raw_answer_text = raw_response.text
        
        # --- STEP 3: Final Polish ---
        if not return_raw_results: print("✨ Polishing answer...")
        final_answer = format_final_answer(raw_answer_text, question, top_score)
        
        # --- RETURN LOGIC FOR TESTING ---
        if return_raw_results:
            return final_answer, rows # <--- CRITICAL RETURN FOR ABLATION SCRIPT
            
        # --- PRINT FINAL ANSWER (Original CLI behavior) ---
        print("\n📝 Final Answer:")
        print(final_answer)
        
    except Exception as e:
        if return_raw_results:
            return f"LLM Error: {e}", []
        else:
            print(f"\n❌ LLM Error: {e}")

if __name__ == "__main__":
    # Example: Hybrid Search + Reranker ON (CLI mode)
    # The default behavior is to print the result
    ask_tax_question("What is the meaning of assessment year?", mode="hybrid", use_reranker=True)
