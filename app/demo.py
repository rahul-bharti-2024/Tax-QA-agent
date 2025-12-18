# streamlit demo
import streamlit as st
import time

from rag_app import ask_tax_question

st.set_page_config(
    page_title="Indian Tax QA",
    layout="wide"
)

st.title("Indian Tax QA Assistant")
st.caption(
    "LLM-based Retrieval-Augmented Generation system over the Indian Income Tax Code"
)

# --- Sidebar ---
with st.sidebar:
    st.header("System Info")
    st.markdown(
        """
        **Retrieval:**
        - Hybrid (BM25 + Vector)
        - Cross-encoder reranking

        **Evaluation:**
        - Recall@k
        - MRR@k
        - Groundedness

        **Corpus:**
        - Income-tax Bill, 2025
        """
    )

# --- Main UI ---
query = st.text_area(
    "Enter your tax-related question",
    placeholder="e.g. How are lottery winnings taxed in India?",
    height=100
)

submit = st.button("Submit")

if submit and query.strip():
    with st.spinner("Retrieving relevant sections and generating answer..."):
        start = time.time()

        answer = ask_tax_question(query)

        elapsed = time.time() - start

    st.success(f"Answer generated in {elapsed:.2f} seconds")

    st.subheader("Answer")
    st.write(answer)

elif submit:
    st.warning("Please enter a question before submitting.")
