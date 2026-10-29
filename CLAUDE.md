# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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
- `game/main.py`: Pygame UI and the game loop (`async def main()`), covering rendering, the move log, the promotion popup, the mode toggle (vs AI / local 2-player / online), clocks, hints, resign and draw offers, review and analysis after the game, and online sync (see below). `panelRows()` names the side panel's controls row by row, `panelLayout()` turns them into rects, and both click handling and drawing use it. The bottom row is always Undo, Restart, Account and the menu (a narrow three-line icon button, `CONTROL_WEIGHTS`); the menu's items are `MENU_ITEMS` (Save/Load PGN, Flip board, Settings, How to play), laid out by `menuItemRects()` upwards from its button, drawn last like dropdown options by `drawMenu()`, and run by the nested `menuAction(name)`. Online without a room there is no game: the Resign/Offer Draw row is left out, Undo is disabled and the board doesn't take moves. The board's orientation `flip_board` is worked out every frame (Black at the bottom for the online guest and when playing Black against the computer) and then turned around when `boardFlipped` is set (F or the menu; `resetGame` clears it); everything that draws or clicks the board takes that `flip_board`. Nested helpers inside `main()` own the shared state changes: `resetGame`, `playMove` (every move of the game goes through it), and `takeBack`. All three call `clearReview()`, which leaves the review (or looking back) and cancels the analysis. `reviewTo(ply)` replays the moves onto `reviewGs` for display, during the game too (looking back: arrow keys, Home/End, a click on a move in the log). While looking back in a live game, `drawLookBackBanner()` shows `lookBackText()` across the top of the board, a board click only returns (`reviewTo(len(gs.moveLog))`), the clocks keep running and the log highlights the shown move; any new move returns through `playMove`, and a game that ends meanwhile returns to show its result (`wasGameOver`). `analyzeGame()` runs as a background asyncio task on its own `GameState`, searching each position for `ANALYSIS_SECONDS`. `moveMarks()` turns the score drops into `??`/`?`/`?!` marks.
- `game/pgn.py`: PGN export and parsing, and saving and loading files. Desktop uses a tkinter file dialog and falls back to a `saved_games/` folder. In the browser, `js.eval` helpers trigger a download or a file picker, and the picked file's text is polled each frame.
- `game/settings.py`: the player's preferences, stored like the hint count. `settings.get(name)` falls back to `DEFAULTS` (board, pieces, uiTheme, coordinates, moveMarkers, lastMove, animation, figurines, sound, volume, premoves, seenHelp). In `main.py`, `settingValue(name)` also replaces a saved value that isn't a valid choice.
  - **Settings window** (menu > Settings): two tabs, Board and Game, laid out by `settingsLayout(tab)` from `SETTINGS_ROWS`. Switches are `SETTING_CHOICES` (rects named `'<setting>:<choiceId>'`, e.g. `'coordinates:off'`, `'animation:fast'`), drawn as `drawSegment()` buttons. `settingsClick(location, tab)` applies a choice and returns the tab to show (None closes); `settingsKey()` handles Esc and Tab. `main()` keeps the open tab in `settingsTab`.
  - **What reads them:** `drawSquare` (coordinates), `drawMoveMarkers` (moveMarkers), `drawGameState` (lastMove), `animationDuration()` (animation, `ANIMATION_SPEEDS`; 0 skips the slide), and `applySoundSettings()` (sound and volume, through `Sound.set_volume` on `SOUNDS`). `premoves` is read by `premoveTurn()`; `figurines` is stored but not used yet.
