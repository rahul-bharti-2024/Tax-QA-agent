# import os
# import psycopg2
# from dotenv import load_dotenv
# from llama_index.llms.gemini import Gemini
# from llama_index.embeddings.huggingface import HuggingFaceEmbedding
# from sentence_transformers import CrossEncoder # <--- NEW IMPORT
# from urllib.parse import urlparse
# import re
# import math

# # 1. Load Environment Variables
# load_dotenv()

# def sigmoid(x):
#     return 1 / (1 + math.exp(-x))

# if not os.getenv("GOOGLE_API_KEY"):
#     raise ValueError("❌ GOOGLE_API_KEY not found in .env")

# # 2. Initialize Models
# print("Loading gemma-3-27b-it...")
# llm = Gemini(model="models/gemma-3-27b-it") 

# print("Loading Embedding Model...")
# embed_model = HuggingFaceEmbedding(model_name="BAAI/bge-base-en-v1.5")

# # --- 3. LOAD RERANKER (NEW) ---
# print("Loading Reranker Model (BAAI/bge-reranker-base)...")
# # usage: reranker.predict([['query', 'doc1'], ['query', 'doc2']])
# reranker_model = CrossEncoder('BAAI/bge-reranker-base') 

# def get_db_connection():
#     db_url = os.getenv("DATABASE_URL2")
#     if db_url:
#         result = urlparse(db_url)
#         return psycopg2.connect(
#             dbname=result.path[1:], user=result.username,
#             password=result.password, host=result.hostname, port=result.port
#         )
#     return psycopg2.connect(
#         dbname=os.getenv("DB_NAME", "taxrag"),
#         user=os.getenv("DB_USER", "taxuser"),
#         password=os.getenv("DB_PASSWORD", "password"),
#         host=os.getenv("DB_HOST", "localhost"),
#         port=int(os.getenv("DB_PORT", 5432))
#     )

# # --- RETRIEVAL LOGIC ---
# def run_vector_search(cursor, query_embedding, limit=10):
#     cursor.execute("""
#         SELECT c.chunk_id, s.heading, s.section_number, c.text,
#         1 - (c.embedding <=> %s::vector) as similarity
#         FROM chunks c
#         LEFT JOIN sections s ON c.section_id = s.section_id
#         ORDER BY c.embedding <=> %s::vector
#         LIMIT %s;
#     """, (query_embedding, query_embedding, limit))
#     return cursor.fetchall()

# def run_keyword_search(cursor, query_text, limit=10):
#     cursor.execute("""
#         SELECT c.chunk_id, s.heading, s.section_number, c.text,
#         ts_rank_cd(c.text_search, websearch_to_tsquery('english', %s)) as score
#         FROM chunks c
#         LEFT JOIN sections s ON c.section_id = s.section_id
#         WHERE c.text_search @@ websearch_to_tsquery('english', %s)
#         ORDER BY score DESC
#         LIMIT %s;
#     """, (query_text, query_text, limit))
#     return cursor.fetchall()

# def perform_hybrid_fusion(vector_results, keyword_results, k=10):
#     fused_scores = {}
#     for rank, row in enumerate(vector_results):
#         chunk_id = row[0]
#         if chunk_id not in fused_scores: fused_scores[chunk_id] = {"row": row, "score": 0}
#         fused_scores[chunk_id]["score"] += 1.0 / (k + rank + 1)
        
#     for rank, row in enumerate(keyword_results):
#         chunk_id = row[0]
#         if chunk_id not in fused_scores: fused_scores[chunk_id] = {"row": row, "score": 0}
#         fused_scores[chunk_id]["score"] += 1.0 * (1 / (k + rank + 1)) 
    
#     sorted_results = sorted(fused_scores.values(), key=lambda x: x["score"], reverse=True)
#     final_rows = []
#     for item in sorted_results:
#         row = list(item["row"])
#         row[4] = item["score"]  # overwrite score with fused RRF score
#         final_rows.append(tuple(row))

#     return final_rows

