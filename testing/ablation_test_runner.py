
import json
import time
import os
import sys
import re
import math
from collections import defaultdict

# --- Setup Paths and Imports ---
current_dir = os.path.dirname(os.path.abspath(__file__))
app_dir = os.path.join(current_dir, '..', 'app')
sys.path.append(app_dir)

try:
    from rag_app import (
        ask_tax_question, 
        initialize_models, 
        get_embed_model,
        get_llm 
    )
    # Import Gemini class to instantiate the separate Judge model
    from llama_index.llms.gemini import Gemini 
except ImportError as e:
    print(f"❌ Error: {e}")
    sys.exit(1)

# --- Configuration ---
GOLDEN_SET_PATH = os.path.join(current_dir, '..', 'data', 'golden_test_set.json')
RESULTS_FILE = os.path.join(current_dir, '..', 'ablation_results.json')

TEST_MODES = {
    "A_Vector_Only": {"mode": "vector", "use_reranker": False},
    "B_Hybrid_Only": {"mode": "hybrid", "use_reranker": False},
    "C_Vector_Rerank": {"mode": "vector", "use_reranker": True},
    "D_Hybrid_Rerank": {"mode": "hybrid", "use_reranker": True},
}

# --- Helper: Math for Cosine Similarity ---
def cosine_similarity(v1, v2):
    if not v1 or not v2: return 0.0
    dot_product = sum(a * b for a, b in zip(v1, v2))
    magnitude1 = math.sqrt(sum(a * a for a in v1))
    magnitude2 = math.sqrt(sum(b * b for b in v2))
    if magnitude1 == 0 or magnitude2 == 0: return 0.0
    return dot_product / (magnitude1 * magnitude2)

# --- Metric 1 & 2: Retrieval (MRR & Recall) via LLM Judge ---
def calculate_retrieval_metrics_llm(llm_judge, golden_sections, retrieved_rows):
    if not retrieved_rows: return 0.0, 0.0

    retrieved_summary = ""
    for i, row in enumerate(retrieved_rows):
        retrieved_summary += f"Rank {i+1}: [Section {row[2]}] {row[3][:200]}...\n"

    # We ask the LLM specifically to check ONLY the golden sections
    prompt = f"""
    You are a strict data evaluator.
    
    TARGET SECTIONS: {golden_sections}
    RETRIEVED CONTENT:
    {retrieved_summary}
    
    TASK: For EACH "Target Section" listed above, determine its Rank (1-7) in the "Retrieved Content". 
    If a section is NOT found, rank is 0.
    
    OUTPUT: A JSON object with EXACTLY the keys from TARGET SECTIONS.
    Example: {{"3": 1, "6(2)": 0}}
    """
    
    try:
        response = llm_judge.complete(prompt)
        cleaned_text = response.text.replace("```json", "").replace("```", "").strip()
        matches = json.loads(cleaned_text)
        
        found_count = 0
        first_match_rank = float('inf')
        
        # --- CRITICAL FIX: Iterate over GOLDEN SECTIONS, not the LLM output ---
        # This prevents counting hallucinated or extra sections.
        for needed_sec in golden_sections:
            # We normalize keys slightly to ensure matching (strings vs ints)
            # Check if the needed section exists in the LLM's output keys
            rank = 0
            
            # Simple fuzzy lookup in case LLM changed casing or spacing
            for key, val in matches.items():
                if str(needed_sec).strip() == str(key).strip():
                    rank = val
                    break
            
            if rank > 0:
                found_count += 1
                if rank < first_match_rank:
                    first_match_rank = rank
        
        # Now Recall is mathematically bounded [0, 1]
        recall = found_count / len(golden_sections) if golden_sections else 0.0
        mrr = 1.0 / first_match_rank if first_match_rank != float('inf') else 0.0
        
        return recall, mrr

    except Exception as e:
        print(f"   ⚠️ Judge Error (Retrieval): {e}")
        return 0.0, 0.0

# --- Metric 3: Groundedness via LLM Judge ---
def calculate_groundedness_llm(llm_judge, rag_answer, retrieved_rows):
    if not retrieved_rows: return 0.0
    context_text = "\n".join([r[3] for r in retrieved_rows])
    
    prompt = f"""
    Rate the Groundedness (0.0 to 1.0) of the Answer based ONLY on Context.
    OUTPUT ONLY THE FLOAT.
    
    CONTEXT: {context_text[:7500]}
    ANSWER: {rag_answer}
    """
    try:
        response = llm_judge.complete(prompt)
        match = re.search(r"(\d+(\.\d+)?)", response.text)
        return float(match.group(1)) if match else 0.0
    except:
        return 0.0

