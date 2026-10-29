# AGENTS.md

This file provides guidance to Codex (claude.ai/code) when working with code in this repository.

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

There is no test suite or linter configured.

## Architecture

- `game/engine.py`: rules engine. `GameState` holds an 8×8 board of two-character strings (`'wK'`, `'bp'`, `'--'` for empty). It handles move generation with pin/check detection (`checkForPinsAndChecks`), castling rights, en passant, and draw detection (50-move rule, insufficient material, position keys for threefold repetition). `Move` stores a move and produces its notation. Every state change in `makeMove` must be reversed in `undoMove`, because the AI search depends on make/undo.
- `game/chessAi.py`: the AI. `findBestMove` runs NegaMax with alpha-beta pruning, and its search depth comes from the module global `DEPTH`. `main.py` sets `chessAi.DEPTH` from the difficulty dropdown (1–5 = Easy…Impossible). The evaluation is material plus piece-square tables.
- `game/main.py`: Pygame UI and the game loop (`async def main()`), covering rendering, the move log, the promotion popup, buttons and dropdowns, the mode toggle (vs AI / local 2-player / online), and handling of online messages (moves, undo requests and responses).
- `game/network.py`: the `net` singleton (`NetworkManager`). It relays messages over public ntfy.sh topics named `chess_app_multiplayer_<ROOMCODE>`. It uses one of two transports:
  - **Native:** a background thread streams from ntfy, and sends go through `urllib` on daemon threads.
  - **WASM:** JS helpers are injected with `js.eval`. Receiving uses `EventSource` SSE, and sending uses `fetch`.
  
  Incoming messages are deduplicated by ntfy message id and queued in `incoming_messages`. The main loop drains that queue with `get_messages()`.

## Constraints

- **Browser compatibility:** everything in the game loop is async. Long-running work must `await asyncio.sleep(0)` regularly, as the main loop, animations, the promotion popup, and the AI search (every 500 nodes) already do. Without this, the browser tab freezes. Don't add blocking calls, threads, or synchronous network I/O on the WASM path.
- `asyncio.run(main())` at the bottom of `main.py` is the entry point that pygbag requires.
- Sound files are `.ogg` so they work in the browser.
- `game/build/` is committed to git (Vercel rebuilds it). `__pycache__/` and `.pyc` files are ignored by `.gitignore`.