# # def apply_advanced_reranking(query, initial_chunks, top_k=7, threshold=0.30):
# #     """
# #     Applies Cross-Encoder scoring + Metadata Boosting + Weighted Combination.
# #     Filters out chunks below 'threshold'.
# #     """
# #     if not initial_chunks:
# #         return []
        
# #     # 1. Prepare pairs for Cross-Encoder
# #     # row: (chunk_id, heading, sec_num, text, vector_score)
# #     pairs = [[query, row[3]] for row in initial_chunks]
    
# #     # 2. Get Raw Logits (e.g., -5.2, +3.1)
# #     raw_scores = reranker_model.predict(pairs)
    
# #     # 3. Extract Section Number from Query for Metadata Boosting
# #     # Regex looks for "Section 123" or "Sec 123"
# #     query_sec_match = re.search(r"Sec(?:tion)?\.?\s*(\d+[A-Z]?(?:\(\d+\))?)"
# # , query, re.IGNORECASE)
# #     target_section = query_sec_match.group(1) if query_sec_match else None
    
# #     final_results = []
    
# #     for i, row in enumerate(initial_chunks):
# #         # A. Normalize Reranker Score (Logit -> 0-1 Probability)
# #         rerank_prob = sigmoid(raw_scores[i])
        
# #         # B. Get Initial Vector Score (Assume it's 0-1 from Cosine Similarity)
# #         # Note: If using Hybrid RRF, this might be a rank score. 
# #         # We'll treat it as a weak signal compared to Reranker.
# #         vector_score = row[4] 
        
# #         # C. Calculate Weighted Score
# #         # 80% weight to Reranker (it's smarter), 20% to Vector (stability)
# #         # You can tune these weights!
# #         # norm_vec = (vector_score + 1) / 2
# #         weighted_score = rerank_prob 

        
# #         # D. Apply Metadata Bonus
# #         # If query asks for "Section 80C" and chunk is "Section 80C", BOOST IT!
# #         chunk_sec = str(row[2]) if row[2] else ""
# #         if target_section and target_section == chunk_sec:
# #             # print(f"   🚀 Bonus applied for Section {target_section} match!")
# #             weighted_score += 0.15
            
# #         # E. Threshold Filtering (The "Garbage Check")
# #         if weighted_score < threshold:
# #             continue
            
# #         # Create new tuple with updated score
# #         new_row = list(row)
# #         new_row[4] = weighted_score
# #         final_results.append(tuple(new_row))
        
# #     # 4. Sort by Final Weighted Score
# #     final_results.sort(key=lambda x: x[4], reverse=True)
    
# #     return final_results[:top_k]
# def apply_advanced_reranking(query, initial_chunks, top_k=7, threshold=0.15): # Lowered threshold slightly
#     if not initial_chunks:
#         return []
        
#     pairs = [[query, row[3]] for row in initial_chunks]
#     raw_scores = reranker_model.predict(pairs)
    
#     # Regex for metadata boosting
#     query_sec_match = re.search(r"Sec(?:tion)?\.?\s*(\d+[A-Z]*(?:\(\d+\))?)", query, re.IGNORECASE)
#     target_section = query_sec_match.group(1) if query_sec_match else None
    
#     final_results = []
    
#     for i, row in enumerate(initial_chunks):
#         rerank_prob = sigmoid(raw_scores[i])
        
#         # Base score is just the Reranker Probability
#         weighted_score = rerank_prob 
        
#         # Metadata Boost
#         chunk_sec = str(row[2]) if row[2] else ""
#         if target_section and target_section.strip().lower() == chunk_sec.lower():
#             weighted_score += 0.15 # Stronger boost for explicit section match
            
#         if weighted_score < threshold:#should i do a return 
#             continue
            
#         new_row = list(row)
#         new_row[4] = weighted_score
#         final_results.append(tuple(new_row))
        
#     final_results.sort(key=lambda x: x[4], reverse=True)
#     return final_results[:top_k]



# def requires_governing_section(question: str) -> bool:
#     keywords = ["taxable", "exempt", "included", "excluded", "chargeable"]
#     return any(k in question.lower() for k in keywords)

