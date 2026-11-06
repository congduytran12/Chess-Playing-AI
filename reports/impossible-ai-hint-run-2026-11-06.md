# Impossible AI, 10 games with the threaded Hint on the Vercel build

**Date:** 2026-11-06
**Site:** https://chess-playing-ai.vercel.app/. It runs commit `6382e3c`, which includes `f055525`, "Threaded Stockfish for hints where the page can run threads". The live page has `HINT_THREADED_URL`, and the site sends COOP `same-origin` and COEP `credentialless`.
**Account:** congduytran12 (admin, so Hint is unlimited and uncounted)
**Settings:** Local vs AI, AI "Impossible", no clock. The sides alternate: odd-numbered games as White, even-numbered games as Black.

## Method

A headless Chromium (Playwright 1.58) drove the live page at 1280×800, signing in through the game's own form. On each of my turns it clicked **Hint**, read the hinted move from `GAME_VIEW['hintMove']`, and played exactly that move with two clicks. **I made no move of my own: all 849 of my moves were the Hint's move.** After each game it waited for "Game saved to your account", then pressed Switch sides on the result card.

| | Engine | Threads / hash | Time per move |
|---|---|---|---|
| **Hint** | Stockfish 19 WASM Multithreaded (`stockfish-19.js`, 4 × 25 MB parts) | 8 threads, 128 MB | 5 s (`HINT_SECONDS`) |
| **Impossible AI** | Stockfish 19 Lite WASM | 1 thread, 16 MB | 5 s, full strength |

What the page reported: `crossOriginIsolated` true, 12 cores, `deviceMemory` 8, so `browserThreads()` = 8, `hintHash()` = 128, and `smallDevice()` false.

## Results

| # | Side | Result for me | Plies | Time (min) | Hints | Avg hint (s) | Max hint (s) | How it ended |
|---|------|---------------|------:|-----------:|------:|-------------:|-------------:|--------------|
| 1 | White | **Win** | 201 | 18.5 | 101 | 5.09 | 5.58 | Checkmate (1-0) |
| 2 | Black | Draw | 259 | 25.3 | 129 | 5.44 | 5.61 | 50-move rule |
| 3 | White | Draw | 245 | 24.1 | 123 | 5.43 | 5.65 | Stalemate |
| 4 | Black | Draw | 194 | 19.0 | 97 | 5.42 | 5.60 | Insufficient material |
| 5 | White | Draw | 79 | 7.6 | 40 | 5.46 | 5.60 | Threefold repetition |
| 6 | Black | Draw | 153 | 15.0 | 76 | 5.46 | 5.58 | Insufficient material |
| 7 | White | Draw | 167 | 16.4 | 84 | 5.43 | 5.57 | Insufficient material |
| 8 | Black | Draw | 226 | 21.9 | 113 | 5.43 | 5.57 | Insufficient material |
| 9 | White | Draw | 101 | 10.0 | 51 | 5.45 | 5.54 | Threefold repetition |
| 10 | Black | Draw | 70 | 6.9 | 35 | 5.46 | 5.65 | Threefold repetition |

**Total: 1 win, 9 draws, 0 losses (5.5 / 10).**

- **Length:** 1,695 plies, 165 minutes of play.
- **Hints:** 849, all from the threaded engine. None came from the single-threaded build or a fallback, and `threadedFailed` stayed False.
- **Hint time:** 5.40 s on average, at most 5.65 s. These times include about 0.3 s of the driver's polling. The few hints under 1 s came at the end of game 1, where the engine found a forced mate and its search reached full depth early.
- **The AI** took 5.09 s per move on average. Its 13 fast moves were forced (mostly the only legal move) or came at the end of the mate in game 1.

## Were the draws the hint's fault? No.

I checked every game in two passes, both with the native Stockfish dev-20261028 (SFNNv19) in `engines/`.

1. **First pass:** every position at 0.5 s.
2. **Deep pass:** four analysts covered the games in groups, and for each group an independent reviewer tried to refute the analyst's conclusions. They used 10–20 s searches with MultiPV, and Syzygy tablebases (the Lichess API, plus local 5-piece tables where the 50-move clock mattered) for every position of 7 pieces or fewer. In all, about 200 probes.

