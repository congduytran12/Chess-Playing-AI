import os

with open("main.py", "r", encoding="utf-8") as f:
    text = f.read()

# 1. Inject networking logic inside `while running:`
target_while = "    while running:\n        humanTurn ="
replace_while = """    while running:
        if multiplayerMode and networkConnected:
            for msg in net.get_messages():
                mtype = msg.get('type')
                if mtype == 'join' and multiplayerRole == 'host':
                    pass
                elif mtype == 'move':
                    moveStr = msg.get('move')
                    startPoint = (moveStr[0][0], moveStr[0][1])
                    endPoint = (moveStr[1][0], moveStr[1][1])
                    remoteMove = Move(startPoint, endPoint, gs.board)
                    if msg.get('promo'):
                        remoteMove.isPawnPromotion = True
                    gs.makeMove(remoteMove)
                    if remoteMove.isPawnPromotion:
                        gs.board[remoteMove.endRow][remoteMove.endCol] = remoteMove.pieceMoved[0] + msg.get('promoPiece')
                    
                    if remoteMove.pieceCaptured != '--' or remoteMove.isEnpassantMove: capture_sound.play()
                    else: move_sound.play()
                    
                    moveMade = True
                    animate = True
                    squareSelected = ()
                    playerClicks = []
                elif mtype == 'undo_request':
                    opponentRequestedUndo = True
                elif mtype == 'undo_response':
                    if msg.get('accepted'):
                        gs.undoMove()
                        gs.undoMove()
                        moveMade = True

        humanTurn ="""
text = text.replace(target_while, replace_while)

# 2. Modify humanTurn evaluation
target_hturn = "humanTurn = (gs.whiteToMove and playerWhiteHuman) or (\n            not gs.whiteToMove and playerBlackHuman)"
replace_hturn = """humanTurn = (gs.whiteToMove and playerWhiteHuman) or (\n            not gs.whiteToMove and playerBlackHuman)
        if multiplayerMode and networkConnected:
            humanTurn = (gs.whiteToMove and multiplayerRole == 'host') or (not gs.whiteToMove and multiplayerRole == 'client')"""
text = text.replace(target_hturn, replace_hturn)

# 3. Suppress AI when multiplayer
target_ai = "if not gameOver and not humanTurn and not moveUndone:"
replace_ai = "if not gameOver and not humanTurn and not moveUndone and not (multiplayerMode and networkConnected):"
text = text.replace(target_ai, replace_ai)

# 4. Broadcast Moves (inside makeMove)
target_broad = "promote_sound.play()\n                                    pieceCaptured = False"
replace_broad = """promote_sound.play()
                                    pieceCaptured = False
                                else:
                                    promotion_choice = ""
                                if multiplayerMode and networkConnected:
                                    await net.send({
                                        'type': 'move',
                                        'move': [(validMoves[i].startRow, validMoves[i].startCol), (validMoves[i].endRow, validMoves[i].endCol)],
                                        'promo': validMoves[i].isPawnPromotion,
                                        'promoPiece': promotion_choice
                                    })"""
text = text.replace(target_broad, replace_broad)

with open("main.py", "w", encoding="utf-8") as f:
    f.write(text)
print("Network logic integration patched.")