# def has_governing_section(rows):
#     for r in rows:
#         heading = (r[1] or "").lower()
#         if "not included in total income" in heading:
#             return True
#         if "charge of income-tax" in heading:
#             return True
#     return False

# def is_definition_query(q: str) -> bool:
#     return any(k in q.lower() for k in ["meaning", "define", "definition", "what is"])


# # --- UPDATED RETRIEVAL FUNCTION ---
# def retrieve_context(query_text, mode="vector", use_reranker=False, final_k=7):
#     # Fetch wider pool for reranking (e.g., 50 candidates)
#     fetch_k = 50 if use_reranker else final_k
    
#     conn = get_db_connection()
#     cursor = conn.cursor()
#     candidates = []
    
#     try:
#         if mode == "vector":
#             query_embedding = embed_model.get_text_embedding(query_text)
#             candidates = run_vector_search(cursor, query_embedding, limit=fetch_k)
#         elif mode == "hybrid":
#             query_embedding = embed_model.get_text_embedding(query_text)
#             vec_rows = run_vector_search(cursor, query_embedding, limit=fetch_k)
#             kw_rows = run_keyword_search(cursor, query_text, limit=fetch_k)
#             candidates = perform_hybrid_fusion(vec_rows, kw_rows)[:fetch_k]
            
#         # --- APPLY ADVANCED RERANKING ---
#         if use_reranker and candidates:
#             final_results = apply_advanced_reranking(
#                 query_text, 
#                 candidates, 
#                 top_k=final_k, 
#                 threshold=0.30 # <--- TUNABLE THRESHOLD
#             )
            
#             if not final_results:
#                 print("⚠️  Warning: Reranker dropped ALL chunks below threshold.")
#         else:
#             final_results = candidates[:final_k]
            
#     except Exception as e:
#         print(f"❌ Retrieval Error: {e}")
#         final_results = []
#     finally:
#         cursor.close()
#         conn.close()
        
#     return final_results

# # --- STEP 1: QUERY OPTIMIZER (Unchanged) ---
# # def generate_optimized_query(original_question):
# #     prompt = f"""
# #     You are a search query optimizer for an Indian Tax Law database.
# #     1. **Terminology Mapping:**
# #        - "Assessment Year" -> MUST become "Tax Year"
# #        - "Previous Year" -> MUST become "Financial Year"
# #     2. **Preservation:**
# #        - Keep legal terms like "Block of Assets", "Person" EXACTLY as they are.
# #     3. **Enhancement:**
# #        - If user asks for definition, add "meaning", "includes".
# #     User Question: "{original_question}"
# #     Output ONLY the optimized search string.
# #     """
# #     response = llm.complete(prompt)
# #     return response.text.strip().replace('"', '')
# def generate_optimized_query(original_question):
#     """
#     Transforms a user question into a keyword-rich legal search query.
#     """
#     prompt = f"""
#     You are an expert Legal Query Optimizer for the Indian Income Tax Bill, 2025.
#     Your task is to translate the User's "Layman Question" into a precise "Legal Search Query" that will match the statute text.

#     ### 1. TERMINOLOGY MAPPING (CRITICAL)
#     - "Assessment Year" -> MUST become "Tax Year"
#     - "Previous Year" -> MUST become "Financial Year"
#     - "Filing" -> "Furnishing of Return"
#     - "ITR" -> "Return of Income"

#     ### 2. CONCEPT EXPANSION (Add these specific keywords)
#     - **Salary/Pay/Wage:** Add "Income under Head Salaries" AND "Section 15" AND "Deductions Section 19".
#     - **House/Rent/Property:** Add "Income from House Property" AND "Annual Value Section 21".
#     - **Business/Profit/Freelance:** Add "Profits and gains of business or profession" AND "Section 26".
#     - **Capital Gains/Selling Asset/Shares:** Add "Capital Gains" AND "Transfer of Capital Asset" AND "Section 43".
#     - **Deductions/80C:** Add "Deductions from gross total income" AND "Chapter VI-A".
#     - **Exempt/Tax Free:** Add "Incomes not included in total income" AND "Section 11".
#     - **Residency/NRI:** Add "Residence in India Section 6" AND "Deemed Resident Section 26".
#     - **TDS:** Add "Deduction of tax at source".

