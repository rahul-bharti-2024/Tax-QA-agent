import json
import re
from collections import defaultdict
from pathlib import Path
from tqdm import tqdm
import time
from google.api_core.exceptions import ResourceExhausted

# =========================
# CONFIG
# =========================
DEBUG = False
K = 7

# =========================
# SAFE LLM CALL
# =========================
def safe_complete(llm, prompt, base_sleep=3, max_retries=5):
    for attempt in range(max_retries):
        try:
            return llm.complete(prompt).text
        except ResourceExhausted:
            wait = base_sleep * (attempt + 1)
            print(f"⚠️ Rate limit hit. Sleeping {wait}s...")
            time.sleep(wait)
    raise RuntimeError("Gemini quota repeatedly exceeded")

# =========================
# PATHS
# =========================
BASE_DIR = Path(__file__).resolve().parent.parent
GOLDEN_PATH = BASE_DIR / "data" / "golden_set_3.json"

# =========================
# SECTION NORMALIZATION
# =========================
def normalize_section(section):
    """
    '15(1)(a)' -> '15'
    '263A(2)'  -> '263A'
    """
    if not section:
        return None
    m = re.match(r'^(\d+[A-Z]*)', str(section).strip())
    return m.group(1) if m else None

# =========================
# SECTION EXTRACTION
# =========================
SECTION_RE = re.compile(
    r"(?:Section\s*)?(\d+[A-Z]?(?:\(\d+\))?)",
    re.I
)

def extract_sections_from_answer(ans):
    return {
        normalize_section(s)
        for s in SECTION_RE.findall(ans or "")
        if normalize_section(s)
    }

def extract_sections_from_rows(rows):
    return {
        normalize_section(r[2])
        for r in rows
        if r[2] and normalize_section(r[2])
    }

# =========================
# IMPORT RAG
# =========================
from rag_app import (
    retrieve_context,
    generate_optimized_query,
    llm_reasoning,
    format_final_answer
)

# =========================
# METRICS
# =========================
def recall_at_k(retrieved, gold):
    return int(bool(retrieved & gold))

def mrr(retrieved, gold):
    for i, s in enumerate(retrieved):
        if s in gold:
            return 1.0 / (i + 1)
    return 0.0

def citation_metrics(pred, gold):
    if not pred:
        return 0.0, 0.0, 0.0
    tp = len(pred & gold)
    precision = tp / len(pred) if pred else 0.0
    recall = tp / len(gold) if gold else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return precision, recall, f1

def groundedness(answer_sections, retrieved_sections):
    if not answer_sections:
        return 0.0
    grounded = sum(1 for s in answer_sections if s in retrieved_sections)
    return grounded / len(answer_sections)

# =========================
# PIPELINE EVAL
# =========================
def evaluate_pipeline(name, config, golden_set):
    scores = defaultdict(list)
    per_query_logs = []

    for q in tqdm(golden_set, desc=f"{name} | Queries", leave=False):
        query = q["Query"]

        gold_sections = {
            normalize_section(s)
            for s in q["Required_Sections"]
            if normalize_section(s)
        }

        # ---- Retrieval ----
        search_query = generate_optimized_query(query)
        time.sleep(2)

        rows = retrieve_context(
            search_query,
            mode=config["mode"],
            use_reranker=config["use_reranker"],
            final_k=K
        )

        retrieved_sections = extract_sections_from_rows(rows)

        # ---- Retrieval metrics ----
        recall_hit = recall_at_k(retrieved_sections, gold_sections)
        mrr_val = mrr(list(retrieved_sections), gold_sections)

        scores["recall"].append(recall_hit)
        scores["mrr"].append(mrr_val)

        # ---- Answer generation ----
        context = ""
        for r in rows:
            context += f"\nSection {r[2]}\n{r[3]}\n"

        raw_prompt = f"""
Answer strictly from the context below.
If the answer is not explicitly present, say "Information not found".

CONTEXT:
{context}

QUESTION:
{query}
"""
        raw_answer = safe_complete(llm_reasoning, raw_prompt)
        time.sleep(2)

        final_answer = format_final_answer(raw_answer, query)

        answer_sections = extract_sections_from_answer(final_answer)

        # 🔑 Effective predicted coverage
        effective_sections = answer_sections | retrieved_sections

        # ---- Answer metrics ----
        p, r, f1 = citation_metrics(answer_sections, gold_sections)
        g = groundedness(answer_sections, retrieved_sections)
        coverage_recall = (
            len(effective_sections & gold_sections) / len(gold_sections)
            if gold_sections else 0.0
        )

        scores["citation_precision"].append(p)
        scores["citation_recall"].append(r)
        scores["citation_f1"].append(f1)
        scores["groundedness"].append(g)
        scores["coverage_recall"].append(coverage_recall)

        # ---- Per-query log ----
        per_query_logs.append({
            "query": query,
            "gold_sections": sorted(gold_sections),
            "retrieved_sections": sorted(retrieved_sections),
            "answer_sections": sorted(answer_sections),
            "effective_sections": sorted(effective_sections),
            "metrics": {
                "recall_hit": recall_hit,
                "mrr": mrr_val,
                "citation_precision": p,
                "citation_recall": r,
                "citation_f1": f1,
                "groundedness": g,
                "coverage_recall": coverage_recall
            }
        })

    aggregate_metrics = {
        "Recall@7": sum(scores["recall"]) / len(scores["recall"]),
        "MRR@7": sum(scores["mrr"]) / len(scores["mrr"]),
        "Citation_Precision": sum(scores["citation_precision"]) / len(scores["citation_precision"]),
        "Citation_Recall": sum(scores["citation_recall"]) / len(scores["citation_recall"]),
        "Citation_F1": sum(scores["citation_f1"]) / len(scores["citation_f1"]),
        "Groundedness": sum(scores["groundedness"]) / len(scores["groundedness"]),
        "Coverage_Recall": sum(scores["coverage_recall"]) / len(scores["coverage_recall"]),
    }

    return aggregate_metrics, per_query_logs

# =========================
# RUNNER
# =========================
def run_ablation(golden_path):
    with open(golden_path) as f:
        golden_set = json.load(f)

    golden_set = golden_set
    results = {}

    for name, cfg in PIPELINES.items():

        if cfg["use_reranker"]==False:
            continue

        metrics, details = evaluate_pipeline(name, cfg, golden_set)
        results[name] = metrics
        print(name, metrics)

        with open(f"ablation_details_{name}.json", "w") as f:
            json.dump(details, f, indent=2)

    with open("ablation_results_2.json", "w") as f:
        json.dump(results, f, indent=2)

if __name__ == "__main__":
    PIPELINES = {
        "A_vector_no_rerank": dict(mode="vector", use_reranker=False),
        "B_vector_rerank":    dict(mode="vector", use_reranker=True),
        "C_hybrid_no_rerank": dict(mode="hybrid", use_reranker=False),
        "D_hybrid_rerank":    dict(mode="hybrid", use_reranker=True),
    }

    run_ablation(GOLDEN_PATH)
