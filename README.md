# Chess

A chess game written in Python with Pygame. You can play against the computer (Stockfish), against a friend on the same screen, or online with a room code. It runs on the desktop and in the browser (Python compiled to WebAssembly with pygbag).

![Untitled video - Made with Clipchamp](https://github.com/anuragjain-git/chess/assets/98457054/bfdea7e5-502b-4852-a2c9-115ea32e45da)

## Features

### Game modes

Switch modes with the **Mode** dropdown:

- **Local vs AI:** play the computer at five levels (Easy, Normal, Hard, Very Hard, Impossible). You can play as White, Black, or a random color. When you play Black, the board flips and the AI moves first.
- **Local 2-Player:** two players take turns on the same screen.
- **Online Multiplayer:** host a game to get a room code, and your opponent joins with it. The host plays White and sets the time control.

### The AI

- **Stockfish:** the computer's moves, the hints and the game analysis come from [Stockfish](https://stockfishchess.org/). In the browser it is [stockfish.js](https://github.com/nmrugg/stockfish.js) (17.1, the lite single-threaded build), which runs in the background while you play. On the desktop the game uses a Stockfish program on your computer (see [Installation](#installation--how-to-play)).
- **Levels:** each level holds Stockfish to a playing strength: about 1320 Elo on Easy, 1600 on Normal, 1900 on Hard and 2300 on Very Hard. Impossible is full strength. Each level also has a time budget, from 0.3 s on Easy to 5 s on Impossible. Hints and the analysis always use full strength.
- **The built-in AI:** when there is no Stockfish (a desktop without it, or a browser that can't load it), the game's own AI plays instead. It thinks for the same time budgets, searching one move deeper at a time, so it never freezes the game. Easy and Normal also add some randomness, so they stay beatable.
- **The built-in AI's search:** NegaMax with alpha-beta pruning. It also:
  - keeps following captures past the normal search depth, so it doesn't misjudge trades
  - follows checking sequences further, so it sees mating attacks
  - remembers positions it has already searched
  - avoids repeating positions when it's winning
- **The built-in AI's opening book:** its first moves come from 32 common openings, picked at random, so games don't all start the same way.

### Playing a game

- **Chess clock:** play untimed or with 1+0, 3+2, 5+0, 10+5, or 15+10. Running out of time loses, unless your opponent has only a king left, in which case it's a draw.
- **Hints:** the **Hint** button highlights a good move for you, up to 5 times a day (online too, on your turn).
- **Resign or offer a draw:** against the AI, the computer accepts a draw only when it's losing. In 2-player and online games, the opponent gets an Accept / Decline prompt.
- **Undo:** use the button or press `Z`. Against the AI, it takes back your last move and the AI's reply. Online, it asks your opponent first.
- **On the board:** the last move and a king in check are highlighted. Each player's panel shows the pieces they've captured, the material lead, and their clock.
- **Move log:** moves are written in standard chess notation (`Nf3`, `exd5`, `O-O`, `Qxf7#`, `e8=Q`).

### Review and analysis

When a game ends, you can go back through it:

- **Step through the moves** with the ◀ ▶ buttons, the arrow keys (and Home/End), or by clicking a move in the log.
- **Analyze game** has the AI check every position in the background. It marks moves in the log as `??` (blunder), `?` (mistake), or `?!` (inaccuracy), and shows the score and the better move for each flagged move.

### Saving and loading games

- **Save PGN** saves the game in PGN, the standard chess game format that most chess sites and apps can open. On the desktop you choose where to save the file; in the browser it downloads.
- **Load PGN** opens a PGN file. You can review the game, or keep playing from the final position (against the AI or a friend).

### Online play that recovers

Online games can recover from dropped messages and page refreshes. Every move sends the whole game, and a player who falls behind is caught up automatically. After a refresh or restart, the **Rejoin** button puts you back in your last room as the same color.

### Accounts

Click **Sign in** (bottom right of the panel) to create an account with a username, email, and password, or to sign in. You stay signed in until you sign out. With an account:

- **Your games are saved.** Every game you finish while signed in is saved to your account. Open **My games** to load one back for review or analysis, on any device.
- **Stats:** see your wins, losses, and draws against each AI level and online.
- **Names online:** your opponent sees your username and rating instead of "Opponent".
- **Rating and leaderboard:** online games between two signed-in players change both ratings (Elo, starting at 1200), and the leaderboard shows the top 10. A result counts once both players report the same result, or when the losing side reports it, for example by resigning. If the loser just closes the game, the result isn't rated.

### Rules

The game enforces all the rules of chess:

- moves that would leave your own king in check are not allowed, including moves of pinned pieces
- castling, with all its conditions
- en passant
- promotion to any piece
- checkmate and stalemate
- draws by threefold repetition, the 50-move rule, and insufficient material

## En Passant

In chess, the en passant rule allows a pawn to capture an opponent's pawn that has moved two squares forward from its starting position. The capturing pawn moves to the square immediately beyond the captured pawn. Here's how it works:

1. **Initial Position:**

   <img src="https://github.com/anuragjain-git/chess/assets/98457054/1b92957b-1126-4771-8ffb-e3fe7a77b4ca" alt="Chessboard" width="400"/>

2. **Opponent's Move:**

   <img src="https://github.com/anuragjain-git/chess/assets/98457054/bba26e9f-86b2-421b-99b0-a0e7c73a49d9" alt="Chessboard" width="400"/>

3. **En Passant Capture:**

   <img src="https://github.com/anuragjain-git/chess/assets/98457054/d77b5e0c-cd11-41e2-86d1-687267586c63" alt="Chessboard" width="400"/>

## Pawn Promotion

In chess, pawn promotion occurs when a pawn reaches the eighth rank. The pawn can be promoted to any other chess piece (except a king). Here's how it works:

1. **Reach the Eighth Rank**:

   <img src="https://github.com/anuragjain-git/chess/assets/98457054/9d33967c-6d19-478c-bb23-8737e4325510" alt="Chessboard" width="400"/>

2. **Select the Promotion Piece**:

   <img src="https://github.com/anuragjain-git/chess/assets/98457054/42fc5e0e-f782-4d55-a454-37c13dd39ffa" alt="Chessboard" width="400"/>

## Installation & How to Play

1. Clone the repository:
   ```bash
   git clone https://github.com/congduytran12/Chess-Playing-AI.git
   cd Chess-Playing-AI/game
   ```

2. Install the dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Optional, for Stockfish: download Stockfish from [stockfishchess.org](https://stockfishchess.org/download/) and either put the program in the repository's `engines/` folder, install it so `stockfish` is on your `PATH`, or set the `STOCKFISH_PATH` environment variable to it. Without it, the desktop game uses its built-in AI.

4. Start the game from the repository root:
   ```bash
   cd ..
   python main.py
   ```

### Building the web version

The browser version is built with [pygbag](https://github.com/pygame-web/pygbag) and deployed on Vercel. To build it yourself, run this from the repository root:

```bash
npm run build
```

The output goes to `game/build/web`. The build also downloads stockfish.js and its `.wasm` file into `game/build/web/stockfish/`.

Stockfish and stockfish.js are licensed under the GNU GPL v3; the build copies the license next to them (`stockfish/Copying.txt`).

### Setting up accounts

Accounts use [Supabase](https://supabase.com/) for sign-in and storage. The game talks only to the `/api/account` function on Vercel ([api/account.py](api/account.py)), which holds the Supabase key. One-time setup:

1. Create a Supabase project.
2. In the Supabase dashboard, open **SQL Editor**, paste in [supabase/schema.sql](supabase/schema.sql), and run it. This creates the tables and the rating function.
3. In **Authentication > Sign In / Providers**, keep **Email** enabled. With **Confirm email** on, new players must click the link in their email before they can sign in. In that case, set **Authentication > URL Configuration > Site URL** to your game's address so the link opens the game.
4. In Vercel, open the project's **Settings > Environment Variables** and add these two (from Supabase's **Project Settings > API**), then redeploy:
   - `SUPABASE_URL`: the project URL.
   - `SUPABASE_SERVICE_ROLE_KEY`: the service role key. It's secret: keep it out of the code and the repository.

The desktop game uses the deployed site at `https://chess-playing-ai.vercel.app`. To use another deployment, set the `CHESS_API_URL` environment variable.

All sign-ins reach Supabase from Vercel's servers, so they share Supabase's sign-in rate limits. If many players sign in at once, raise the limits in **Authentication > Rate Limits**.

## Controls

- **Move a piece:** click a piece to select it. Its legal moves are highlighted; click one to move there. When a pawn promotes, choose the new piece from the popup.
- **Keyboard:**
  - `Z`: undo
  - `R`: restart
  - arrow keys, `Home`, `End`: step through a finished game
- **Mouse wheel** over the move log: scroll through earlier moves.
- **After the game:** click the board to start a new game. When you're reviewing earlier moves, step to the end first.
- **Online:**
  1. Choose **Online Multiplayer** in the Mode dropdown and pick a clock.
  2. The host clicks **Host (White)** and shares the room code shown.
  3. The opponent types the code and clicks **Join (Black)**.

## Credits

- [Pygame](https://www.pygame.org/) for graphics, input, and sound.
- [pygbag](https://github.com/pygame-web/pygbag) for running the game in the browser.
- Online games are relayed through [ntfy.sh](https://ntfy.sh/).
- Accounts are stored with [Supabase](https://supabase.com/).
- The game's text uses the [Liberation Serif](https://github.com/liberationfonts/liberation-fonts) font (SIL Open Font License, see `game/fonts/`).

## Contributing

Contributions are welcome. If you have ideas, find a bug, or want to suggest an improvement, open an issue or a pull request on GitHub.
