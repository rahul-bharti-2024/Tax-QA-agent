# Metadata-Augmented Hybrid RAG for Indian Tax Law

This repository contains the codebase for **Metadata-Augmented Hybrid Retrieval-Augmented Generation (RAG)** applied to the **Indian Income Tax Bill, 2025**.  
The system is designed for **high-precision legal question answering**, with a focus on retrieval fidelity, groundedness, and reproducible evaluation.

The accompanying paper evaluates multiple retrieval and reranking configurations through a controlled ablation study on a curated golden test set.

---

## Project Overview

Legal documents exhibit strong hierarchical structure (Chapters → Sections → Clauses) and high semantic overlap across provisions.  
Naive RAG pipelines often fail due to:
- Context fragmentation during chunking
- Vocabulary mismatch between lay queries and statutory language
- Retrieval of legally adjacent but incorrect sections (“distractor problem”)

This project addresses these issues via:
- **Structure-aware ingestion**
- **Hybrid dense + sparse retrieval**
- **Metadata-augmented cross-encoder reranking**
- **LLM-based groundedness evaluation**

---




