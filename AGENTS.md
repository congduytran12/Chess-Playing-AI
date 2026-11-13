# AGENTS.md

This file provides guidance to Codex when working with code in this repository.

## Overview

Pygame chess game with a NegaMax/alpha-beta AI (and Stockfish when available), local hotseat, online multiplayer, puzzles and accounts. It runs natively on desktop and in the browser via pygbag (Python compiled to WebAssembly), deployed on Vercel. The code is the reference for details; this file keeps what is not obvious from it.

## Commands

Run the desktop game from inside `game/` (assets load by relative path, and modules import each other as top-level modules, not as a package):

```bash
cd game
pip install -r requirements.txt   # pygame==2.1.2, pygbag
python main.py
```

Build the web bundle (what Vercel runs; output in `game/build/web`):

```bash
npm run build
```

The build pins pygbag 0.9.3, downloads the browser Stockfish engines into `game/build/web/stockfish/` (stockfish.js 19.0.1 lite for the computer from unpkg; the full threaded build for hints, whose `.wasm` it splits into four parts; the dev-20261028 hint/analysis engine from this repo's GitHub release `stockfish-dev-20261028-wasm`, built by `tools/stockfish-wasm/build.sh`, see its README), downloads the pygbag runtime locally and rewrites `index.html` with `sed` to load it from there. Keep those versions in sync with `WORKER_URL`, `HINT_WORKER_URL` and `HINT_THREADED_URL` in `game/stockfish.py` if you change one.

Run the tests from the repository root (standard library `unittest`; the account API tests need `flask` and `requests`, the UI tests `pygame`). On this machine see the running-tests memory: PATH python is broken.

```bash
python -m unittest discover -s tests
```

`tests/support.py` sets `CHESS_NO_STOCKFISH=1`, so tests play `chessAi`'s moves whether or not Stockfish is installed; `tests/test_stockfish_real.py` runs only when a real Stockfish is found. There is no linter.

End-to-end check for online play (about 80 s; needs `pygame`, `flask`, `requests`):

```bash
python tools/e2e_online.py [--games N]
```

It runs two clients through scripted games against local stand-ins (an ntfy relay via `CHESS_NTFY_URL`, the real `api/account.py` on an in-memory Supabase via `CHESS_API_URL`) and reports whether both agree and what the rating server counted. It reads the game through `main.GAME_VIEW`.

## Architecture

- `game/engine.py`: rules engine. `GameState` holds an 8×8 board of two-character strings (`'wK'`, `'bp'`, `'--'`). Move generation with pin/check detection, castling, en passant, draw detection (50-move, insufficient material, position keys for repetition). Game moves go through `makeMoveWithSan` (sets `move.san`; `findMoveBySan` parses it); the AI search calls plain `makeMove`. **Every state change in `makeMove` must be reversed in `undoMove`**, because the search depends on it. `fromFen` / `toFen` set up and write positions (`startFen`). `CLOCK_OPTIONS` lists the clock presets (`5+3` = minutes + seconds per move).
- `game/stockfish.py`: the `engine` singleton speaks UCI to Stockfish: stockfish.js in a Web Worker in the browser (polled through `js.eval`), a native executable on desktop (`STOCKFISH_PATH`, PATH, or the git-ignored `engines/`). `hintEngine` is a second, stronger engine for hints and analysis (threaded build where the page is cross-origin isolated, see `vercel.json`'s COOP/COEP headers; falls back to single-threaded via `_useSingleThreaded()` on failure). `main()` calls `engine.start()` once and `prepareHintEngine()` after sign-in (caches the `.wasm` parts in Cache Storage). `findBestMove` (level-limited by `LEVEL_ELO`), `searchPosition`, `searchHintPosition`, `analyzePosition` and `evaluate` have `chessAi`'s shapes and fall back to `chessAi` when Stockfish isn't ready within `READY_WAIT` or fails. One search runs at a time; `go` puts `searchmoves` last. Positions go as `position startpos moves ...` (or `position fen <startFen> moves ...`) so Stockfish sees repetitions. `vercel.json` keeps `game/build/**` out of the account function (`excludeFiles`) or the deployment exceeds the size limit.
- `game/chessAi.py`: the game's own AI, used when Stockfish isn't there: iterative-deepening NegaMax with alpha-beta, quiescence, check extensions, transposition table, killer/history ordering, null move pruning (`makeNullMove` must be undone even on timeout), LMR and repetition detection. `findBestMove()` plays from the opening book (`BOOK_LINES`) then searches with `LEVELS[LEVEL]` (time, depth cap, root noise); `main.py` sets `chessAi.LEVEL`. The search raises `SearchTimeout` and the caller undoes back to the root; it yields to the browser every `YIELD_SECONDS`. `scoreBoard()` is material plus piece-square tables, in pawns, positive for White.
- `game/main.py`: the Pygame UI and game loop (`async def main()`): rendering, move log, promotion popup, modes (vs AI / local / online / puzzles / your mistakes), clocks, hints, resign and draw offers, review and analysis, online sync. Nested helpers in `main()` own shared state changes: `resetGame`, `playMove` (every move goes through it), `takeBack`, `tryMove` (the one path for click and drag moves). Things worth knowing:
  - **Side panel:** `panelRows()` names the controls row by row, `panelLayout()` turns them into rects; clicks and drawing both use them. A new panel control or menu item needs an entry in `TOOLTIPS`, and in `controlStates()` and `disabledReason` if it can be disabled. `pointerTarget()` finds what the pointer is over (tooltip and cursor).
  - **Layouts:** `Layout('landscape')` (desktop always; `WINDOW_SIZE`) or `Layout('portrait', ...)` (a browser window taller than wide), picked by `layoutFor(browser.viewportSize())`. Code that places the board or panel reads `LAYOUT` and sizes go through `scaled(n)`. The board draws on `boardSurface` in its own coordinates (`toBoard()`, `onBoard()`). Windows keep a board-sized layout and are scaled in portrait (`drawWindow`, `windowPos()`).
  - **Theme:** every panel/window color comes from the live dict `UI` (`setUiTheme`, `PALETTES['light'|'dark']`; add a key to both). Never hard-code one; the board keeps `BOARD_COLORS`. `UI['textDim']` must keep 4.5:1 contrast (a test checks it). Buttons go through `drawButton()`; fonts through `get_font(size, bold, sans)`.
  - **Desktop window:** resizable and scaled; the game always draws at `WINDOW_SIZE`. The `_sdl2.video.Window` must stay referenced in `DESKTOP_WINDOW` (dropping it crashes on the first event). Pointer events read `pointerPos()`, which ignores clicks in the black bars.
  - **Review and analysis:** `reviewTo(ply)` replays moves onto `reviewGs` (also while looking back in a live game); `clearReview()` is called by `resetGame`, `playMove` and `takeBack`. `analyzeGame()` is a background task; `moveMarks()` turns score drops into `??`/`?`/`?!`.
  - **Premoves, drag, annotations, sounds, "Your move" alert:** all in `main.py` (`premoveTurn()`, `drag`, `boardRings`/`boardArrows`, `SOUNDS`/`playSound(name)`, `turnArrived()`). Every sound goes through `playSound`, which respects settings and never raises.
  - **Text fields:** `game/textfield.py` has `TextField`; `main.py` draws them with `drawTextField`. Account forms use `accountFields`, the room box `roomField`. In the browser, pastes are polled with `browser.takePastedText()`, and a phone's on-screen keyboard works through a hidden `<input>` kept by `browser.py` (`keyboardSync` / `keyboardTake`); it is hard to check without a device.
  - **Account window:** views `ACCOUNT_FORMS`, 'profile', 'games', 'leaderboard', laid out by `accountLayout()`. Requests run through `startRequest()` and are handled once per frame. Finished games are saved by `saveFinishedGame()`, which also reports online results. A password-reset email link (`resetLinkFromHash`) opens 'newPassword'; error text from such a link is never shown.
  - **How to play:** `HELP_PAGES` / `helpPageLayout()`; keep its text in step with the game's features. It opens by itself on the first visit (setting `seenHelp`); the UI tests store `seenHelp` True.
  - **Invite links and chat:** the host's Copy link puts `?room=CODE` on the clipboard; a page opened with it asks to join as Black (`pendingPrompt` `'joinInvite'`). Quick chat sends an index into `QUICK_CHAT`, never typed text.
- `game/browser.py`: browser-only features with desktop fallbacks, each returning a plain value and never raising (`inBrowser`, `pageHidden`, `setTitle`, `copyText`, `takePastedText`, `queryParam`, `locationHash`, `siteUrl`, `viewportSize`, `touchScreen`, ...). The URL helpers are pure functions so they can be tested anywhere.
- `game/pgn.py`: PGN export/parsing and file save/load (tkinter dialog on desktop with a `saved_games/` fallback; `js.eval` download and picker in the browser).
- `game/settings.py`: preferences (`settings.get(name)` falls back to `DEFAULTS`; `settingValue(name)` in `main.py` also rejects invalid saved values). The Settings window (menu > Settings) is laid out by `settingsLayout(tab)` from `SETTING_CHOICES`/`SETTINGS_ROWS`.
- `game/puzzles.py` / `puzzles.txt`: the Puzzles mode (Lichess puzzle database, CC0, picked by `tools/make_puzzles.py`; `id|FEN|moves|rating|themes`). Rating, streak and solved list are kept in localStorage or `~/.chess-playing-ai-puzzles.json`. In `main.py` the frame calls `puzzleStep()`.
- `game/mistakes.py`: Your mistakes, the player's own `??`/`?` moves from analyzed games as puzzles, run by the same code as Puzzles (`PUZZLE_MODES`). Mistakes are stored through the account API; `puzzleStep()` judges alternatives to the best move with `judgeAlternative()`.
- `game/i18n.py`, `game/lang_vi.py`: English and Vietnamese. Texts are written in English in the code; `i18n.tr(text)` translates (`EXACT` for whole texts, `TEMPLATES` for texts with `%s`/`%d`/...). `get_font()` hands out `LocalFont`s whose `render()`/`size()` translate, and `wrapText()` translates before cutting lines, so most drawn text needs no explicit `tr`. A composite text built in code needs a template. **When adding a text, add its Vietnamese to `lang_vi.py`**; `tests/test_i18n.py` fails for a missing translation in the game's tables and checks help pages fit. The UI tests pin the language to English.
- `game/hints.py`: the daily hint limit (`HINTS_PER_DAY`), counted per device and reset at local midnight. Premium accounts (and admins) have unlimited, uncounted hints.
- `game/network.py`: the `net` singleton relays messages over public ntfy.sh topics `chess_app_multiplayer_<ROOMCODE>`. Native uses a background thread (`CHESS_NTFY_URL` overrides the server; tests and the e2e tool use that), WASM uses `EventSource` and `fetch` through `js.eval`. Incoming messages are deduplicated by ntfy id and drained by `get_messages()`. `save_session`/`load_session` remember the last room for Rejoin.
- `game/account.py`: the client for `api/account.py`, the `account` singleton. Requests are non-blocking (`fetch` polled each frame in the browser, an executor thread on desktop). The browser build calls its own site; desktop calls `https://chess-playing-ai.vercel.app` (override with `CHESS_API_URL`).
- `api/account.py`: a Flask function at `/api/account` (register, login, refresh, recover, set_password, me, save_game, games, game, report_online, leaderboard, save_mistakes, mistakes, mistake_result). Each request is a POST with an `action` field; signed-in actions carry an access `token`. It talks to Supabase (`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`) with plain `requests`: GoTrue for auth, PostgREST for data. The schema is `supabase/schema.sql` (re-runnable: it only adds what is missing; row level security is on with no policies, so tables are reachable only through this function). Premium is given by hand in SQL for now (`premium_until`). `report_online` counts a result only when both players report the same result for the same game id, after replaying the moves with `game/engine.py` (`checkGame()`, listed in `vercel.json`'s `includeFiles`); a game with a hint isn't reported by the player who used it, so it isn't rated.

### Online sync protocol

Online games sync whole game states, not single events, so lost messages and rejoins recover on their own.

- **State messages:** every change (move, accepted undo, resignation, accepted draw, new game) bumps `onlineVersion` and sends a `state` message with the game number, a game id (`gid`), the version, the full move list in coordinate notation (`Move.getCode`), time control, clocks, result and `hw` (the host plays White; a Rematch flips it). Use `publishChange()` for local changes. Only a new game bumps `onlineGame` and resets the version.
- **Receiving:** anyone with the room code can post, so nothing received may stop the game. Only states passing `wellFormedState()` count, `player` info goes through `onlinePlayerInfo()`, and the newest state from the opponent's role is compared by `(game, version)` and accepted only if `judgeState()` finds it a step the opponent can really have taken (legal moves, only their own moves added, takebacks only after our `undoAsked`, a result only from their resignation, a draw we offered, or a time-out the clocks show). We take everything as it is only when joining. `adoptState()` undoes back to the common moves and replays the rest; our own clock is never taken from a state. An older state means the sender is behind, so we send ours back (rate-limited). Equal versions that disagree are settled for the host.
- **Heartbeats and presence:** the side waiting re-sends its state every `HEARTBEAT_MS`, backing off when nobody answers (`heartbeatInterval()`), because the message service rate-limits. A player silent for `PRESENCE_MS` sends a `ping`; the opponent is taken for gone after `OPPONENT_GONE_SECONDS`. Presence compares ntfy's server time (`_time`, `net.server_time`), never the players' clocks.
- **Joining:** connecting sends `sync_request`; the ntfy backlog replays older states, and our own `sync_request` coming back marks where history ends (`joinedAt`, `caughtUp`). Chats and joined-before messages from the backlog are ignored (`incomingChat()`).
- **Requests and offers:** `undo_request`, `draw_offer`, `undo_declined` and `draw_declined` are transient and count only from the opponent's role about the current `(game, version)`.

Server tests aren't in the repo. The account API was tested against an in-memory imitation of Supabase; anything touching the schema needs a real Supabase project to verify.

## Constraints

- **Browser compatibility:** everything in the game loop is async. Long-running work must `await asyncio.sleep(0)` regularly (at least every `YIELD_SECONDS` for the AI search), or the browser tab freezes. Don't add blocking calls, threads or synchronous network I/O on the WASM path.
- `asyncio.run(main())` at the bottom of `main.py` is the entry point pygbag requires.
- Sound files are `.ogg` so they work in the browser. The short alert sounds are synthesized by `tools/make_sounds.py` (needs numpy and soundfile); rerun it to change them.
- `game/build/` is committed to git (Vercel rebuilds it). `__pycache__/` and `.pyc` files are ignored.
