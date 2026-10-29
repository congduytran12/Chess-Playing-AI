# AGENTS.md

This file provides guidance to Codex when working with code in this repository.

## Overview

Pygame chess game with a NegaMax/alpha-beta AI, local hotseat, and online multiplayer. It runs natively on desktop and in the browser via pygbag (Python compiled to WebAssembly), deployed on Vercel.

## Commands

Run the desktop game. It must be run from inside `game/`, because assets load by relative path (`sounds/...`, `images/...`) and modules import each other as top-level modules (`from engine import ...`), not as a package:

```bash
cd game
pip install -r requirements.txt   # pygame==2.1.2, pygbag
python main.py
```

Build the web (WASM) bundle. This is what Vercel runs. The output goes to `game/build/web`:

```bash
npm run build
```

The build pins pygbag 0.9.3. It also downloads the pygbag runtime JS files locally and uses `sed` to rewrite `index.html` so the page loads them from the local copies instead of the CDN. Keep those versions in sync if you change one.

Run the tests from the repository root (standard library `unittest`, no extra packages; the account API tests need `flask` and `requests`, and the UI tests need `pygame`):

```bash
python -m unittest discover -s tests
```

They cover move generation (perft counts), the AI search, PGN, network message handling, the hint and settings storage, the account API against an in-memory Supabase stand-in, and the game loop itself, run headless with scripted clicks. There is no linter configured.

## Architecture

- `game/engine.py`: rules engine. `GameState` holds an 8×8 board of two-character strings (`'wK'`, `'bp'`, `'--'` for empty). It handles move generation with pin/check detection (`checkForPinsAndChecks`), castling rights, en passant, and draw detection (50-move rule, insufficient material, position keys for threefold repetition). `Move` stores a move, including its `promotionChoice`. Game moves go through `makeMoveWithSan`, which records standard algebraic notation in `move.san`; `findMoveBySan` parses it back. The AI search calls plain `makeMove`. Every state change in `makeMove` must be reversed in `undoMove`, because the AI search depends on make/undo.
- `game/chessAi.py`: the AI.
  - **Search:** `searchPosition()` runs NegaMax with alpha-beta pruning by iterative deepening until a time budget runs out, then returns the best move of the last finished depth. It adds quiescence search over captures and promotions, check extensions, a transposition table keyed by `GameState.getPositionKey()`, killer and history move ordering, null move pruning (`makeNullMove` passes the turn, and must be undone even on a timeout), late move reductions, and repetition detection against the game's position history. A depth cut off by the clock still contributes the best move it found so far.
  - **Levels:** `findBestMove()` plays from the opening book (`BOOK_LINES`, built on first use) while it can. After that it searches with the settings in `LEVELS[LEVEL]`: time, depth cap, and root noise that makes the lower levels beatable. `main.py` sets `chessAi.LEVEL` from the difficulty dropdown.
  - **Responsiveness:** the search raises `SearchTimeout` when time runs out, and the caller undoes back to the root. It yields to the browser every `YIELD_SECONDS`.
  - **Evaluation:** `scoreBoard()` counts material plus piece-square tables, with a king table that switches for the endgame. It returns a score in pawns, positive when White is better.
- `game/main.py`: Pygame UI and the game loop (`async def main()`), covering rendering, the move log, the promotion popup, the mode toggle (vs AI / local 2-player / online), clocks, hints, resign and draw offers, review and analysis after the game, and online sync (see below). `panelLayout()` defines the side panel's controls, and both click handling and drawing use it. Nested helpers inside `main()` own the shared state changes: `resetGame`, `playMove` (every move of the game goes through it), and `takeBack`. All three call `clearReview()`, which leaves the review of a finished game and cancels its analysis. After the game, `reviewTo(ply)` replays the moves onto `reviewGs` for display. `analyzeGame()` runs as a background asyncio task on its own `GameState`, searching each position for `ANALYSIS_SECONDS`. `moveMarks()` turns the score drops into `??`/`?`/`?!` marks.
- `game/pgn.py`: PGN export and parsing, and saving and loading files. Desktop uses a tkinter file dialog and falls back to a `saved_games/` folder. In the browser, `js.eval` helpers trigger a download or a file picker, and the picked file's text is polled each frame.
- `game/settings.py`: the player's preferences (board colors `BOARD_THEMES` and piece style `PIECE_SETS` in `main.py`), stored like the hint count. The Settings window (gear button) is drawn by `drawSettingsWindow()`.
- `game/hints.py`: the daily hint limit (`HINTS_PER_DAY`), counted per device in `localStorage` or `~/.chess-playing-ai-hints.json` and reset at local midnight. `main.py` counts a hint with `hints.use()` once it is shown.
- `game/network.py`: the `net` singleton (`NetworkManager`). It relays messages over public ntfy.sh topics named `chess_app_multiplayer_<ROOMCODE>`. It uses one of two transports:
  - **Native:** a background thread streams from ntfy, and sends go through `urllib` on daemon threads.
  - **WASM:** JS helpers are injected with `js.eval`. Receiving uses `EventSource` SSE, and sending uses `fetch`.
  
  Incoming messages are deduplicated by ntfy message id and queued in `incoming_messages`. The main loop drains that queue with `get_messages()`. `save_session`/`load_session` remember the last room and role for the Rejoin button. The browser keeps them in `localStorage`; desktop keeps them in `~/.chess-playing-ai-session.json`.

