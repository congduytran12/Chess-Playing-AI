"""Optional LLM coaching built on top of the game's Stockfish analysis.

The LLM is never used to choose or validate a chess move.  It only explains
analysis that Stockfish has already produced. Configure Groq with:

    GROQ_API_KEY
    GROQ_MODEL          (optional, defaults to openai/gpt-oss-120b)

The browser uses the site's /api/llm proxy so the API key is never shipped to
the client. Set GROQ_API_KEY on the Vercel project.
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


def _content_text(content):
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict)).strip()
    return (content or "").strip() if isinstance(content, str) else ""


def enabled():
    return WASM or bool(os.environ.get("GROQ_API_KEY"))


# What the coach is asked, as the browser sends it to /api/llm (and the desktop turns into a prompt itself). There are
# three kinds, each with the language to answer in; the server checks every field (api/llm.py), so no text of the
# caller's own reaches the model:
#   game     moves (codes), best (SAN, one per position), evals (White's point of view), marks, result
#   move     fen (before the move), played, history (SAN), best, reply, before and after (White's point of view),
#            mark, loss
#   mistake  fen (the player to move), opponent (the move before it), played, best, reply, score (the best move's,
#            for the player), after (the move played, for the player), loss
KINDS = ("game", "move", "mistake", "hint")
LANGUAGES = {"en": "English", "vi": "Vietnamese"}
HISTORY_PLIES = 10  # the moves before the explained one that the coach is told
CHECKMATE = 1000  # chessAi.CHECKMATE and MATE_THRESHOLD: this file stands alone (the server loads it by itself)
MATE_THRESHOLD = 800
TOKENS = {"game": 180, "move": 220, "mistake": 220, "hint": 140}  # the answer's limit; Vietnamese needs about twice as many


def max_tokens(kind, lang="en"):
    return TOKENS.get(kind, TOKENS["game"]) * (2 if lang == "vi" else 1)


# the instruction for the answer's language ("" for English)
def _language_note(lang):
    if lang == "vi":
        return (" Write the answer in Vietnamese. Keep every move exactly as given in algebraic notation (Nf3, O-O, "
                "exd5) and call the pieces: king vua, queen hậu, rook xe, bishop tượng, knight mã, pawn tốt. "
                "Write the sides as Trắng and Đen with a capital letter. Say a side is losing or winning only as the "
                "evaluation says, never call a worse position balanced, and write a loss in pawns as a number "
                "followed by \"điểm\" (pawn units), not \"tốt\", which means the piece. Use no English words: say "
                "\"sai lầm nặng\" for a blunder, \"sai lầm\" for a mistake, \"nước kém chính xác\" for an inaccuracy and "
                "\"nước tốt nhất\" for the best move. Put the data's phrases in your own words, not in quotation marks, "
                "and spell \"chiếu hết\" (checkmate) with its accents. Name a bad move as a move, for example "
                "\"nước g4 là một sai lầm nặng\", never \"chơi sai lầm nặng g4\", and do not write evaluation numbers.")
    return ""


def _pawns(score):
    """A score in pawns for the model: a number, or a word for a forced mate (the analysis's mate scores are huge)."""
    if abs(score) >= MATE_THRESHOLD:
        return "forced mate for White" if score > 0 else "forced mate for Black"
    return round(score, 2)


def _prompt(move_codes, best_san, evals, marks, result, lang="en"):
    mistakes = []
    for ply, (mark, loss) in sorted(marks.items()):
        best = best_san[ply] if ply < len(best_san) else None
        mistakes.append({
            "ply": ply + 1,
            "mark": mark,
            "loss": round(loss, 2),
            "played": move_codes[ply] if ply < len(move_codes) else None,
            "best": best,
            # evals[i] is the position before move i: the one after the move is the next
            "evaluation_before": _pawns(evals[ply]) if ply < len(evals) else None,
            "evaluation_after": _pawns(evals[ply + 1]) if ply + 1 < len(evals) else None,
        })
    return (
        "You are a concise chess coach. Explain the following completed game using only "
        "the supplied Stockfish analysis. Do not invent tactics or evaluations. Mention "
        "the two most important lessons and one practical improvement. If there are no "
        "mistakes, describe one strategic strength. Evaluations are in pawns from White's point of view "
        "(positive: White is better), while loss is what the side that moved gave up. "
        "Keep the answer under 90 words. "
        "Return plain text, no headings or markdown." + _language_note(lang) + "\n\n"
        + json.dumps({"moves": move_codes, "mistakes": mistakes, "result": result},
                     separators=(",", ":"))
    )


def _fen_side(fen):
    """The side to move in a FEN. (Its move counters aren't used: GameState.toFen() always writes "0 1".)"""
    return "White" if fen.split()[1] == "w" else "Black"


def _pov_pawns(value, who):
    """A score already from the point of view of who ("the side that moved", "the player"): a number, or a word for a
    forced mate."""
    if abs(value) >= MATE_THRESHOLD:
        return "forced mate for " + who if value > 0 else "forced mate against " + who
    return round(value, 2)


def _assess(value):
    """Words for a score already from one side's point of view, so the model doesn't judge the number itself."""
    size = abs(value)
    if abs(value) >= MATE_THRESHOLD:
        return "a forced mate for this side" if value > 0 else "a forced mate against this side"
    if size < 0.3:
        return "roughly equal"
    degree = "slightly" if size < 1 else "clearly" if size < 2.5 else "decisively"
    return "%s %s" % (degree, "better" if value > 0 else "worse")


def _lost(loss, *after):
    """The pawns a move gave up, as a number, or a note when a forced mate is behind it (the number is just a cap)."""
    if loss is None:
        return None
    if any(abs(value) >= MATE_THRESHOLD for value in after):
        return "not counted: a forced mate follows"
    return round(loss, 2)


# the words of the facts in Vietnamese: a model told to write Vietnamese copies English phrases of the data otherwise
VIETNAMESE_FACTS = {
    "roughly equal": "gần cân bằng",
    "slightly better": "hơi có lợi", "clearly better": "có lợi rõ rệt", "decisively better": "có lợi áp đảo",
    "slightly worse": "hơi bất lợi", "clearly worse": "bất lợi rõ rệt", "decisively worse": "bất lợi áp đảo",
    "a forced mate for this side": "phe này có nước chiếu hết bắt buộc",
    "a forced mate against this side": "phe này bị chiếu hết bắt buộc",
    "forced mate for the side that moved": "bên vừa đi có nước chiếu hết bắt buộc",
    "forced mate against the side that moved": "bên vừa đi bị chiếu hết bắt buộc",
    "forced mate for the player": "bạn có nước chiếu hết bắt buộc",
    "forced mate against the player": "bạn bị chiếu hết bắt buộc",
    "not counted: a forced mate follows": "không tính: sau đó bị chiếu hết bắt buộc",
    "blunder": "sai lầm nặng", "mistake": "sai lầm", "inaccuracy": "nước kém chính xác",
}


def _in_language(facts, lang):
    """The facts with their English phrases in the answer's language."""
    if lang != "vi":
        return facts
    # a small score next to its words confuses the model ("hơi thua 0.1 điểm"): the assessment says it, so the plain
    # numbers of the evaluations go, keeping only the words for a mate
    return {key: VIETNAMESE_FACTS.get(value, value) if isinstance(value, str) else value
            for key, value in facts.items()
            if not (key.startswith("evaluation_") and isinstance(value, (int, float)))}


def _mover_pawns(score, white):
    """A score from White's point of view, for the side that moved."""
    return _pov_pawns(score if white else -score, "the side that moved")


def _move_prompt(data, lang="en"):
    side = _fen_side(data["fen"])
    white = side == "White"
    marks = {"??": "blunder", "?": "mistake", "?!": "inaccuracy"}
    facts = {
        "position_before_the_move": data["fen"],
        "side_that_moved": side,
        "previous_moves": data.get("history") or [],
        "move_played": data["played"],
        "engine_best_move": data.get("best"),
        "engine_best_reply_to_the_move_played": data.get("reply"),
        "evaluation_before": _mover_pawns(data["before"], white),
        "evaluation_after": _mover_pawns(data["after"], white),
        "assessment_before": _assess(data["before"] if white else -data["before"]),
        "assessment_after": _assess(data["after"] if white else -data["after"]),
        "analysis_mark": marks.get(data.get("mark")),
        "pawns_lost": _lost(data.get("loss"), data["after"]),
    }
    return (
        "You are a concise chess coach. Explain one move of a completed game to a club player, using only the "
        "supplied Stockfish analysis. Evaluations are in pawns from the point of view of the side that moved "
        "(positive: that side is better). Do not invent tactics, variations or evaluations that are not in the data; "
        "if the data doesn't show why, say what the move does in general terms. In two or three sentences, under 60 "
        "words: say what the move does. If it is the engine's best move or loses little, say why it is good; "
        "otherwise say what the best move does better and what the engine's reply to the move played takes "
        "advantage of. Say who is better only in the words of the assessment fields, and give pawns_lost only when "
        "it is a number. Return plain text, no headings or markdown." + _language_note(lang) + "\n\n"
        + json.dumps(_in_language(facts, lang), separators=(",", ":")))


def _mistake_prompt(data, lang="en"):
    side = _fen_side(data["fen"])
    facts = {
        "position": data["fen"],
        "player": side,
        "opponents_last_move": data.get("opponent"),
        "move_the_player_played": data["played"],
        "engine_best_move": data["best"],
        "engine_best_reply_to_the_move_played": data.get("reply"),
        "evaluation_of_best_move": _pov_pawns(data["score"], "the player"),
        "evaluation_after_move_played": _pov_pawns(data["after"], "the player"),
        "assessment_of_best_move": _assess(data["score"]),
        "assessment_after_move_played": _assess(data["after"]),
        "pawns_lost": _lost(data["loss"], data["after"]),
    }
    return (
        "You are a concise chess coach. The player made a mistake in their own game. Using only the supplied "
        "Stockfish analysis, explain what was wrong with the move they played and what the best move does better. "
        "Evaluations are in pawns from the player's point of view (positive: the player is better). Do not invent "
        "tactics, variations or evaluations that are not in the data; if the data doesn't show the reason, say so "
        "and describe the difference in general terms. In two or three sentences, under 60 words, speaking to the "
        "player (\"you\"). Say who is better only in the words of the assessment fields, and give pawns_lost only "
        "when it is a number. Return plain text, no headings or markdown." + _language_note(lang) + "\n\n"
        + json.dumps(_in_language(facts, lang), separators=(",", ":")))


def _hint_prompt(data, lang="en"):
    side = _fen_side(data["fen"])
    facts = {
        "position": data["fen"],
        "player_to_move": side,
        "previous_moves": data.get("history") or [],
        "suggested_move": data["best"],
        "evaluation": _pov_pawns(data["score"], "the player"),
        "assessment": _assess(data["score"]),
    }
    return (
        "You are an encouraging and insightful chess coach. The player asked for a strategic hint on their turn. "
        "Stockfish has found the suggested move. In one or two concise sentences (under 45 words), explain the "
        "strategic idea, purpose, or tactical plan behind playing this suggested move (e.g., controlling a key square, "
        "developing a piece, opening a file, creating an attack, or neutralizing an opponent threat). Speak directly "
        "to the player (\"you\"). Return plain text, no headings or markdown." + _language_note(lang) + "\n\n"
        + json.dumps(_in_language(facts, lang), separators=(",", ":")))


def prompt_for(kind, data, lang="en"):
    """The prompt for a checked request: data is the game's (moves, best, evals, marks, result) or the move's,
    mistake's, or hint's fields."""
    if kind == "move":
        return _move_prompt(data, lang)
    if kind == "mistake":
        return _mistake_prompt(data, lang)
    if kind == "hint":
        return _hint_prompt(data, lang)
    return _prompt(*data, lang=lang)


def _request_groq(prompt, tokens=TOKENS["game"]):
    key = os.environ["GROQ_API_KEY"]
    model = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
    url = os.environ.get("GROQ_API_URL", "https://api.groq.com/openai/v1/chat/completions")
    body = json.dumps({
        "model": model,
        "temperature": 0.2,
        "max_completion_tokens": tokens,
        "reasoning_effort": "low",
        "messages": [
            {"role": "system", "content": "You explain chess analysis accurately and briefly."},
            {"role": "user", "content": prompt},
        ],
    }).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:200]
        raise LLMError("Groq request failed (%d): %s" % (error.code, detail)) from error
    except (urllib.error.URLError, TimeoutError, ValueError) as error:
        raise LLMError("Groq request failed: %s" % error) from error
    try:
        text = _content_text(data["choices"][0]["message"].get("content"))
    except (KeyError, IndexError, TypeError, AttributeError) as error:
        raise LLMError("Groq returned an invalid response") from error
    return text or None