The reviewers corrected a few details (sizes of the AI's mistakes, one FEN typo, one notation slip) but **did not overturn any conclusion.**

**Findings:**

- **The hint never missed a win.** In games 2–10 our side was never better than about +0.5, and never worse than about −0.35.
- **Tablebase checks:** every hint move in the tablebase range kept the best result available, and the reviewers covered that range position by position for most games. Several were only moves:
  - game 4: 87...Rg6+, one of 5 drawing moves out of 29;
  - game 6: 74...dxc4, the only drawing move;
  - game 7: 76.Rf8+, the only move that did not get mated.
- **The AI made almost no mistakes.** In games 2–10 no AI move lost even 0.3 pawn. The one exception was game 3's 39...f6 (about 0.37), which the AI played on purpose to avoid a threefold repetition. There was nothing for the hint to convert.
- **Game 1 was won from three real AI mistakes:**
  - 27...g5 (about 0.6 pawn);
  - 38...Ba1 (about 1.1, losing the b4 pawn; only 39.Kc4 kept the gain, and the hint found it);
  - 42...Bxc5+ (about 0.9, into a lost opposite-colored bishop ending).

  The hint's slips there never put the win at risk: 46.e6+ cost under a pawn (0.4–0.9, depending on search depth). From 7 pieces on, every hint move kept the tablebase win. The mate took 28 plies more than the tablebase's fastest line, and the 50-move counter never passed 25 plies.

**How each draw happened:**

| # | What decided it |
|---|-----------------|
| 2 | Level throughout. R+P vs R from ply 131. Every position from ply 126 to the end is a tablebase draw, and every move both sides played was a drawing move. |
| 3 | Level throughout. The game reached B+P vs R, a tablebase draw. 122...Rxc7+ was one of the AI's only two drawing moves; it forced 123.bxc7, stalemate. Our 122.Bc7 drew, like every hint move from 7 pieces on. |
| 4 | Level throughout. We defended R+N+P vs R+B+P, and the hint found narrow tablebase draws (5 of 29 moves, then 3 of 24). |
| 5 | Our perpetual check (Nf7+/Nh6+). It was forced: Black was a rook up, with ...a1=Q coming, and every other move scored −9.8 or worse. |
| 6 | Level throughout. In the pawn ending the hint found the only drawing moves (74...dxc4), and so did the AI. |
| 7 | 28...Bxh3 was the AI's only move that kept the balance. Later both sides had only moves: 76.Rf8+ for us, 77...gxf3 for the AI. |
| 8 | 0.00 at depth from the middlegame on. At 7 pieces the AI found one of White's 3 holding moves (104.Ne1). |
| 9 | The AI's queen perpetual from 31...Qxh3+, its only move that did not lose. Our 51.Kg2 made the third repetition; its alternatives scored −4.4 and −5.8. |
| 10 | The AI's knight perpetual (Na7+/Nc6+), its only move that did not lose. Our 35...Kc8 made the third repetition; its alternatives scored −6.1 and −7.1. |

**The repetition rule (`nonRepetitionMoves` / `takesTheDraw`) worked as designed in every case:**

- **Draws it took (games 5, 9, 10):** only when every move that plays on scored far below −0.5.
- **Draws it declined:** the hint turned down a threefold for an equal or slightly worse position at least nine times (games 2, 3 three times, 4 twice, 8, 9 and 10). The AI did the same at least six times (games 2, 3, 6 and 10). None of these cost anything. The largest concession was game 2's 31...Rb7, at −0.30.
- **One thing to know:** the rule compares scores only. Twice (game 4 at ply 167, game 10 at ply 43) turning down the draw led into a line where our side then had only moves. The hint found every one, but someone playing those positions by hand would have had to as well.

## Stability

- **Errors:** none. Every hint arrived, every move was accepted, no prompt appeared and the page never froze.
- **Hint engine start:** on the first visit it was ready about 90 s after sign-in, which includes downloading and saving the 4 parts (59 s in a smoke test just before the run). On a second visit in the same browser profile it was ready after 1 s with **zero** `.wasm` downloads, started from Cache Storage.
- **Saved games: 10 of 10.** The account API lists all ten in the run's time window. Each is move-for-move identical to the driver's record, with the right colors and results. The "vs Impossible" record now reads +4 =39 −4.
  - Caveat: the driver waited for the save message before starting the next game. So this run does not test the quick New-game race from the 2026-11-04 report, which `c77cf93` addressed.

## Compared with the earlier runs

| Run | Hint engine | Wins / draws / losses | Points |
|---|---|---|---|
| 2026-11-04, run 1 | Stockfish 19 full, 1 thread, 16 MB | 4 / 2 / 4 | 5.0 |
| 2026-11-04, run 2 | the same with 64 MB hash | 4 / 4 / 2 | 6.0 |
| 2026-11-05, run A* | Stockfish dev (SFNNv19), 1 thread | 1 / 8 / 1 | 5.0 |
| 2026-11-05, run B* | the same, after `51bd6fa` (repetition draws, saved hint engine) | 1 / 9 / 0 | 5.5 |
| **2026-11-06 (this run)** | **Stockfish 19 full, 8 threads, 128 MB** | **1 / 9 / 0** | **5.5** |

\* No report was written for the two 2026-11-05 runs. Their numbers come from that session's driver output.

Since the hint got stronger (SFNNv19, then 8 threads), it has stopped losing: 0 losses in the last 20 games. Wins have not increased, because Impossible at 5 s is accurate enough that most games stay level. More time or threads for the hint will not turn these draws into wins, since the analysis found no winning chance in nine of the ten games. More wins would need the AI to make more mistakes, for example a lower ceiling for Impossible, or a hint that steers toward unbalanced positions. That is a design choice, not a defect.

## Raw data

In `C:\Users\ADMIN\AppData\Local\Temp\claude\d--Projects-Chess-Playing-AI\3a1b83e1-35be-4f40-8861-285eb93ab175\scratchpad\`:

- `run\results.json`: every game's moves, hint and AI times, and engine names.
- `run.out`: the per-ply log.
- `analysis.json`: the first-pass scores.
- `wf-summary.txt`: the deep pass's findings and reviews.
- `driver.py`, `analyze.py`, `probe.py`: the scripts.
- `run\game-01.png` to `game-10.png`: the final positions.
