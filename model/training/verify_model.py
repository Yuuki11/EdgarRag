"""
Quick verification that the fine-tuned model works correctly.
Run after export: python model/training/verify_model.py

Tests:
1. Numeric QA -- financial figure extraction
2. Sentiment classification
3. Abstention on questions outside filing data

Supports comparing fine-tuned model against base model for ablation.
"""

import argparse
import os
import sys

import httpx

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")


def ollama_generate_url() -> str:
    return f"{os.getenv('OLLAMA_HOST', OLLAMA_HOST).rstrip('/')}/api/generate"

TEST_CASES = [
    {
        "name": "Numeric QA",
        "prompt": (
            "What was Apple's revenue in FY2023? The revenue was $383.29 billion "
            "as reported in the 10-K filing."
        ),
        "expect_contains": ["383", "billion"],
    },
    {
        "name": "Sentiment",
        "prompt": (
            "Classify the sentiment of this financial statement as positive, "
            "negative, or neutral:\n\n"
            '"Revenue increased by 15% year-over-year, driven by strong demand."'
        ),
        "expect_contains": ["positive", "Positive"],
    },
    {
        "name": "Abstention",
        "prompt": (
            "Based on the SEC filings, what is the current stock price of Apple?"
        ),
        "expect_contains": ["cannot", "don't", "not available", "not able", "do not"],
    },
]


def query_model(model: str, prompt: str) -> str | None:
    """Send a prompt to Ollama and return the response text."""
    try:
        response = httpx.post(
            ollama_generate_url(),
            json={
                "model": model,
                "prompt": prompt,
                "options": {"temperature": 0.1},
                "stream": False,
            },
            timeout=120.0,
        )
        response.raise_for_status()
        return response.json()["response"]
    except (httpx.HTTPError, KeyError) as e:
        print(f"  Request error: {e}")
        return None


def verify_model(model: str = "finedgar") -> bool:
    """Run all test cases against the specified Ollama model."""
    print(f"\n{'='*60}")
    print(f"  Testing model: {model}")
    print(f"{'='*60}")

    all_passed = True

    for test in TEST_CASES:
        result = query_model(model, test["prompt"])

        if result is None:
            print(f"[FAIL] {test['name']} -- request error")
            all_passed = False
            continue

        passed = any(kw.lower() in result.lower() for kw in test["expect_contains"])

        if passed:
            print(f"[PASS] {test['name']}")
            print(f"  Response: {result[:150]}...")
        else:
            print(f"[FAIL] {test['name']}")
            print(f"  Expected one of: {test['expect_contains']}")
            print(f"  Got: {result[:200]}")
            all_passed = False

    return all_passed


def main():
    parser = argparse.ArgumentParser(
        description="Verify fine-tuned model via Ollama"
    )
    parser.add_argument(
        "--model",
        type=str,
        default="finedgar",
        help="Ollama model name to test (default: finedgar)",
    )
    parser.add_argument(
        "--base-model",
        type=str,
        default="gemma4:e2b",
        help="Base model for comparison (default: gemma4:e2b)",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Also test the base model for ablation comparison",
    )
    args = parser.parse_args()

    # Test fine-tuned model
    ft_passed = verify_model(args.model)

    # Optional: test base model for comparison
    base_passed = None
    if args.compare:
        base_passed = verify_model(args.base_model)

        print(f"\n{'='*60}")
        print(f"  Ablation Summary")
        print(f"{'='*60}")
        print(f"  Fine-tuned ({args.model}):  {'ALL PASS' if ft_passed else 'SOME FAIL'}")
        print(f"  Base ({args.base_model}):    {'ALL PASS' if base_passed else 'SOME FAIL'}")

    sys.exit(0 if ft_passed else 1)


if __name__ == "__main__":
    main()
