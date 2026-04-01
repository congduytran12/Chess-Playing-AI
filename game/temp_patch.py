import os

with open("main.py", "r", encoding="utf-8") as f:
    text = f.read()

# 1. Imports
text = text.replace(
    "from chessAi import findRandomMoves, findBestMove\nimport asyncio",
    "from chessAi import findRandomMoves, findBestMove\nimport asyncio\nfrom network import net\nimport random\nimport string"
)

# 2. Variables
var_target = """    AIThinking = False  # True if ai is thinking
    dropdown_open = False

    moveUndone = False"""

var_replace = """    AIThinking = False  # True if ai is thinking
    dropdown_open = False

    multiplayerMode = False
    multiplayerRole = None
    roomCode = ""
    inputBoxActive = False
    networkConnected = False
    opponentRequestedUndo = False

    moveUndone = False"""
text = text.replace(var_target, var_replace)

with open("main.py", "w", encoding="utf-8") as f:
    f.write(text)
print("done")
