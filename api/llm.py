"""Server-side proxy for the browser's optional Gemini chess coach."""

import json
import os

import requests
from flask import Flask, jsonify, request

app = Flask(__name__)
MAX_PROMPT_LENGTH = 24000


@app.route("/api/llm", methods=["POST", "OPTIONS"])
def coach():
    if request.method == "OPTIONS":
        return "", 204
    payload = request.get_json(silent=True) or {}
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT_LENGTH:
        return jsonify(error="Invalid coaching request"), 400
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("CHESS_LLM_API_KEY")
    if not key:
        return jsonify(error="Browser coaching is not configured"), 503
    model = os.environ.get("CHESS_LLM_MODEL", "gemini-3.8-flash")
    url = "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent" % model
    try:
        response = requests.post(url, headers={"x-goog-api-key": key}, json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 180},
        }, timeout=20)
    except requests.RequestException:
        return jsonify(error="The coaching service could not be reached"), 502
    if response.status_code != 200:
        return jsonify(error="The coaching service returned an error"), 502
    try:
        data = response.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        return jsonify(error="The coaching service returned an invalid response"), 502
    return jsonify(text=text)
