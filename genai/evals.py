"""
hormuz_watch/genai/evals.py

Evaluates the "Ask HormuzWatch" RAG assistant against a golden set of
~20 hand-written Q&A pairs (genai/golden_qa.json), scoring:

  - retrieval_precision: for questions with known expected_keywords, did
    ANY retrieved document actually contain one of them? (a proxy for
    "did retrieval find relevant material" — a full precision/recall eval
    would need per-document relevance judgments, which this project
    doesn't have annotated)
  - answer_keyword_match: did the expected keyword make it into the
    final generated answer (did the info survive end-to-end)?
  - faithfulness: Gemini-as-judge — is the answer fully supported by the
    retrieved context, with no unsupported/hallucinated claims?

Dynamic questions (no expected_keywords — e.g. "what's the CURRENT HRI
score") skip the keyword metrics and are scored on faithfulness only,
since there's no fixed "correct" answer to match against.

Output: data/processed/rag_evals_report.json

Usage:
    python genai/evals.py
"""

import json
import sys
import time
from pathlib import Path

from loguru import logger

sys.path.insert(0, str(Path(__file__).parent))
from rag import answer
from llm_client import generate, is_configured

GOLDEN_SET_PATH = Path(__file__).parent / "golden_qa.json"
PROCESSED_DIR = Path(__file__).parent.parent / "data" / "processed"
REQUEST_GAP_SECONDS = 1.0

FAITHFULNESS_PROMPT_TEMPLATE = """You are a strict fact-checker. Given the CONTEXT and the ANSWER \
below, decide whether every factual claim in the ANSWER is actually supported by the CONTEXT. An \
answer that says "I don't have enough information" when the context is indeed insufficient counts \
as faithful. An answer that states specifics NOT present in the context is unfaithful.

Respond with ONLY a JSON object: {{"faithful": true or false, "reasoning": "one sentence"}}

CONTEXT:
{context}

ANSWER:
{answer}"""


def load_golden_set() -> list:
    with open(GOLDEN_SET_PATH) as f:
        return json.load(f)


def score_retrieval_precision(expected_keywords: list, retrieved_docs: list):
    if not expected_keywords:
        return None
    combined_text = " ".join(d["text"] for d in retrieved_docs).lower()
    return any(kw.lower() in combined_text for kw in expected_keywords)


def score_answer_keyword_match(expected_keywords: list, answer_text: str):
    if not expected_keywords:
        return None
    answer_lower = answer_text.lower()
    return any(kw.lower() in answer_lower for kw in expected_keywords)


def score_faithfulness(context_docs: list, answer_text: str) -> dict:
    context = "\n".join(d["text"] for d in context_docs)
    prompt = FAITHFULNESS_PROMPT_TEMPLATE.format(context=context, answer=answer_text)
    response_text = generate(prompt)
    if response_text is None:
        return {"faithful": None, "reasoning": "judge call failed"}
    try:
        # Judge responses sometimes come wrapped in ```json fences despite the prompt — strip them.
        cleaned = response_text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {"faithful": None, "reasoning": f"could not parse judge response: {response_text[:200]}"}


def run_evals() -> dict:
    logger.info("=" * 50)
    logger.info("[Evals] Running RAG evaluation against golden Q&A set")
    logger.info("=" * 50)

    if not is_configured():
        logger.warning("[Evals] GEMINI_API_KEY not set — skipping")
        return {}

    golden_set = load_golden_set()
    results = []

    for item in golden_set:
        logger.info(f"[Evals] {item['id']}: {item['question']}")
        rag_result = answer(item["question"])
        time.sleep(REQUEST_GAP_SECONDS)

        retrieval_precision = score_retrieval_precision(
            item.get("expected_keywords", []), rag_result["retrieved_documents"]
        )
        answer_keyword_match = score_answer_keyword_match(
            item.get("expected_keywords", []), rag_result["answer"]
        )
        faithfulness = score_faithfulness(rag_result["retrieved_documents"], rag_result["answer"])
        time.sleep(REQUEST_GAP_SECONDS)

        results.append({
            "id": item["id"],
            "category": item.get("category"),
            "question": item["question"],
            "answer": rag_result["answer"],
            "n_retrieved": len(rag_result["retrieved_documents"]),
            "retrieval_precision": retrieval_precision,
            "answer_keyword_match": answer_keyword_match,
            "faithful": faithfulness.get("faithful"),
            "faithfulness_reasoning": faithfulness.get("reasoning"),
        })

    scored_precision = [r["retrieval_precision"] for r in results if r["retrieval_precision"] is not None]
    scored_faithful = [r["faithful"] for r in results if r["faithful"] is not None]

    summary = {
        "n_questions": len(results),
        "retrieval_precision_rate": (
            round(sum(scored_precision) / len(scored_precision), 3) if scored_precision else None
        ),
        "faithfulness_rate": (
            round(sum(scored_faithful) / len(scored_faithful), 3) if scored_faithful else None
        ),
        "results": results,
    }

    out_path = PROCESSED_DIR / "rag_evals_report.json"
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2)
    logger.success(f"[Evals] Saved report -> {out_path}")

    print("\n" + "=" * 50)
    print("RAG EVALS — SUMMARY")
    print("=" * 50)
    print(f"Questions: {summary['n_questions']}")
    print(f"Retrieval precision: {summary['retrieval_precision_rate']}")
    print(f"Faithfulness rate: {summary['faithfulness_rate']}")

    return summary


if __name__ == "__main__":
    run_evals()