def _request(prompt, tokens=TOKENS["game"]):
    return _request_groq(prompt, tokens)


async def _request_browser(analysis):
    """Ask the site's proxy, which builds the prompt itself from this analysis (it takes no free text)."""
    if js is None:
        raise LLMError("Browser coaching is unavailable")
    js.eval(JS_HELPERS)
    request_id = "coach_" + str(id(analysis))
    js.eval("window.chessLlmRequest(%s, %s)" % (json.dumps(request_id), json.dumps(json.dumps(analysis))))
    deadline = asyncio.get_running_loop().time() + 20
    while True:
        raw = js.eval("window.chessLlmTake(%s)" % json.dumps(request_id))
        if raw:
            break
        if asyncio.get_running_loop().time() > deadline:
            raise LLMError("The coaching server didn't answer")
        await asyncio.sleep(0.05)
    try:
        reply = json.loads(str(raw))
        data = json.loads(reply["body"]) if reply["body"] else {}
        status = int(reply["status"])
    except (ValueError, TypeError, KeyError) as error:
        raise LLMError("The coaching server returned an invalid response") from error
    if status != 200:
        message = data.get("error") if isinstance(data, dict) else None
        raise LLMError(message or "The coaching server returned an error")
    text = data.get("text")
    if not isinstance(text, str):
        raise LLMError("The coaching server returned an invalid response")
    return text.strip() or None


