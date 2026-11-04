# The browser's hint and analysis engine

The browser build plays the computer's moves with stockfish.js 19's lite engine (from unpkg), but hints and the
analysis after a game use a newer Stockfish that no package ships: **Stockfish dev-20261028-ff7cee42**, with the
NNUE architecture **SFNNv19** (net `nn-d1ee674a62ca.nnue`). There is no lite net for SFNNv19, so this is the full
engine: one 137 MB `.wasm`, split into six parts that the loader fetches and joins.

Vercel can't compile it, so it is built here once and published as the GitHub release
[`stockfish-dev-20261028-wasm`](https://github.com/congduytran12/Chess-Playing-AI/releases/tag/stockfish-dev-20261028-wasm),
and `npm run build` downloads it into `game/build/web/stockfish/` (`HINT_WORKER_URL` in `game/stockfish.py`).
The release also holds the complete corresponding source (GPL v3).

## Rebuilding

```bash
tools/stockfish-wasm/build.sh            # Linux or WSL, Emscripten 6.0.9 active; output in tools/stockfish-wasm/work/out
```

It takes the official dev source and stockfish.js 19.0.1's build system (both pinned in the script), applies
`stockfish-wasm.patch` and runs `node build.js --single-threaded --split=6`. The output is byte for byte the
release's (`SHA256SUMS.txt`).

`stockfish-wasm.patch` is stockfish.js 19.0.1's WebAssembly changes to Stockfish 19, with the lite-net code
removed, merged onto the dev source (Stockfish 19 as the base). Besides adding the glue (`src/emscripten/`,
`glue.*`), it resolves the merge's conflicts by keeping dev's code with the `__EMSCRIPTEN__` changes around it,
and raises `INITIAL_MEMORY` to 192 MiB, which the larger net needs.

A build was checked by fixed-depth searches: it visits exactly the same nodes as the native dev build, and it
loads and plays in Chromium, Firefox and WebKit.

## Moving to a newer Stockfish

Merge stockfish.js's changes onto the new source the same way, rebuild, publish the files under a new release tag,
and change the tag, file names and part count in `package.json`, `HINT_WORKER_URL` / `HINT_WORKER_PARTS` and
`tests/test_stockfish.py` together.
