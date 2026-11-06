"""Optional LLM coaching built on top of the game's Stockfish analysis.

The LLM is never used to choose or validate a chess move.  It only explains
analysis that Stockfish has already produced. Configure Google's Gemini
free-tier API with:

    CHESS_LLM_API_KEY
    CHESS_LLM_MODEL     (optional, defaults to gemini-3.8-flash)

The browser uses the site's /api/llm proxy so the API key is never shipped to
the client. Set GEMINI_API_KEY (or CHESS_LLM_API_KEY) on the Vercel project.
"""

import asyncio
import json
import os
import sys
import urllib.error
import urllib.request

WASM = sys.platform == "emscripten"
js = None
if WASM:
    try:
        import js
    except ImportError:
        js = None

JS_HELPERS = '''
    window.chessLlmResults = {};
    window.chessLlmRequest = function(id, body) {
        fetch("/api/llm", {method: "POST", headers: {"Content-Type": "application/json"}, body: body})
            .then(r => r.text().then(t => { window.chessLlmResults[id] = JSON.stringify({status: r.status, body: t}); }))
            .catch(e => { window.chessLlmResults[id] = JSON.stringify({status: 0, body: String(e)}); });
    };
    window.chessLlmTake = function(id) {
        const result = window.chessLlmResults[id];
        if (result === undefined) return "";
        delete window.chessLlmResults[id];
        return result;
    };
'''


class LLMError(Exception):
    """A user-actionable error returned by the optional coaching service."""


def enabled():
    return WASM or bool(os.environ.get("CHESS_LLM_API_KEY"))


def _prompt(move_codes, best_san, evals, marks, result):
    mistakes = []
    for ply, (mark, loss) in sorted(marks.items()):
        best = best_san[ply] if ply < len(best_san) else None
        mistakes.append({
            "ply": ply + 1,
            "mark": mark,
            "loss": round(loss, 2),
            "played": move_codes[ply] if ply < len(move_codes) else None,
            "best": best,
            "evaluation_after": round(evals[ply], 2) if ply < len(evals) else None,
        })
    return (
        "You are a concise chess coach. Explain the following completed game using only "
        "the supplied Stockfish analysis. Do not invent tactics or evaluations. Mention "
        "the two most important lessons and one practical improvement. If there are no "
        "mistakes, describe one strategic strength. Keep the answer under 90 words. "
        "Return plain text, no headings or markdown.\n\n"
        + json.dumps({"moves": move_codes, "mistakes": mistakes, "result": result},
                     separators=(",", ":"))
    )


def _request_gemini(prompt):
    key = os.environ["CHESS_LLM_API_KEY"]
    model = os.environ.get("CHESS_LLM_MODEL", "gemini-3.8-flash")
    url = os.environ.get(
        "CHESS_LLM_API_URL",
        "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent" % model,
    )
    separator = "&" if "?" in url else "?"
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 180},
    }).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:200]
        raise LLMError("Gemini request failed (%d): %s" % (error.code, detail)) from error
    except (urllib.error.URLError, TimeoutError, ValueError) as error:
        raise LLMError("Gemini request failed: %s" % error) from error
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError, TypeError, AttributeError) as error:
        raise LLMError("Gemini returned an invalid or blocked response") from error
    return text or None


def _request_openai_compatible(prompt):
    key = os.environ.get("CHESS_LLM_API_KEY")
    url = os.environ["CHESS_LLM_API_URL"]
    model = os.environ["CHESS_LLM_MODEL"]
    body = json.dumps({
        "model": model,
        "temperature": 0.2,
        "max_tokens": 180,
        "messages": [
            {"role": "system", "content": "You explain chess analysis accurately and briefly."},
            {"role": "user", "content": prompt},
        ],
    }).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": "Bearer " + key,
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:200]
        raise LLMError("LLM request failed (%d): %s" % (error.code, detail)) from error
    except (urllib.error.URLError, TimeoutError, ValueError) as error:
        raise LLMError("LLM request failed: %s" % error) from error
    try:
        text = data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, AttributeError) as error:
        raise LLMError("LLM returned an invalid response") from error
    return text or None


def _request(prompt):
    if os.environ.get("CHESS_LLM_PROVIDER", "gemini").lower() == "gemini":
        return _request_gemini(prompt)
    return _request_openai_compatible(prompt)


async def _request_browser(prompt):
    if js is None:
        raise LLMError("Browser coaching is unavailable")
    js.eval(JS_HELPERS)
    request_id = "coach_" + str(id(prompt))
    js.eval("window.chessLlmRequest(%s, %s)" % (json.dumps(request_id), json.dumps(json.dumps({
        "prompt": prompt,
    }))))
    deadline = asyncio.get_running_loop().time() + 20
    while True:
        raw = js.eval("window.chessLlmTake(%s)" % json.dumps(request_id))
        if raw:
            break
        if asyncio.get_running_loop().time() > deadline:
            raise LLMError("The coaching server didn't answer")
        await asyncio.sleep(0.05)
    reply = json.loads(str(raw))
    try:
        data = json.loads(reply["body"]) if reply["body"] else {}
    except ValueError as error:
        raise LLMError("The coaching server returned an invalid response") from error
    if reply["status"] != 200:
        raise LLMError(data.get("error") or "The coaching server returned an error")
    return data.get("text") or None


async def explain_game(move_codes, best_san, evals, marks, result):
    """Return a short explanation, or None when coaching is not configured."""
    if not enabled():
        return None
    prompt = _prompt(move_codes, best_san, evals, marks, result)
    if WASM:
        return await _request_browser(prompt)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _request, prompt)