def move_payload(lang, fen, played, history, best, reply, before, after, mark=None, loss=None):
    """What the coach is asked about one move: the position before it (fen), the move (SAN) and the ones before it,
    the analysis's best move for that position and best reply to the move played (SAN or None), and the evaluations
    before and after it, from White's point of view; mark and loss when the analysis marked it."""
    return {"kind": "move", "lang": lang, "fen": fen, "played": played, "history": list(history)[-HISTORY_PLIES:],
            "best": best, "reply": reply, "before": round(before, 2), "after": round(after, 2), "mark": mark,
            "loss": None if loss is None else round(loss, 2)}


def mistake_payload(lang, fen, opponent, played, best, reply, score, after, loss):
    """What the coach is asked about one of the player's mistakes: the position with the player to move (fen), the
    opponent's move before it, the move played and the best one (SAN), the best reply to the move played (SAN or
    None), and the scores of the best move and of the move played, for the player."""
    return {"kind": "mistake", "lang": lang, "fen": fen, "opponent": opponent, "played": played, "best": best,
            "reply": reply, "score": round(score, 2), "after": round(after, 2), "loss": round(loss, 2)}


def hint_payload(lang, fen, best, history, score=0.0):
    """What the coach is asked for a strategic hint: the position (fen), the suggested move (best), recent history,
    and the evaluation."""
    return {"kind": "hint", "lang": lang, "fen": fen, "best": best,
            "history": list(history)[-HISTORY_PLIES:], "score": round(score, 2)}


async def explain(payload):
    """Return a short explanation of a move, mistake, or strategic hint (move_payload, mistake_payload, hint_payload),
    or None when coaching is not configured."""
    if not enabled():
        return None
    if WASM:
        return await _request_browser(payload)
    kind, lang = payload["kind"], payload["lang"]
    prompt = prompt_for(kind, payload, lang)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _request, prompt, max_tokens(kind, lang))


async def explain_game(move_codes, best_san, evals, marks, result, lang="en"):
    """Return a short explanation, or None when coaching is not configured."""
    if not enabled():
        return None
    if WASM:
        return await _request_browser({
            "kind": "game", "lang": lang,
            "moves": list(move_codes), "best": list(best_san), "evals": [round(e, 2) for e in evals],
            "marks": [[ply, mark, round(loss, 2)] for ply, (mark, loss) in sorted(marks.items())],
            "result": result or ""})
    prompt = _prompt(move_codes, best_san, evals, marks, result, lang)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _request, prompt, max_tokens("game", lang))
