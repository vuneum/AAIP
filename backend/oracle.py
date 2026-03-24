"""
AAIP - Benchmark Oracle Module
Fetches model performance rankings from OpenRouter API
"""

import os
import json
import httpx
from datetime import datetime, timedelta
from typing import Optional

# Domain-specific model rankings (fallback when API is unavailable)
# These are based on common benchmark performance data
DOMAIN_MODEL_RANKINGS = {
    "coding": [
        "anthropic/claude-3.5-sonnet",
        "openai/gpt-4o",
        "deepseek/deepseek-coder",
        "qwen/qwen-coder-turbo",
        "meta-llama/llama-3.1-70b-instruct"
    ],
    "finance": [
        "anthropic/claude-3.5-sonnet",
        "openai/gpt-4o",
        "google/gemini-pro-1.5",
        "meta-llama/llama-3.1-70b-instruct",
        "mistralai/mistral-large"
    ],
    "general": [
        "anthropic/claude-3.5-sonnet",
        "openai/gpt-4o",
        "google/gemini-pro-1.5",
        "meta-llama/llama-3.1-70b-instruct",
        "mistralai/mistral-large"
    ]
}

# Model metadata (pricing, context window, etc.)
MODEL_METADATA = {
    "anthropic/claude-3.5-sonnet": {
        "name": "Claude 3.5 Sonnet",
        "context_window": 200000,
        "pricing": {"prompt": 3.0, "completion": 15.0}
    },
    "openai/gpt-4o": {
        "name": "GPT-4o",
        "context_window": 128000,
        "pricing": {"prompt": 2.5, "completion": 10.0}
    },
    "deepseek/deepseek-coder": {
        "name": "DeepSeek Coder",
        "context_window": 160000,
        "pricing": {"prompt": 0.14, "completion": 0.28}
    },
    "qwen/qwen-coder-turbo": {
        "name": "Qwen Coder Turbo",
        "context_window": 128000,
        "pricing": {"prompt": 0.2, "completion": 0.4}
    },
    "google/gemini-pro-1.5": {
        "name": "Gemini Pro 1.5",
        "context_window": 2000000,
        "pricing": {"prompt": 1.25, "completion": 5.0}
    },
    "meta-llama/llama-3.1-70b-instruct": {
        "name": "Llama 3.1 70B",
        "context_window": 128000,
        "pricing": {"prompt": 0.8, "completion": 0.8}
    },
    "mistralai/mistral-large": {
        "name": "Mistral Large",
        "context_window": 128000,
        "pricing": {"prompt": 2.0, "completion": 6.0}
    }
}

# Cache for benchmark data
_benchmark_cache = {}


async def fetch_openrouter_models() -> dict:
    """
    Fetch model list from OpenRouter API
    Returns a dictionary of model information
    """
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return {}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://openrouter.ai/api/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=30.0
            )
            if response.status_code == 200:
                data = response.json()
                models = {}
                for model in data.get("data", []):
                    models[model["id"]] = {
                        "name": model.get("name", ""),
                        "context_window": model.get("context_length", 0),
                        "pricing": model.get("pricing", {})
                    }
                return models
    except Exception as e:
        print(f"Error fetching OpenRouter models: {e}")

    return {}


async def get_benchmark_rankings(domain: str, force_refresh: bool = False) -> list[str]:
    """
    Get benchmark rankings for a specific domain
    Uses cache with 24-hour refresh
    """
    global _benchmark_cache

    cache_key = f"benchmark_{domain}"
    current_time = datetime.utcnow()

    # Check if cache is valid
    if not force_refresh and cache_key in _benchmark_cache:
        cached_data = _benchmark_cache[cache_key]
        if current_time - cached_data["timestamp"] < timedelta(hours=24):
            return cached_data["rankings"]

    # Try to fetch from OpenRouter
    openrouter_models = await fetch_openrouter_models()

    if openrouter_models:
        # Process OpenRouter data and create domain-specific rankings
        rankings = create_domain_rankings(domain, openrouter_models)
    else:
        # Fallback to static rankings
        rankings = DOMAIN_MODEL_RANKINGS.get(domain, DOMAIN_MODEL_RANKINGS["general"])

    # Update cache
    _benchmark_cache[cache_key] = {
        "rankings": rankings,
        "timestamp": current_time
    }

    return rankings


def create_domain_rankings(domain: str, models: dict) -> list[str]:
    """
    Create domain-specific rankings from OpenRouter model data
    """
    # Domain keywords for filtering
    domain_keywords = {
        "coding": ["code", "coder", "programming", "developer"],
        "finance": ["finance", "financial", "trading", "investment"],
        "general": []
    }

    keywords = domain_keywords.get(domain, [])

    # Score models based on domain relevance and capability
    scored_models = []
    for model_id, model_info in models.items():
        score = 0
        model_name_lower = model_info.get("name", "").lower()

        # Check for domain keywords
        for keyword in keywords:
            if keyword in model_name_lower:
                score += 10

        # Consider context window (larger is better)
        context = model_info.get("context_window", 0)
        if context > 100000:
            score += 5
        elif context > 50000:
            score += 3

        # Consider pricing (cheaper is better for judges)
        pricing = model_info.get("pricing", {})
        prompt_price = pricing.get("prompt", 999)
        if prompt_price < 1.0:
            score += 3
        elif prompt_price < 5.0:
            score += 1

        scored_models.append((model_id, score))

    # Sort by score descending
    scored_models.sort(key=lambda x: x[1], reverse=True)

    # Return top 10 model IDs
    return [model_id for model_id, _ in scored_models[:10]]


async def get_judges_for_domain(domain: str, num_judges: int = 3) -> list[dict]:
    """
    Get the top performing models as judges for a domain
    Returns list of judge configurations
    """
    rankings = await get_benchmark_rankings(domain)

    judges = []
    for i, model_id in enumerate(rankings[:num_judges]):
        metadata = MODEL_METADATA.get(model_id, {
            "name": model_id,
            "context_window": 128000,
            "pricing": {"prompt": 1.0, "completion": 1.0}
        })

        judges.append({
            "rank": i + 1,
            "model_id": model_id,
            "name": metadata["name"],
            "context_window": metadata["context_window"],
            "pricing": metadata["pricing"]
        })

    return judges


async def get_all_domains() -> list[str]:
    """Get list of supported domains"""
    return list(DOMAIN_MODEL_RANKINGS.keys())


async def get_model_metadata(model_id: str) -> dict:
    """Get metadata for a specific model"""
    return MODEL_METADATA.get(model_id, {
        "name": model_id,
        "context_window": 128000,
        "pricing": {"prompt": 1.0, "completion": 1.0}
    })
