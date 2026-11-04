Put a Stockfish program here and the desktop game uses it for the computer's moves, the hints and the analysis.
The browser's hints and analysis use Stockfish dev-20261028 (NNUE SFNNv19); for the same engine on desktop, take
`stockfish-windows-x86-64-universal.zip` (or the arm64 one) from the development build
https://github.com/official-stockfish/Stockfish/releases/tag/stockfish-dev-20261028-ff7cee42, or a release from
https://stockfishchess.org/download/. Only one program is used: the first `stockfish*` file by name, so keep a
single one here. Anything else in this folder is ignored by git. See `game/stockfish.py`.
