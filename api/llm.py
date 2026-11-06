"""Server-side proxy for the browser's optional Groq chess coach."""

import json
import os

import requests
from flask import Flask, jsonify, request

app = Flask(__name__)
MAX_PROMPT_LENGTH = 24000


def _content_text(content):
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict)).strip()
    return (content or "").strip() if isinstance(content, str) else ""


@app.route("/api/llm", methods=["POST", "OPTIONS"])
def coach():
    if request.method == "OPTIONS":
        return "", 204
    payload = request.get_json(silent=True) or {}
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT_LENGTH:
        return jsonify(error="Invalid coaching request"), 400
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        return jsonify(error="Browser coaching is not configured"), 503
    model = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
    url = os.environ.get("GROQ_API_URL", "https://api.groq.com/openai/v1/chat/completions")
    try:
        response = requests.post(url, headers={"Authorization": "Bearer " + key}, json={
            "model": model,
            "temperature": 0.2,
            "max_completion_tokens": 180,
            "reasoning_effort": "low",
            "messages": [
                {"role": "system", "content": "You explain chess analysis accurately and briefly."},
                {"role": "user", "content": prompt},
            ],
        }, timeout=20)
    except requests.RequestException:
        return jsonify(error="The coaching service could not be reached"), 502
    if response.status_code != 200:
        return jsonify(error="The coaching service returned an error"), 502
    try:
        data = response.json()
        text = _content_text(data["choices"][0]["message"].get("content"))
        if not text:
            raise ValueError("empty response")
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        return jsonify(error="The coaching service returned an invalid response"), 502
    return jsonify(text=text)