#     ### 3. OUTPUT FORMAT
#     - Output ONLY the optimized query string. No explanations.
#     - The query should look like: [Original Keywords] + [Legal Terms] + [Section Numbers]

#     ### EXAMPLES
#     User: "How to calculate tax on my salary?"
#     Optimized: "Computation of income under Head Salaries Section 15 deductions Section 19"

#     User: "Is agricultural income taxable?"
#     Optimized: "Agricultural income not included in total income exemption Section 11"

#     User: "What is the penalty for late filing?"
#     Optimized: "Penalty for default in furnishing return of income Section 263"

#     ### INPUT
#     User: "{original_question}"
#     Optimized:
#     """
    
#     # Use a low temperature for deterministic output
#     response = llm.complete(prompt) 
#     return response.text.strip().replace('"', '')



# # --- STEP 3: FORMATTER (Unchanged) ---
# def format_final_answer(raw_answer, user_question, top_retrieval_score):
#     formatting_prompt = f"""
#     You are a professional legal editor. Your job is to restructure the raw answer below into a strict, standardized format.
    
#     **USER QUESTION:** {user_question}
#     **RAW ANSWER:** {raw_answer}
#     **RETRIEVAL STRENGTH:** {top_retrieval_score:.2f}

#     --------------------------------------------------
#     **MANDATORY OUTPUT TEMPLATE:**
    
#     ### Direct Answer
#     [Provide a direct 1-2 sentence summary of the answer here. No fluff.]

#     ### Key Details
#     * **[Concept 1]:** [Explanation] [Section Citation]
#     * **[Concept 2]:** [Explanation] [Section Citation]
#     * **[Concept 3]:** [Explanation] [Section Citation]

#     ### Exceptions / Notes (If applicable)
#     * [List any specific conditions, exceptions, or important definitions here]
    
#     ---
#     **Confidence Score:** [Label] ([Score]%)
#     **Reasoning:** [1 sentence explaining why]
#     --------------------------------------------------

#     **RULES FOR FILLING THE TEMPLATE:**
#     1. **Direct Answer:** Must be a direct "Yes", "No", or summary statement.
#     2. **Key Details:** MUST use bullet points. BOLD the key term at the start of the bullet.
#     3. **Exceptions:** If there are no exceptions, write "None identified in context."
#     4. **Confidence Logic:**
#        - High (>=80%): Exact definition or clear section found.
#        - Medium (50-79%): Good context but requires inference.
#        - Low (<50%): Answer is "I cannot find this".
#     5. **Safety:** If the raw answer says "I cannot find this," the Direct Answer must be "Information not found in the provided legal text." and Confidence MUST be Low.

#     Output ONLY the filled template.
#     """
#     response = llm.complete(formatting_prompt)
#     return response.text.strip()




# def ask_tax_question(question, mode="hybrid", use_reranker=True):
#     needs_governing = requires_governing_section(question)

#     print(f"\n❓ User Question: {question}")
    
#     rerank_status = "ON (Top 50->7)" if use_reranker else "OFF"
#     print(f"⚙️  Pipeline: {mode.upper()} Search | Reranker: {rerank_status}")
    
#     # --- STEP 1: QUERY OPTIMIZATION ---
#     print("🧠 Preparing search query...")
#     # Modified: Use optimization more liberally, not just for definitions
#     # This helps map "Assessment Year" -> "Tax Year" during retrieval too
#     # search_query = generate_optimized_query(question) if is_definition_query(question) else question
#     search_query = generate_optimized_query(question)
#     print(f"   -> Using query: '{search_query}'")
    
#     print(f"🔍 Retrieving context...")
    
#     rows = retrieve_context(
#         search_query,
#         mode=mode,
#         use_reranker=use_reranker,
#         final_k=7
#     )
    
