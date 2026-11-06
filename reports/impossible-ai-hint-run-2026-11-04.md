# Impossible AI, 10 games played with Hint on the Vercel build

**Date:** 2026-11-04
**Site:** https://chess-playing-ai.vercel.app/ (the deployed pygbag build). By the code, hints come from the full-size single-thread Stockfish 19 build (`stockfish-19-single.js`, 5 s per hint, `HINT_SECONDS`), and the computer's moves from the Lite build (`stockfish-19-lite-single.js`). I did not check in the browser which file each one loaded.
**Account:** congduytran12 (admin, so Hint is unlimited and uncounted)
**Settings:** Mode "Local vs AI", AI "Impossible", Play as "Random", Clock off

## Method

A headless Chromium (Playwright) drove the live page. It signed in through the game's own form and set the level and side with the game's buttons. Each game then ran this loop on the player's turn:

1. Click **Hint** and wait for the hint move. The page's `GAME_VIEW` exposes `hintMove`, which was read through the pygbag Python bridge.
2. Play exactly that move by clicking the from and to squares. Promotion would be picked with the picker's column.
3. Wait for the computer's reply.

I made no move of my own in any game. Every one of my moves is the Hint's move.

## Results

| # | Side | Result for me | Plies | Time (min) | Hints | Avg hint (s) | Max hint (s) | How it ended |
|---|------|---------------|------:|-----------:|------:|-------------:|-------------:|--------------|
| 1 | Black | Draw | 223 | 22.6 | 111 | 5.66 | 5.76 | Insufficient material |
| 2 | Black | Draw | 150 | 15.1 | 75 | 5.66 | 5.79 | Threefold repetition |
| 3 | Black | **Win** | 132 | 12.7 | 66 | 5.40 | 5.77 | Checkmate (0-1) |
| 4 | Black | **Win** | 90 | 8.5 | 45 | 5.32 | 5.81 | Checkmate (0-1) |
| 5 | Black | Loss | 79 | 7.2 | 39 | 5.06 | 5.77 | Checkmated (1-0) |
| 6 | White | Loss | 124 | 12.0 | 62 | 5.37 | 5.77 | Checkmated (0-1) |
| 7 | White | **Win** | 111 | 10.7 | 56 | 5.31 | 5.77 | Checkmate (1-0) |
| 8 | White | Loss | 132 | 12.4 | 66 | 5.29 | 5.78 | Checkmated (0-1) |
| 9 | White | Loss | 94 | 8.6 | 47 | 5.06 | 5.78 | Checkmated (0-1) |
| 10 | White | **Win** | 149 | 14.8 | 75 | 5.46 | 5.80 | Checkmate (1-0) |

**Total: 4 wins, 2 draws, 4 losses (5.0 / 10 points).**

- **By side:** as Black, 2W 2D 1L. As White, 2W 0D 3L. Five games each is too few to say a side matters.
- **Length:** 1,284 plies in total, an average of 128 plies (64 moves) per game, from 79 to 223 plies. The run took about 125 minutes.
- **Hints:** 642 hints, one for each of my moves. They averaged 5.4 s and never took longer than 5.81 s. The search time is a fixed budget, so the hint's cost is the same in every position.
- **Side selection:** Random gave Black five times, then White five times. The code picks with `random.choice` (`game/main.py:1416`), so this is a streak of chance, not a defect.

For comparison, the account's profile before the run showed **+1 =7 -3** against Impossible (11 games). Following the hint every move gave a more decisive record, but the sample is small.

## Stability

- **Errors:** none. No hint failed to arrive, no move was refused, no stall or error prompt appeared, and the page never froze. All 642 hint moves were accepted as legal.
- **Promotion:** it worked. Game 10 includes `c8=Q+`.
- **Starting the engine:** the gameplay engine (Stockfish 19 Lite WASM) reported "ready" about 30 s after the page opened. After that every hint and every computer move came back on time.
- **Page loading:** the first attempts to reach the site failed with connection timeouts from this machine, on both of its IP addresses. It loaded normally on a later try, so I put that down to the network on my side, not the deployment.

## Issue to look at: saved games

Only **2 of the 10 games** appear in the account's *My games* list and in the "vs Impossible" record. The count went from +1 =7 -3 to **+2 =8 -3**. The two saved games are one win and one draw. The other eight did not appear.

- **What the code does:** `saveFinishedGame()` runs once for each finished game when the player is signed in (`game/main.py:3237`).
- **What I observed:** the games that did save are, as far as I can tell, the ones where nothing was clicked for a while after the game ended. In the other games my script clicked **New game** within a few seconds of the result. I did not verify this.
- **Likely cause:** starting a new game before the save request finishes may drop it. It could also be a failed request, since the "Couldn't save the game" message would have flashed only briefly, and I did not capture it.
- **To confirm:** finish a game by hand, wait 10 seconds, then start the next one. If those games save, the problem is the timing.

