"""
AAIP - Consensus Engine Module
Calculate final reliability score from judge evaluations
"""

import statistics
import math
from typing import Optional


def calculate_consensus(judge_scores: dict) -> dict:
    """
    Calculate final AAIP score from judge evaluations

    Returns:
        - final_score: Average of all judge scores
        - score_variance: Variance of judge scores
        - confidence_interval: (low, high) tuple
        - agreement_level: How well judges agree
    """
    if not judge_scores:
        return {
            "final_score": 0.0,
            "score_variance": 0.0,
            "confidence_interval_low": 0.0,
            "confidence_interval_high": 100.0,
            "agreement_level": "no_data",
            "judge_count": 0
        }

    scores = list(judge_scores.values())
    n = len(scores)

    if n == 0:
        return {
            "final_score": 0.0,
            "score_variance": 0.0,
            "confidence_interval_low": 0.0,
            "confidence_interval_high": 100.0,
            "agreement_level": "no_data",
            "judge_count": 0
        }

    # Calculate mean
    mean_score = statistics.mean(scores)

    # Calculate variance
    if n > 1:
        variance = statistics.variance(scores)
    else:
        variance = 0.0

    # Calculate standard deviation
    std_dev = math.sqrt(variance) if variance > 0 else 0.0

    # Calculate 95% confidence interval
    # Using t-distribution for small sample sizes
    if n > 1:
        t_critical = get_t_critical(n - 1)
        margin_of_error = t_critical * (std_dev / math.sqrt(n))
    else:
        margin_of_error = 0.0

    confidence_low = max(0, mean_score - margin_of_error)
    confidence_high = min(100, mean_score + margin_of_error)

    # Determine agreement level
    if n < 3:
        agreement_level = "insufficient_data"
    elif std_dev <= 5:
        agreement_level = "high"
    elif std_dev <= 15:
        agreement_level = "moderate"
    else:
        agreement_level = "low"

    return {
        "final_score": round(mean_score, 2),
        "score_variance": round(variance, 2),
        "score_std_dev": round(std_dev, 2),
        "confidence_interval_low": round(confidence_low, 2),
        "confidence_interval_high": round(confidence_high, 2),
        "agreement_level": agreement_level,
        "judge_count": n
    }


def get_t_critical(degrees_of_freedom: int) -> float:
    """
    Get t-critical value for 95% confidence interval
    Approximate values for common degrees of freedom
    """
    t_table = {
        1: 12.706,
        2: 4.303,
        3: 3.182,
        4: 2.776,
        5: 2.571,
        6: 2.447,
        7: 2.365,
        8: 2.306,
        9: 2.262,
        10: 2.228,
        20: 2.086,
        30: 2.042,
        60: 2.000,
        120: 1.980,
        float('inf'): 1.960
    }

    # Find closest value
    for df in sorted(t_table.keys()):
        if degrees_of_freedom <= df:
            return t_table[df]

    return 1.960


def detect_outliers(judge_scores: dict, threshold: float = 20.0) -> dict:
    """
    Detect outlier scores that deviate significantly from the mean

    Returns:
        - outlier_models: List of model IDs that are outliers
        - weighted_scores: Scores with outliers given less weight
    """
    if not judge_scores or len(judge_scores) < 3:
        return {
            "outlier_models": [],
            "weighted_scores": judge_scores,
            "outlier_count": 0
        }

    scores = list(judge_scores.values())
    mean = statistics.mean(scores)
    std_dev = math.sqrt(statistics.variance(scores))

    outlier_models = []
    weighted_scores = {}

    for model_id, score in judge_scores.items():
        if std_dev > 0 and abs(score - mean) > threshold * std_dev:
            outlier_models.append(model_id)
            # Give outliers reduced weight (0.5)
            weighted_scores[model_id] = {
                "score": score,
                "weight": 0.5,
                "reason": "outlier"
            }
        else:
            weighted_scores[model_id] = {
                "score": score,
                "weight": 1.0,
                "reason": "normal"
            }

    return {
        "outlier_models": outlier_models,
        "weighted_scores": weighted_scores,
        "outlier_count": len(outlier_models)
    }


def calculate_weighted_consensus(judge_scores: dict) -> dict:
    """
    Calculate consensus with outlier detection and weighting
    """
    # First check for outliers
    outlier_result = detect_outliers(judge_scores)

    # Calculate weighted mean
    weighted_scores = outlier_result["weighted_scores"]
    total_weight = sum(s["weight"] for s in weighted_scores.values())

    if total_weight > 0:
        weighted_mean = sum(
            s["score"] * s["weight"]
            for s in weighted_scores.values()
        ) / total_weight
    else:
        weighted_mean = 0.0

    return {
        "final_score": round(weighted_mean, 2),
        "outliers": outlier_result["outlier_models"],
        "weighted_scores": {
            k: v["score"] for k, v in weighted_scores.items()
        },
        "consensus_method": "weighted"
    }