- **Tooltips and the cursor (in `main.py`):** each frame the nested `pointerTarget()` finds what the pointer is over, topmost first, as (id, tooltip, clickable). Clickable gives the hand cursor through `setCursor()`. A tooltip shows after `TOOLTIP_DELAY_MS` on the same id and hides on a click. Texts: `TOOLTIPS` / `tooltipText()` for enabled panel controls, `disabledReason(name, ...)` for disabled ones (also shown in the status slot when a disabled control is clicked), `SETTING_TIPS` for the Settings labels. A new panel control or menu item needs an entry in `TOOLTIPS`, and in `controlStates()` and `disabledReason` if it can be disabled (menu items are looked up by the same names). While a menu, dropdown or window is open, the panel's buttons don't show hover.
- **UI look (in `main.py`):** the side panel and windows take every color from the live dict `UI`, filled by `setUiTheme(name)` from `PALETTES['light' | 'dark']` (keys listed above `PALETTES`; add a key to both themes). Never hard-code a panel or window color; the board keeps `BOARD_COLORS`, and the promotion picker and the dark result card keep their own colors. Text: `get_font(size, bold, sans)`; titles and body text use the bundled serif, button labels `sans=True` (pygame's default font, already bold). Buttons go through `drawButton()` (rounded, hover, a pressed look from `MOUSE_HELD`, optional `color=`, `textColor=` and label `size=`). The panel's rows come from `panelRows()`, and `evenLabelSizes()` gives each row one label size, the largest at which all its labels fit.
- **Moving on the board (in `main.py`):** a move is two clicks or a drag. The nested async `tryMove(start, end, slide)` is the one path for both (promotion picker, `playMove`, online publish); it returns 'played', 'cancelled', 'refused' or None. A left press on an own piece (`canDrag()`: the player's turn, live position) arms `drag` = {'square', 'pressPos', 'active'}; it becomes active after `DRAG_THRESHOLD` px of MOUSEMOTION with the button held, and MOUSEBUTTONUP drops it (`dropPiece()`: a legal square plays without the slide, anywhere else puts it back, still selected). Until then a press is an ordinary click, so click-click is unchanged. Esc or the right button cancels a drag; `takeBack` and `resetGame` clear it, and each frame drops it when `canDrag` fails (the piece was captured, looking back) or a window opens. `playMove` keeps it, so a piece picked up for a premove can be dropped as a move once the opponent has moved. While active, `drawGameState(..., hidden=square)` leaves the piece out and `drawDraggedPiece()` draws it under the pointer after the side panel, below the overlays. A move the piece could make that leaves the king in check gets `refusalReason(gs, start, end)` in the status slot and `kingFlash` (`drawKingFlash`, `KING_FLASH_MS`). The right button draws the player's marks and arrows (`rightPress()` / `rightRelease()`, `boardRings` / `boardArrows`, colors from `annotationColor(mods)` and `ANNOTATION_COLORS`, toggled by `toggleAnnotation`); `rightPress` cancels a drag first, then a premove. `clearAnnotations()` runs on a left click on the board, in `playMove` / `takeBack` / `resetGame` and in `reviewTo`. `drawArrow(screen, start, end, flip, color=ARROW_COLOR)`; `drawGameState` takes arrows as (start, end) or (start, end, color), plus `rings`, `flash` and `premove`.
- **Premoves (in `main.py`, setting `premoves`):** vs the computer and online in a room, while the opponent is to move (`premoveTurn()`), a click or drag picks one move from `premoveMoves(gs)` (the moves that would be legal if it were the player's turn: no en passant, cached per position by `premoveCandidates()`) into `premove` = (start, end), through `choosePremove()` / `setPremove()`. It is drawn as `PREMOVE_COLOR` tints (`drawGameState(..., premove={'squares', 'moves'})`), the piece staying on its square. Right button, Esc or a click on the premoved piece cancel it (`cancelPremove()`); `resetGame`, `takeBack`, game over and switching the setting off clear it. In the frame after the opponent's move has been played and shown, `resolvePremove(premove, validMoves)` gives the legal move to play through `tryMove(..., promotion='Q')` (which also publishes online), or None: then `PREMOVE_DROPPED` shows in the status slot.
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
  - **In `main.py`:** account work runs through `startRequest()`, and finished requests are handled once per frame. The account window is drawn by `drawAccountWindow()`, with `accountLayout()` as its layout. The How to play window (`H` key or the menu) works the same way: `drawHelpWindow()` draws the page of `HELP_PAGES` in `helpPage`; keep its text in step with the game's features. Finished games are saved automatically by `saveFinishedGame()`, which also reports online results. Online messages carry a `player` field (uid, name, rating) when the sender is signed in.

Server tests aren't in the repo. The account API was tested against an in-memory imitation of Supabase; anything touching the schema needs a real Supabase project to verify.

## Constraints

- **Browser compatibility:** everything in the game loop is async. Long-running work must `await asyncio.sleep(0)` regularly, as the main loop, animations, the promotion popup, and the AI search (at least every `YIELD_SECONDS`) already do. Without this, the browser tab freezes. Don't add blocking calls, threads, or synchronous network I/O on the WASM path.
- `asyncio.run(main())` at the bottom of `main.py` is the entry point that pygbag requires.
- Sound files are `.ogg` so they work in the browser.
- `game/build/` is committed to git (Vercel rebuilds it). `__pycache__/` and `.pyc` files are ignored by `.gitignore`.
