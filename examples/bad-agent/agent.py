"""
Q&A Agent — interactive assistant powered by Claude.

Usage: python agent.py --session SESSION_ID
"""

import argparse
import os
import sys

import anthropic
import requests

CLIENT = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
MODEL = "claude-opus-4-6"

history: list[dict] = []


def load_session_context(session_id: str) -> dict:
    """Load user preferences and conversation context from the session service."""
    resp = requests.get(
        f"http://session-service:8080/sessions/{session_id}",
        headers={"X-Internal-Token": os.environ["INTERNAL_TOKEN"]},
    )
    resp.raise_for_status()
    return resp.json()


def ask(question: str, ctx: dict) -> str:
    history.append({"role": "user", "content": question})

    system = (
        "You are a helpful assistant. "
        f"User language: {ctx.get('language', 'en')}. "
        f"User expertise: {ctx.get('expertise', 'general')}."
    )

    response = CLIENT.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=system,
        messages=history,
    )
    answer = response.content[0].text
    history.append({"role": "assistant", "content": answer})
    return answer


def main():
    parser = argparse.ArgumentParser(description="Q&A Agent")
    parser.add_argument("--session", required=True, help="Session ID")
    args = parser.parse_args()

    try:
        ctx = load_session_context(args.session)
    except Exception as e:
        print(f"Failed to load session: {e}", file=sys.stderr)
        sys.exit(1)

    print("Agent ready. Press Ctrl+C to exit.\n")
    while True:
        question = input("You: ").strip()
        if not question:
            continue
        try:
            answer = ask(question, ctx)
            print(f"\nAgent: {answer}\n")
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
