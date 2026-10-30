"""
Agentic RAG — state
===================
Working memory of a single question-answering run. The retry loop lives in this
state: `attempt`, `refined_query` and `history` are what let the Reflection
Agent send the graph back to retrieval without losing what it already learned.
"""

from typing import Any, Dict, List, Optional
from typing_extensions import TypedDict


class RAGState(TypedDict, total=False):
    # Request
    query: str                      # the auditor's original question
    search_query: str               # what retrieval actually searched for this attempt
    invoice_id: Optional[str]       # optional filter to a single invoice
    max_retries: int

    # Retrieval -> augmentation
    retrieved_chunks: List[Dict[str, Any]]
    ranked_chunks: List[Dict[str, Any]]
    context: str

    # Generation
    answer: str
    answer_cached: bool

    # Reflection (RAG Triad)
    context_relevance: float
    groundedness: float
    answer_relevance: float
    average_score: float
    threshold: float
    passed: bool
    critique: str

    # Loop control & audit
    attempt: int
    history: List[Dict[str, Any]]
    best_attempt: Optional[Dict[str, Any]]
    guardrail: Dict[str, Any]
    blocked: bool
    error: Optional[str]
