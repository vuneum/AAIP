"""
AAIP - Judge Execution Module
Parallel execution of judge models for output evaluation
"""

import os
import json
import asyncio
import httpx
from typing import Optional

JUDGE_PROMPT_TEMPLATE = """You are an impartial AI judge evaluating another AI agent's output.

Evaluate the following agent output from 0-100 based on:
- Correctness: Is the output factually correct and accurate?
- Completeness: Does the output fully address the task?
- Logical Reasoning: Is the reasoning sound and well-structured?

Task: {task_description}

Agent Output:
{agent_output}

Context (Similar Examples from Previous Evaluations):
{context}

Return ONLY the integer score (0-100). Do not write explanations, do not add text, just the number."""


async def call_judge_model(
    model_id: str,
    task_description: str,
    agent_output: str,
    context: str = ""
) -> dict:
    """
    Call a judge model to evaluate an agent output
    Returns the score and metadata
    """
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return {
            "model_id": model_id,
            "score": None,
            "error": "No API key configured"
        }

    # Prepare the prompt
    prompt = JUDGE_PROMPT_TEMPLATE.format(
        task_description=task_description,
        agent_output=agent_output,
        context=context
    )

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://aaip.ai",
                    "X-Title": "AAIP"
                },
                json={
                    "model": model_id,
                    "messages": [
                        {"role": "user", "content": prompt}
                    ],
                    "max_tokens": 10,  # Minimal tokens for just the score
                    "temperature": 0.1  # Low temperature for consistent scoring
                },
                timeout=60.0
            )

            if response.status_code == 200:
                data = response.json()
                content = data["choices"][0]["message"]["content"].strip()

                # Extract numeric score
                try:
                    score = int(content)
                    score = max(0, min(100, score))  # Clamp to 0-100
                    return {
                        "model_id": model_id,
                        "score": score,
                        "raw_response": content
                    }
                except ValueError:
                    return {
                        "model_id": model_id,
                        "score": None,
                        "error": f"Invalid score format: {content}"
                    }
            else:
                return {
                    "model_id": model_id,
                    "score": None,
                    "error": f"API error: {response.status_code}"
                }

    except asyncio.TimeoutError:
        return {
            "model_id": model_id,
            "score": None,
            "error": "Request timeout"
        }
    except Exception as e:
        return {
            "model_id": model_id,
            "score": None,
            "error": str(e)
        }


async def execute_parallel_judges(
    judges: list[dict],
    task_description: str,
    agent_output: str,
    context: str = ""
) -> dict:
    """
    Execute all judge models in parallel
    Returns all judge scores
    """
    # Create tasks for all judges
    tasks = []
    for judge in judges:
        task = call_judge_model(
            model_id=judge["model_id"],
            task_description=task_description,
            agent_output=agent_output,
            context=context
        )
        tasks.append(task)

    # Execute all in parallel
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Process results
    judge_scores = {}
    errors = []

    for i, result in enumerate(results):
        if isinstance(result, Exception):
            errors.append({
                "model_id": judges[i]["model_id"],
                "error": str(result)
            })
        elif result.get("score") is not None:
            judge_scores[judges[i]["model_id"]] = result["score"]
        else:
            errors.append({
                "model_id": judges[i]["model_id"],
                "error": result.get("error", "Unknown error")
            })

    return {
        "judge_scores": judge_scores,
        "errors": errors,
        "total_judges": len(judges),
        "successful_judges": len(judge_scores)
    }


def generate_mock_scores(num_judges: int = 3) -> dict:
    """
    Generate mock scores for testing without API access
    """
    import random

    base_score = random.randint(60, 90)
    judge_scores = {}

    model_ids = [
        "anthropic/claude-3.5-sonnet",
        "openai/gpt-4o",
        "google/gemini-pro-1.5"
    ]

    for i in range(min(num_judges, len(model_ids))):
        # Random score within ±15 of base score
        score = max(0, min(100, base_score + random.randint(-15, 15)))
        judge_scores[model_ids[i]] = score

    return {
        "judge_scores": judge_scores,
        "errors": [],
        "total_judges": num_judges,
        "successful_judges": len(judge_scores),
        "mock": True
    }
