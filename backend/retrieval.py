"""
AAIP - Retrieval System Module
Vector-based similarity search for evaluation context
"""

import os
import json
import numpy as np
from typing import Optional, List

# Try to import sentence-transformers, fall back to simple embedding if not available
try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False


# Initialize embedding model (lazy loading)
_embedding_model = None


def get_embedding_model():
    """Get or initialize the embedding model"""
    global _embedding_model

    if _embedding_model is None:
        if SENTENCE_TRANSFORMERS_AVAILABLE:
            # Use a lightweight model for efficiency
            model_name = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
            _embedding_model = SentenceTransformer(model_name)
        else:
            # Use OpenAI embeddings as fallback
            _embedding_model = "openai"

    return _embedding_model


async def generate_embedding(text: str) -> List[float]:
    """
    Generate embedding vector for text
    """
    model = get_embedding_model()

    if model == "openai":
        # Use OpenAI API for embeddings
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            # Return dummy embedding for testing
            return generate_dummy_embedding()

        import httpx
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "text-embedding-3-small",
                    "input": text[:8000]  # Truncate to avoid token limits
                },
                timeout=30.0
            )

            if response.status_code == 200:
                data = response.json()
                return data["data"][0]["embedding"]
            else:
                return generate_dummy_embedding()

    else:
        # Use sentence-transformers
        embedding = model.encode(text[:8000])
        return embedding.tolist()


def generate_dummy_embedding(dimensions: int = 384) -> List[float]:
    """
    Generate a deterministic dummy embedding for testing
    Uses simple hash-based approach for consistency
    """
    # Simple deterministic embedding based on text hash
    import hashlib

    # Create a fixed-size vector
    vector = np.zeros(dimensions)

    # Use first 1000 chars for hash
    text_hash = hashlib.md5(b"dummy").digest()

    # Fill vector with pseudo-random but deterministic values
    for i in range(min(len(text_hash) * 4, dimensions)):
        vector[i] = (text_hash[i % len(text_hash)] % 100) / 100.0

    return vector.tolist()


async def search_similar_outputs(
    db,
    agent_id: str,
    task_domain: str,
    agent_output: str,
    top_k: int = 5
) -> List[dict]:
    """
    Search for similar outputs in the database using vector similarity

    Returns list of similar evaluations with their scores
    """
    from sqlalchemy import select, text
    from database import Evaluation, Agent

    # Generate embedding for the current output (unused in MVP, kept for future pgvector use)
    await generate_embedding(agent_output)

    # For MVP, we'll use a simple text-based search
    # In production, you'd use pgvector's cosine similarity

    # Get recent evaluations for the same agent/domain
    result = await db.execute(
        select(Evaluation)
        .join(Agent)
        .where(
            Agent.id == agent_id,
            Evaluation.task_domain == task_domain
        )
        .order_by(Evaluation.timestamp.desc())
        .limit(50)
    )

    evaluations = result.scalars().all()

    if not evaluations:
        return []

    # Calculate simple similarity scores
    similarities = []
    for eval in evaluations:
        # Simple word overlap similarity
        similarity = calculate_text_similarity(agent_output, eval.agent_output)
        similarities.append({
            "evaluation_id": str(eval.id),
            "task_description": eval.task_description,
            "agent_output": eval.agent_output[:500],  # Truncate for context
            "final_score": eval.final_score,
            "similarity": round(similarity, 3),
            "timestamp": eval.timestamp.isoformat()
        })

    # Sort by similarity and return top k
    similarities.sort(key=lambda x: x["similarity"], reverse=True)
    return similarities[:top_k]


def calculate_text_similarity(text1: str, text2: str) -> float:
    """
    Calculate simple text similarity using word overlap
    """
    # Tokenize
    words1 = set(text1.lower().split())
    words2 = set(text2.lower().split())

    if not words1 or not words2:
        return 0.0

    # Calculate Jaccard similarity
    intersection = len(words1 & words2)
    union = len(words1 | words2)

    return intersection / union if union > 0 else 0.0


def format_context_for_judges(similar_outputs: List[dict]) -> str:
    """
    Format similar outputs as context for judge prompts
    """
    if not similar_outputs:
        return "No similar examples available."

    context_parts = []
    for i, output in enumerate(similar_outputs, 1):
        context_parts.append(
            f"Example {i} (Score: {output['final_score']}, Similarity: {output['similarity']}):\n"
            f"Task: {output['task_description'][:200]}...\n"
            f"Output: {output['agent_output'][:300]}..."
        )

    return "\n\n".join(context_parts)