#     if not rows:
#         print("❌ No relevant context found in database.")
#         print("\n📝 Final Answer:")
#         print("Information not found in the provided legal text (No chunks retrieved).")
#         return

#     # --- DEBUG OUTPUT ---
#     # Get the top score (Reranker score if ON, else Hybrid score)
#     top_score = rows[0][4] if (rows and len(rows[0]) > 4) else 0.0

#     print("\n🧐 DEBUG: Best Chunks:")
#     for i, r in enumerate(rows):
#         sec_num = r[2]
#         heading = r[1] or "Introduction"
#         text_preview = r[3][:80].replace("\n", " ") + "..."
#         score_display = f"{r[4]:.4f}"
        
#         display_ref = f"Section {sec_num}" if sec_num else heading
#         print(f"   [{i+1}] {display_ref} (Score: {score_display}): {text_preview}")
#     print("-" * 50)

#     # --- FIX 1: SOFT GOVERNING WARNING (Instead of Hard Stop) ---
#     governing_warning = ""
#     if requires_governing_section(question) and not has_governing_section(rows):
#         print("⚠️  Governing section not explicit — answering from available context.")
#         governing_warning = (
#             "WARNING: The specific 'charging' or 'exemption' section (Sec 4 or 10/11) "
#             "was not explicitly retrieved. Answer carefully based ONLY on the provided chunks. "
#             "Do not assume taxability if the section is missing."
#         )

#     # --- FIX 2: LOW CONFIDENCE WARNING ---
#     confidence_instruction = ""
#     if top_score < 0.35: # Threshold for "Wait, is this even relevant?"
#         print("⚠️  Low Retrieval Score detected. Instructing LLM to be strict.")
#         confidence_instruction = (
#             "WARNING: The retrieved context has low relevance scores. "
#             "If the text does NOT explicitly answer the user's question, "
#             "you MUST state 'Information not found'. Do not guess."
#         )

#     # --- CONTEXT ASSEMBLY ---
#     context_str = ""
#     for r in rows:
#         heading = r[1] or "Introduction"
#         sec_num = r[2]
#         text = r[3]
#         citation = f"Section {sec_num} - {heading}" if sec_num else f"Section: {heading}"
        
#         context_str += f"""
# --- START CONTEXT BLOCK ---
# {citation}
# Content:
# {text}
# --- END CONTEXT BLOCK ---
# """

#     # --- RAW ANSWER GENERATION ---
#     print("🤖 Generating raw legal answer...")
    
#     raw_system_prompt = (
#         "You are an expert Indian Tax Consultant AI. "
#         "Your goal is to extract the correct legal answer strictly from the provided context."
#     )
    
#     raw_user_prompt = f"""
# ### CONTEXT INFORMATION:
# {context_str}

# ### CRITICAL RULES FOR ANSWERING:
# 1. **TERMINOLOGY OVERRIDE (MANDATORY):**
#    - 'Tax Year' = 'Assessment Year'
#    - 'Financial Year' = 'Previous Year'

# 2. **STRICT GROUNDING:**
#    - Answer ONLY based on the provided context blocks.
#    - {governing_warning}
#    - {confidence_instruction}

# 3. **CITATION:**
#    - Cite Section Numbers [Section X] or Headers.

# ### USER QUESTION:
# {question}
# """

#     try:
#         raw_response = llm.complete(raw_system_prompt + "\n\n" + raw_user_prompt)
#         raw_answer_text = raw_response.text
        
#         print("✨ Polishing answer...")
#         # Pass the top_score to the formatter so it can auto-label "Low Confidence"
#         final_answer = format_final_answer(raw_answer_text, question, top_score)
        
#         print("\n📝 Final Answer:")
#         print(final_answer)
        
#     except Exception as e:
#         print(f"\n❌ LLM Error: {e}")

# if __name__ == "__main__":
#     # Example: Hybrid Search + Reranker ON
#     ask_tax_question("What is the meaning of assessment year?", mode="hybrid", use_reranker=True)