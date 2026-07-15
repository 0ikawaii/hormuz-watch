"""
hormuz_watch/genai/rag.py

The "Ask HormuzWatch" RAG assistant: embeds the corpus (genai/corpus.py)
once and caches it locally, retrieves the top-k most relevant documents
for a question via cosine similarity (no vector DB needed at this
corpus size — a few hundred documents, brute-force numpy search is
plenty fast), then asks Gemini to answer USING ONLY the retrieved
context, with citations back to source/date/url.

Usage:
    python genai/rag.py "What happened during the 2019 tanker attacks?"
"""

import json
import sys
import time
from pathlib import Path

import numpy as np
from loguru import logger

sys.path.insert(0, str(Path(__file__).parent))
from corpus import build_corpus
from llm_client import embed_text, generate, is_configured

CACHE_PATH = Path(__file__).parent / "rag_index.json"

ANSWER_PROMPT_TEMPLATE = """You are HormuzWatch's research assistant. Answer the user's question \
using ONLY the context documents below — do not use outside knowledge, and do not make claims \
the context doesn't support. If the context doesn't contain enough information to answer, say so \
explicitly rather than guessing.

After your answer, list the sources you actually used as a "Sources:" section, citing each by \
its [N] marker.

Context documents:
{context}

Question: {question}

Answer (with inline [N] citations matching the context documents, followed by a Sources section):"""


def build_and_cache_index(force: bool = False) -> dict:
    """
    Embeds every corpus document and caches {doc, embedding} pairs to
    disk. Re-embedding the whole corpus costs one API call per document,
    so this is cached rather than done per-query.
    """
    if CACHE_PATH.exists() and not force:
        with open(CACHE_PATH) as f:
            return json.load(f)

    if not is_configured():
        logger.warning("[RAG] GEMINI_API_KEY not set — cannot build embedding index")
        return {"documents": [], "embeddings": []}

    docs = build_corpus()
    embeddings = []
    kept_docs = []

    # Free tier caps embed_content at 100 requests/minute — pace proactively
    # rather than relying on llm_client's retry-on-429 alone, or a corpus
    # this size burns through several rate-limit cooldown cycles.
    request_gap_seconds = 0.7

    logger.info(f"[RAG] Embedding {len(docs)} documents "
               f"(~{len(docs) * request_gap_seconds / 60:.1f} min at the free-tier pace)...")
    for i, doc in enumerate(docs):
        vec = embed_text(doc["text"], task_type="RETRIEVAL_DOCUMENT")
        if vec is not None:
            embeddings.append(vec)
            kept_docs.append(doc)
        if i < len(docs) - 1:
            time.sleep(request_gap_seconds)
        if (i + 1) % 50 == 0:
            logger.info(f"[RAG] Embedded {i + 1}/{len(docs)}...")

    index = {"documents": kept_docs, "embeddings": embeddings}
    with open(CACHE_PATH, "w") as f:
        json.dump(index, f)
    logger.success(f"[RAG] Cached {len(kept_docs)} embedded documents -> {CACHE_PATH}")
    return index


def _cosine_similarity(query_vec: list, doc_vecs: np.ndarray) -> np.ndarray:
    query = np.asarray(query_vec)
    query_norm = query / (np.linalg.norm(query) + 1e-10)
    doc_norms = doc_vecs / (np.linalg.norm(doc_vecs, axis=1, keepdims=True) + 1e-10)
    return doc_norms @ query_norm


def retrieve(question: str, k: int = 6) -> list:
    """Returns the top-k most relevant documents for a question."""
    index = build_and_cache_index()
    if not index["documents"]:
        return []

    query_vec = embed_text(question, task_type="RETRIEVAL_QUERY")
    if query_vec is None:
        return []

    doc_vecs = np.array(index["embeddings"])
    similarities = _cosine_similarity(query_vec, doc_vecs)
    top_k_idx = np.argsort(similarities)[::-1][:k]

    return [
        {**index["documents"][i], "similarity": round(float(similarities[i]), 4)}
        for i in top_k_idx
    ]


def answer(question: str, k: int = 6) -> dict:
    """
    Full RAG pipeline: retrieve relevant docs, ask Gemini to answer
    grounded in them, return the answer + the documents actually retrieved
    (so callers/evals can check retrieval quality independent of generation).
    """
    if not is_configured():
        return {
            "question": question,
            "answer": "GEMINI_API_KEY is not configured — the Ask HormuzWatch assistant is unavailable.",
            "retrieved_documents": [],
        }

    docs = retrieve(question, k=k)
    if not docs:
        return {
            "question": question,
            "answer": "No relevant documents found in the corpus for this question.",
            "retrieved_documents": [],
        }

    context = "\n".join(
        f"[{i+1}] (source: {d['source']}, date: {d.get('date') or 'n/a'}) {d['text']}"
        for i, d in enumerate(docs)
    )
    prompt = ANSWER_PROMPT_TEMPLATE.format(context=context, question=question)

    response_text = generate(prompt)
    if response_text is None:
        response_text = "The assistant failed to generate an answer — see logs for details."

    return {
        "question": question,
        "answer": response_text,
        "retrieved_documents": docs,
    }


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "What is the Hormuz Risk Index and how is it calculated?"
    result = answer(q)
    print("\nQ:", result["question"])
    print("\nA:", result["answer"])
    print(f"\n({len(result['retrieved_documents'])} documents retrieved)")