# --- Metric 4: Completeness (Semantic Similarity) ---
def calculate_completeness(rag_answer, ground_truth, embed_model_obj):
    if not rag_answer or not ground_truth: return 0.0
    try:
        embeddings = embed_model_obj.get_text_embedding_batch([rag_answer, ground_truth])
        return cosine_similarity(embeddings[0], embeddings[1])
    except Exception as e:
        print(f"   ⚠️ Embedding Error: {e}")
        return 0.0

def run_ablation_test():
    print("Pre-initializing Models...")
    initialize_models() 
    global_embed_model = get_embed_model()
    
    # --- CRITICAL: Using Gemma 12B IT as the Judge ---
    print("Loading Judge Model (Gemma 3 12B IT)...")
    try:
        judge_llm = Gemini(model="models/gemma-3-12b-it") # <--- CHANGED MODEL HERE
    except Exception as e:
        print(f"❌ Failed to load Judge Model: {e}")
        return
        
    print("✅ Models Ready.")

    if not os.path.exists(GOLDEN_SET_PATH):
        print(f"❌ Error: Golden Set not found at {GOLDEN_SET_PATH}")
        return

    with open(GOLDEN_SET_PATH, 'r') as f:
        golden_set = json.load(f)
    golden_set = golden_set[::2]
    all_results = defaultdict(lambda: defaultdict(list))
    total_queries = len(golden_set)

    for mode_name, config in TEST_MODES.items():
        print(f"\n=== MODE: {mode_name} ===")
        
        mode_results = {"recall": [], "mrr": [], "groundedness": [], "completeness": [], "time": []}
        successful = 0
        
        for i, gold_query in enumerate(golden_set):
            query = gold_query['Query']
            required_sections = gold_query['Required_Sections']
            ground_truth = gold_query['Answer']
            
            print(f"[{i+1}/{total_queries}] Q{gold_query['Query_ID']}...", end="", flush=True)
            start_time = time.time()
            
            try:
                # 1. GENERATE (Using the main Gemma 27B model via rag_app)
                final_answer, retrieved_rows = ask_tax_question(
                    query, 
                    mode=config["mode"], 
                    use_reranker=config["use_reranker"],
                    return_raw_results=True 
                )
                
                duration = time.time() - start_time
                
                # 2. EVALUATE (Using the 12B Judge model)
                if retrieved_rows:
                    recall, mrr = calculate_retrieval_metrics_llm(judge_llm, required_sections, retrieved_rows)
                    groundedness = calculate_groundedness_llm(judge_llm, final_answer, retrieved_rows)
                    completeness = calculate_completeness(final_answer, ground_truth, global_embed_model)
                    
                    mode_results["recall"].append(recall)
                    mode_results["mrr"].append(mrr)
                    mode_results["groundedness"].append(groundedness)
                    mode_results["completeness"].append(completeness)
                    mode_results["time"].append(duration)
                    successful += 1
                    
                    print(f" ✅ Rec:{recall:.2f} MRR:{mrr:.2f} Gnd:{groundedness:.1f} Sim:{completeness:.2f} ({duration:.1f}s)")
                else:
                    print(" ⚠️ No context.")

                # --- CRITICAL: Rate Limit Safety Buffer ---
                # Increased to 15s because we are hitting the API heavily
                time.sleep(30) 

            except Exception as e:
                print(f" 🚨 Error: {e}")
                time.sleep(25) # Longer sleep on error to let quota recover

        # Stats for this Mode
        if successful > 0:
            avg_results = {k: sum(v)/successful for k, v in mode_results.items()}
            print(f"\n--- {mode_name} AVERAGES ---")
            print(f"Recall: {avg_results['recall']:.2f}")
            print(f"MRR:    {avg_results['mrr']:.2f}")
            print(f"Gnd:    {avg_results['groundedness']:.2f}")
            print(f"Sim:    {avg_results['completeness']:.2f}")
            
            all_results[mode_name] = avg_results
            with open(RESULTS_FILE, 'w') as f:
                json.dump(all_results, f, indent=4)

if __name__ == "__main__":
    run_ablation_test()