These are my own observations and I did not change any code. Because it is inconclusive, do not treat the profile's win/draw/loss totals as a record of this run. The table above is the record.

Two other things in the account list are not from this run. The account page shows an online win against "Guest" dated 2026-11-04, and the "Online" count rose from +10 to +11 while I played no online games. I don't know who played it.

## Raw data

- Results per game (JSON lines, with every game's full move list): `C:\Users\ADMIN\AppData\Local\Temp\claude\d--Projects-Chess-Playing-AI\8d95686e-df16-4083-9da3-efd17f130a8a\scratchpad\results.jsonl`
- Per-game logs: `game1.log` to `game10.log` in the same folder.

---

# Run 2: the same test with a 64 MB hash for the hint engine

**Change tested:** commit `a32b656` ("Give the hint engine a 64 MB hash") adds `HINT_HASH_MB = 64` in `game/stockfish.py` and uses it for the hint engine only. Gameplay stays at 16 MB, and `HINT_SECONDS` is still 5 s. The site was checked live before the run: the deployed `game.apk` contains `HINT_HASH_MB`.

The method is identical to run 1: Impossible, Random side, every move taken from Hint. The unit tests were not run, because this machine has no Python.

| # | Side | Result for me | Plies | Time (min) | Hints | Avg hint (s) | Max hint (s) | How it ended |
|---|------|---------------|------:|-----------:|------:|-------------:|-------------:|--------------|
| 1 | Black | **Win** | 70 | 6.9 | 35 | 5.79 | 15.69 | Checkmate (0-1) |
| 2 | Black | Draw | 98 | 9.9 | 49 | 5.62 | 5.71 | Threefold repetition |
| 3 | Black | Draw | 132 | 13.4 | 66 | 5.65 | 5.77 | Insufficient material |
| 4 | Black | Loss | 131 | 12.7 | 65 | 5.46 | 5.76 | Checkmated (1-0) |
| 5 | Black | Draw | 196 | 19.8 | 98 | 5.66 | 5.77 | Threefold repetition |
| 6 | Black | **Win** | 146 | 14.0 | 73 | 5.38 | 5.74 | Checkmate (0-1) |
| 7 | White | Draw | 102 | 10.4 | 51 | 5.67 | 5.77 | Insufficient material |
| 8 | White | **Win** | 47 | 4.2 | 24 | 4.83 | 5.77 | Checkmate (1-0) |
| 9 | White | **Win** | 147 | 14.3 | 74 | 5.33 | 5.84 | Checkmate (1-0) |
| 10 | Black | Loss | 153 | 14.6 | 76 | 5.35 | 5.77 | Checkmated (1-0) |

**Run 2 total: 4 wins, 4 draws, 2 losses (6.0 / 10).**

## Comparison

| | Run 1 (16 MB hash) | Run 2 (64 MB hash) |
|---|---|---|
| Wins / draws / losses | 4 / 2 / 4 | 4 / 4 / 2 |
| Points | 5.0 / 10 | 6.0 / 10 |
| Games ending in a loss for me | 4 | 2 |
| Hints | 642 | 611 |
| Average hint | 5.41 s | 5.50 s |
| Plies played | 1,284 | 1,222 |

- **The result is better, but the sample is small.** The same number of wins, two fewer losses and two more draws is within what chance gives across 10 games. A real effect from the bigger hash is possible, but these 20 games do not show it. Run 2 is also 7 games as Black and only 3 as White, since Random drew that split.
- **The 9/10 or 10/10 target was not reached,** and I don't think a hash change alone can reach it. Hint and opponent are both single-thread Stockfish with 5 s per move.
- **One slow hint:** the slowest hint, 15.69 s, was in game 1. It was probably the first one, which loads the larger engine. Every other hint took 5.84 s or less.
- **No errors:** every hint arrived and every move was accepted as legal. The 64 MB allocation caused no failure or visible slowdown.

## Saved games again

Only **1 of the 10** games of run 2 reached the account (the vs Impossible record went from +2 =8 -3 to +2 =8 -4, a loss). It matches the pattern from run 1: the saved games are, as far as I can tell, ones where nothing was clicked soon after they ended. This is still unconfirmed. The profile also shows a loss against Very Hard that was not played in either run, so the profile shows other activity on the account.

## What would still move the score

- **More time per hint:** `HINT_SECONDS` is the main lever, and 15–30 s would give the hint more time than the AI's 5 s. It makes each hint slow.
- **A longer sample:** to tell a 60% result from a 50% one takes far more than 10 games.

Raw data for run 2 is in the scratchpad folder next to run 1's (`results.jsonl`, `game1.log` to `game10.log`; run 1's files are in its `run1` subfolder).
