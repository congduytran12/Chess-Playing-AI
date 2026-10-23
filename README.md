# Chess

A chess game written in Python with Pygame. You can play against a built-in AI, against a friend on the same screen, or online with a room code. It runs on the desktop and in the browser (Python compiled to WebAssembly with pygbag).

![Untitled video - Made with Clipchamp](https://github.com/anuragjain-git/chess/assets/98457054/bfdea7e5-502b-4852-a2c9-115ea32e45da)

## Features

### Game modes

Switch modes with the **Mode** dropdown:

- **Local vs AI:** play the computer at five levels (Easy, Normal, Hard, Very Hard, Impossible). You can play as White, Black, or a random color. When you play Black, the board flips and the AI moves first.
- **Local 2-Player:** two players take turns on the same screen.
- **Online Multiplayer:** host a game to get a room code, and your opponent joins with it. The host plays White and sets the time control.

### The AI

- **Thinks for a set time:** each level has a time budget (from 0.3 s on Easy to 5 s on Impossible). The AI searches one move deeper at a time until the budget runs out, so it never freezes the game, even in the browser. Easy and Normal also add some randomness, so they stay beatable.
- **Search:** NegaMax with alpha-beta pruning. It also:
  - keeps following captures past the normal search depth, so it doesn't misjudge trades
  - follows checking sequences further, so it sees mating attacks
  - remembers positions it has already searched
  - avoids repeating positions when it's winning
- **Opening book:** the first moves come from 32 common openings, picked at random, so games don't all start the same way.

### Playing a game

- **Chess clock:** play untimed or with 1+0, 3+2, 5+0, 10+5, or 15+10. Running out of time loses, unless your opponent has only a king left, in which case it's a draw.
- **Hints:** the **Hint** button highlights a good move for you (not available online).
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

3. Start the game from inside the `game` folder (the game loads its images, sounds, and fonts from there):
   ```bash
   python main.py
   ```

### Building the web version

The browser version is built with [pygbag](https://github.com/pygame-web/pygbag) and deployed on Vercel. To build it yourself, run this from the repository root:

```bash
npm run build
```

The output goes to `game/build/web`.

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
- The game's text uses the [Liberation Serif](https://github.com/liberationfonts/liberation-fonts) font (SIL Open Font License, see `game/fonts/`).

## Contributing

Contributions are welcome. If you have ideas, find a bug, or want to suggest an improvement, open an issue or a pull request on GitHub.