### Online sync protocol

Online games sync whole game states, not single events, so lost messages and rejoins recover on their own:

- **State messages:** every change to the game (move, accepted undo, resignation, accepted draw, new game) bumps `onlineVersion` and sends a `state` message. It holds the game number, a random game id (`gid`, shared by both players and used to match their rating reports), the version, the full move list in coordinate notation (`Move.getCode`, e.g. `e2e4 e7e8n`), the time control, the clocks, and the result. Use `publishChange()` for local changes. Only a new game bumps `onlineGame` and resets the version to 0.
- **Receiving:** the newest state in a batch is compared by `(game, version)`. A newer state is adopted by `adoptState()`, which undoes back to the common moves and replays the rest. An older state means the sender is behind, so we send ours back, rate-limited by `SYNC_REPLY_MS`. Equal versions that disagree are settled in favour of the host.
- **Heartbeats:** the side waiting for the opponent (or both, after the game) re-sends its state every `HEARTBEAT_MS`, so a dropped message can't leave both players waiting.
- **Presence:** a player who has sent nothing for `PRESENCE_MS` sends a `ping`. `network.py` stamps every incoming message with ntfy's server time (`_time`) and keeps the room's latest in `net.server_time`; `presenceStatus()` compares the opponent's latest message with it, so the two players' clocks never matter and old messages replayed on joining don't count as presence.
- **Joining and rejoining:** connecting sends `sync_request`, and the ntfy backlog (`since=30m`) replays older states.
- **Requests and offers:** `undo_request`, `draw_offer`, `undo_declined` and `draw_declined` are transient. They only count when they come from the opponent's role about the current `(game, version)`, which also skips stale ones in the backlog.
- `api/account.py`: a Flask function at `/api/account` for player accounts (register, login, refresh, me, save_game, games, game, report_online, leaderboard). Each request is a POST with an `action` field, and signed-in actions carry an access `token`. It talks to Supabase with `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` (Vercel environment variables) using plain `requests`: GoTrue for auth and PostgREST for data.
  - **Schema:** in `supabase/schema.sql`. Row level security is on with no policies, so the tables are reachable only through this function.
  - **Ratings:** `report_online` counts an online result only when both players report the same result for the same game id. The SQL function `apply_rated_game` applies it once per game, and at most 3 rated games per pair of players in 24 hours.
- `game/account.py`: the client side, the `account` singleton.
  - **Requests:** non-blocking. In the browser they use `fetch` and are polled each frame; on desktop they run on an executor thread.
  - **Server:** the browser build calls its own site; desktop calls `https://chess-playing-ai.vercel.app` (override with `CHESS_API_URL`).
  - **Sign-in:** the refresh token is kept in `localStorage` or `~/.chess-playing-ai-account.json`.
  - **In `main.py`:** account work runs through `startRequest()`, and finished requests are handled once per frame. The account window is drawn by `drawAccountWindow()`, with `accountLayout()` as its layout. The How to play window (`H` key or the panel button) works the same way: `drawHelpWindow()` draws the page of `HELP_PAGES` in `helpPage`; keep its text in step with the game's features. Finished games are saved automatically by `saveFinishedGame()`, which also reports online results. Online messages carry a `player` field (uid, name, rating) when the sender is signed in.

Server tests aren't in the repo. The account API was tested against an in-memory imitation of Supabase; anything touching the schema needs a real Supabase project to verify.

## Constraints

- **Browser compatibility:** everything in the game loop is async. Long-running work must `await asyncio.sleep(0)` regularly, as the main loop, animations, the promotion popup, and the AI search (at least every `YIELD_SECONDS`) already do. Without this, the browser tab freezes. Don't add blocking calls, threads, or synchronous network I/O on the WASM path.
- `asyncio.run(main())` at the bottom of `main.py` is the entry point that pygbag requires.
- Sound files are `.ogg` so they work in the browser.
- `game/build/` is committed to git (Vercel rebuilds it). `__pycache__/` and `.pyc` files are ignored by `.gitignore`.
