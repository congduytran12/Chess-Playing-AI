# Chess

A comprehensive chess game implemented in Python using the Pygame library. It features a fully-playable local and robust online multiplayer mode alongside a challenging built-in AI opponent that calculates optical moves using Minimax (NegaMax) with Alpha-Beta pruning.

![Untitled video - Made with Clipchamp](https://github.com/anuragjain-git/chess/assets/98457054/bfdea7e5-502b-4852-a2c9-115ea32e45da)

## Introduction

This is a modern implementation of a chess game with an interactive graphical user interface. The game allows two players to make moves on a standard chessboard locally or via online multiplayer using unique room codes. Additionally, there is an AI opponent equipped with an optimized negamax algorithm for a challenging single-player chess experience.

## Features

- **Graphical User Interface:**
  - A user-friendly, high-DPI graphical interface developed using the Pygame library with dynamic move highlights and selection indicators.

- **Game Modes (Toggleable In-Game):**
  - **Local vs AI:** Challenge the built-in computer opponent. Set the AI difficulty dynamically using the in-game dropdown (Easy, Normal, Hard, Very Hard).
  - **Local 2-Player:** Play a "hotseat" match against another human on the same screen.
  - **Online Multiplayer:** Host or Join networked games through proxy-unified connections (cross-platform / WASM WebAssembly compatible). Uses server-sent events for responsive, real-time board synchronization with peer-to-peer undo requests.

- **Checkmate, Stalemate, and Legal Moves:**
  - Fully implements the rules of chess, checking for conditions such as pins, king threats, checkmate, stalemate, and 3-fold repetition draws.

- **Advanced Chess Mechanics:**
  - Supports advanced chess mechanics including selectable pawn promotion (via graphical popup), automatic en passant validations, and castling (Kingside & Queenside).

- **Undo and Reset Board:**
  - Features a built-in Undo button (or press `Z`) to revert moves. Press `R` or the Restart button to wipe the board instantly.

- **Immersive Sounds and Audio:**
  - Enhances gameplay feedback with distinct sounds for moves, captures, and pawn promotions.

## En Passant

In chess, the en passant rule allows a pawn to capture an opponent's pawn that has moved two squares forward from its starting position. The capturing pawn moves to the square immediately beyond the captured pawn. Here's how it works:

1. **Initial Position:**:

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

1. Clone the repository to your local machine:
   ```bash
   git clone https://github.com/anuragjain-git/chess-bot.git
   cd chess
   ```
   
2. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Run the `main.py` script to start the game:
   ```bash
   python game/main.py
   ```

## Controls

The controls for the chess game are designed to be intuitive and user-friendly.

- **Selecting a Piece:** Click on the chess piece you want to move. The selected piece will be highlighted to indicate that it's ready for a move.
- **Moving a Piece:** The legal moves for that piece will be highlighted brightly on the board. Click on one of the highlighted squares to move the selected piece.
- **Online Setup:** Use the Mode button to set the game to "Online Multiplayer". The host clicks "Host Game" to receive a Room Code. The client types in the code and clicks "Join Game".

The game engine will automatically handle enforcing chess rules such as pin restrictions, enforcing checks, capturable opponents, and swapping turns correctly between hosts and clients!

## Acknowledgments

Special thanks to the Pygame library for providing a straightforward and effective means to develop graphical applications in Python.

**Contributions and Feedback:**
This project is open to contributions from the community. If you have ideas, want to report issues, or suggest improvements, feel free to contribute on GitHub. Your input is valuable in enhancing the overall quality and functionality of this chess engine.
