'''
    Add or remove bots :
    
    SET_WHITE_AS_BOT = False
    SET_BLACK_AS_BOT = True
'''

# Responsible for handling user input and displaying the current Gamestate object

import sys
import ctypes

# Fix Pygame resolution blurriness on Windows by telling the OS this app is high DPI aware
if sys.platform == 'win32':
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

import pygame as p
import chessAi
from engine import GameState, Move
from chessAi import findRandomMoves, findBestMove
import asyncio
from network import net
import random
import string

# Initialize the mixer
p.mixer.init()
# Load sound files
move_sound = p.mixer.Sound("sounds/move-sound.ogg")
capture_sound = p.mixer.Sound("sounds/capture.ogg")
promote_sound = p.mixer.Sound("sounds/promote.ogg")

BOARD_WIDTH = BOARD_HEIGHT = 768
MOVE_LOG_PANEL_WIDTH = 375
MOVE_LOG_PANEL_HEIGHT = BOARD_HEIGHT
DIMENSION = 8
SQ_SIZE = BOARD_HEIGHT // DIMENSION
MAX_FPS = 30
IMAGES = {}

'''

     ADD BOTS         
    IF IN GameState() , 
    
    playerWantsToPlayAsBlack = True
    SET_BLACK_AS_BOT SHOULD BE = FALSE

'''

SET_WHITE_AS_BOT = False
SET_BLACK_AS_BOT = True

# Define colors

# 1 Green

LIGHT_SQUARE_COLOR = (237, 238, 209)
DARK_SQUARE_COLOR = (119, 153, 82)
MOVE_HIGHLIGHT_COLOR = (84, 115, 161)
POSSIBLE_MOVE_COLOR = (255, 255, 51)

# 2 Brown

'''
LIGHT_SQUARE_COLOR = (240, 217, 181)
DARK_SQUARE_COLOR = (181, 136, 99)
MOVE_HIGHLIGHT_COLOR = (84, 115, 161)
POSSIBLE_MOVE_COLOR = (255, 255, 51)
'''

# 3 Gray

'''
LIGHT_SQUARE_COLOR = (220,220,220)
DARK_SQUARE_COLOR = (170,170,170)
MOVE_HIGHLIGHT_COLOR = (84, 115, 161)
POSSIBLE_MOVE_COLOR = (164,184,196)
'''


def loadImages():
    pieces = ['bR', 'bN', 'bB', 'bQ', 'bK',
              'bp', 'wR', 'wN', 'wB', 'wQ', 'wK', 'wp']
    for piece in pieces:
        image_path = "images1/" + piece + ".png"
        original_image = p.image.load(image_path)
        # p.transform.smoothscale is bit slower than p.transform.scale, using this to reduce pixelation and better visual quality for scaling images to larger sizes
        IMAGES[piece] = p.transform.smoothscale(
            original_image, (SQ_SIZE, SQ_SIZE))


def pawnPromotionPopup(screen, gs):
    font = p.font.SysFont("Times New Roman", 45, False, False)
    text = font.render("Choose promotion:", True, p.Color("black"))

    # Create buttons for promotion choices with images
    button_width, button_height = 150, 150
    buttons = [
        p.Rect(50, 300, button_width, button_height),
        p.Rect(225, 300, button_width, button_height),
        p.Rect(400, 300, button_width, button_height),
        p.Rect(575, 300, button_width, button_height)
    ]

    if gs.whiteToMove:
        button_images = [
            p.transform.smoothscale(p.image.load("images1/bQ.png"), (150, 150)),
            p.transform.smoothscale(p.image.load("images1/bR.png"), (150, 150)),
            p.transform.smoothscale(p.image.load("images1/bB.png"), (150, 150)),
            p.transform.smoothscale(p.image.load("images1/bN.png"), (150, 150))
        ]
    else:
        button_images = [
            p.transform.smoothscale(p.image.load("images1/wQ.png"), (150, 150)),
            p.transform.smoothscale(p.image.load("images1/wR.png"), (150, 150)),
            p.transform.smoothscale(p.image.load("images1/wB.png"), (150, 150)),
            p.transform.smoothscale(p.image.load("images1/wN.png"), (150, 150))
        ]

    while True:
        for e in p.event.get():
            if e.type == p.QUIT:
                p.quit()
                sys.exit()
            elif e.type == p.MOUSEBUTTONDOWN:
                mouse_pos = e.pos
                for i, button in enumerate(buttons):
                    if button.collidepoint(mouse_pos):
                        if i == 0:
                            return "Q"  # Return the index of the selected piece
                        elif i == 1:
                            return "R"
                        elif i == 2:
                            return "B"
                        else:
                            return "N"

        screen.fill(p.Color(LIGHT_SQUARE_COLOR))
        screen.blit(text, (110, 150))

        for i, button in enumerate(buttons):
            p.draw.rect(screen, p.Color("white"), button)
            screen.blit(button_images[i], button.topleft)

        p.display.flip()


'''
moveLocationWhite = ()
movedPieceWhite = ""
moveLocationBlack = ()
movedPieceBlack = ""

moveWhiteLog = []
moveBlackLog = []
'''


async def main():
    # initialize py game
    p.init()
    screen = p.display.set_mode(
        (BOARD_WIDTH + MOVE_LOG_PANEL_WIDTH, BOARD_HEIGHT))
    clock = p.time.Clock()
    screen.fill(p.Color(LIGHT_SQUARE_COLOR))
    moveLogFont = p.font.SysFont("Times New Roman", 18, False, False)
    # Creating gamestate object calling our constructor
    gs = GameState()
    if (gs.playerWantsToPlayAsBlack):
        gs.board = gs.board1
    # if a user makes a move we can ckeck if its in the list of valid moves
    validMoves = gs.getValidMoves()
    moveMade = False  # if user makes a valid moves and the gamestate changes then we should generate new set of valid move
    animate = False  # flag var for when we should animate a move
    loadImages()
    running = True
    squareSelected = ()  # keep tracks of last click
    # clicking to own piece and location where to move[(6,6),(4,4)]
    playerClicks = []
    gameOver = False  # gameover if checkmate or stalemate
    playerWhiteHuman = not SET_WHITE_AS_BOT
    playerBlackHuman = not SET_BLACK_AS_BOT
    AIThinking = False  # True if ai is thinking
    dropdown_open = False

    multiplayerMode = False
    multiplayerRole = None
    roomCode = ""
    inputBoxActive = False
    networkConnected = False
    opponentRequestedUndo = False

    moveUndone = False
    pieceCaptured = False
    positionHistory = ""
    previousPos = ""
    countMovesForDraw = 0
    COUNT_DRAW = 0
    gameOverTime = 0
    while running:
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

        humanTurn = (gs.whiteToMove and playerWhiteHuman) or (
            not gs.whiteToMove and playerBlackHuman)
        if multiplayerMode and networkConnected:
            humanTurn = (gs.whiteToMove and multiplayerRole == 'host') or (not gs.whiteToMove and multiplayerRole == 'client')
        for e in p.event.get():
            if e.type == p.QUIT:
                running = False
            # Mouse Handler
            elif e.type == p.MOUSEBUTTONDOWN:
                location = p.mouse.get_pos()
                
                # Dropdown logic
                btn_w = 200
                btn_h = 40
                dropdownMainRect = p.Rect(BOARD_WIDTH + MOVE_LOG_PANEL_WIDTH // 2 - btn_w // 2, BOARD_HEIGHT - 130, btn_w, btn_h)
                
                if dropdown_open:
                    dropdown_open = False
                    for i in range(5):
                        optRect = p.Rect(BOARD_WIDTH + MOVE_LOG_PANEL_WIDTH // 2 - btn_w // 2, BOARD_HEIGHT - 130 - (5 - i) * btn_h, btn_w, btn_h)
                        if optRect.collidepoint(location):
                            chessAi.DEPTH = i + 1
                            break
                    continue
                
                if dropdownMainRect.collidepoint(location):
                    dropdown_open = True
                    continue
                
                # Multiplayer UI Handling
                panel_rect = p.Rect(BOARD_WIDTH + 20, BOARD_HEIGHT - 350, MOVE_LOG_PANEL_WIDTH - 40, 160)
                if opponentRequestedUndo:
                    acceptBtn = p.Rect(panel_rect.x, panel_rect.y + 40, panel_rect.width // 2 - 5, 40)
                    denyBtn = p.Rect(panel_rect.x + panel_rect.width // 2 + 5, panel_rect.y + 40, panel_rect.width // 2 - 5, 40)
                    if acceptBtn.collidepoint(location):
                        opponentRequestedUndo = False
                        gs.undoMove()
                        gs.undoMove()
                        moveMade = True
                        asyncio.ensure_future(net.send({'type': 'undo_response', 'accepted': True}))
                        continue
                    elif denyBtn.collidepoint(location):
                        opponentRequestedUndo = False
                        asyncio.ensure_future(net.send({'type': 'undo_response', 'accepted': False}))
                        continue
                
                btn_w = 200
                btn_h = 40
                modeBtnRect = p.Rect(BOARD_WIDTH + MOVE_LOG_PANEL_WIDTH // 2 - btn_w // 2, BOARD_HEIGHT - 180, btn_w, btn_h)
                
                if multiplayerMode and not networkConnected:
                    hostBtn = p.Rect(BOARD_WIDTH + MOVE_LOG_PANEL_WIDTH // 2 - btn_w // 2, BOARD_HEIGHT - 280, btn_w, btn_h)
                    joinBtn = p.Rect(BOARD_WIDTH + MOVE_LOG_PANEL_WIDTH // 2 - btn_w // 2, BOARD_HEIGHT - 230, btn_w, btn_h)
                    inputRect = p.Rect(BOARD_WIDTH + MOVE_LOG_PANEL_WIDTH // 2 - btn_w // 2, BOARD_HEIGHT - 330, btn_w, btn_h)
                    
                    if hostBtn.collidepoint(location):
                        multiplayerRole = 'host'
                        roomCode = ''.join(random.choices(string.digits, k=4))
                        net.set_topic(roomCode)
                        networkConnected = True
                        continue
                    elif joinBtn.collidepoint(location):
                        if len(roomCode) == 4:
                            multiplayerRole = 'client'
                            net.set_topic(roomCode)
                            asyncio.ensure_future(net.send({'type': 'join'}))
                            networkConnected = True
                        continue
                    elif inputRect.collidepoint(location):
                        inputBoxActive = True
                        continue
                    else:
                        inputBoxActive = False
                        
                if modeBtnRect.collidepoint(location):
                    multiplayerMode = not multiplayerMode
                    roomCode = ""
                    inputBoxActive = False
                    if multiplayerMode: dropdown_open = False
                    continue
                
                # Check for undo button click
                undoBtnRect = p.Rect(BOARD_WIDTH + 25, BOARD_HEIGHT - 80, 150, 50)
                if undoBtnRect.collidepoint(location):
                    if multiplayerMode and networkConnected:
                        await net.send({'type': 'undo_request'})
                        continue
                    gs.undoMove()
                    if playerWhiteHuman != playerBlackHuman: # playing against AI
                        gs.undoMove()
                    moveMade = True
                    animate = False
                    gameOver = False
                    moveUndone = True
                    gameOverTime = 0
                    squareSelected = ()
                    playerClicks = []
                    continue

                # Check for restart button click or click after game over
                restartBtnRect = p.Rect(BOARD_WIDTH + 200, BOARD_HEIGHT - 80, 150, 50)
                if restartBtnRect.collidepoint(location) or gameOver:
                    gs = GameState()
                    if gs.playerWantsToPlayAsBlack:
                        gs.board = gs.board1
                    validMoves = gs.getValidMoves()
                    squareSelected = ()
                    playerClicks = []
                    moveMade = False
                    animate = False
                    gameOver = False
                    moveUndone = True
                    positionHistory = ""
                    previousPos = ""
                    countMovesForDraw = 0
                    COUNT_DRAW = 0
                    AIThinking = False
                    continue

                if not gameOver and location[0] < BOARD_WIDTH:  # only handle board clicks within board area
                    col = location[0]//SQ_SIZE
                    row = location[1]//SQ_SIZE
                    # if user clicked on same square twice or user click outside board
                    if squareSelected == (row, col) or col >= 8:
                        squareSelected = ()  # deselect
                        playerClicks = []  # clear player clicks
                    else:
                        squareSelected = (row, col)
                        # append player both clicks (place and destination)
                        playerClicks.append(squareSelected)
                    # after second click (at destination)
                    if len(playerClicks) == 2 and humanTurn:
                        # user generated a move
                        move = Move(playerClicks[0], playerClicks[1], gs.board)
                        for i in range(len(validMoves)):
                            # check if the move is in the validMoves
                            if move == validMoves[i]:
                                # Check if a piece is captured at the destination square
                                # print(gs.board[validMoves[i].endRow][validMoves[i].endCol])
                                if gs.board[validMoves[i].endRow][validMoves[i].endCol] != '--':
                                    pieceCaptured = True
                                gs.makeMove(validMoves[i])
                                if (move.isPawnPromotion):
                                    # Show pawn promotion popup and get the selected piece
                                    promotion_choice = pawnPromotionPopup(
                                        screen, gs)
                                    # Set the promoted piece on the board
                                    gs.board[move.endRow][move.endCol] = move.pieceMoved[0] + \
                                        promotion_choice
                                    promote_sound.play()
                                    pieceCaptured = False
                                else:
                                    promotion_choice = ""
                                if multiplayerMode and networkConnected:
                                    await net.send({
                                        'type': 'move',
                                        'move': [(validMoves[i].startRow, validMoves[i].startCol), (validMoves[i].endRow, validMoves[i].endCol)],
                                        'promo': validMoves[i].isPawnPromotion,
                                        'promoPiece': promotion_choice
                                    })
                                # add sound for human move
                                if (pieceCaptured or move.isEnpassantMove):
                                    # Play capture sound
                                    capture_sound.play()
                                    # print("capture sound")
                                elif not move.isPawnPromotion:
                                    # Play move sound
                                    move_sound.play()
                                    # print("move sound")
                                pieceCaptured = False
                                moveMade = True
                                animate = True
                                squareSelected = ()
                                playerClicks = []
                        if not moveMade:
                            playerClicks = [squareSelected]

            # Key Handler
            elif e.type == p.KEYDOWN:
                if multiplayerMode and not networkConnected and inputBoxActive:
                    if e.key == p.K_BACKSPACE:
                        roomCode = roomCode[:-1]
                    elif len(roomCode) < 4 and e.unicode.isalnum():
                        roomCode += e.unicode.upper()
                    continue

                if e.key == p.K_z:  # undo when z is pressed
                    if multiplayerMode and networkConnected:
                        await net.send({'type': 'undo_request'})
                        continue
                    gs.undoMove()
                    if playerWhiteHuman != playerBlackHuman: # playing against AI
                        gs.undoMove()
                    moveMade = True
                    animate = False
                    gameOver = False
                    moveUndone = True
                    gameOverTime = 0
                    squareSelected = ()
                    playerClicks = []
                if e.key == p.K_r:  # reset board when 'r' is pressed
                    gs = GameState()
                    if gs.playerWantsToPlayAsBlack:
                        gs.board = gs.board1
                    validMoves = gs.getValidMoves()
                    squareSelected = ()
                    playerClicks = []
                    moveMade = False
                    animate = False
                    gameOver = False
                    moveUndone = True
                    positionHistory = ""
                    previousPos = ""
                    countMovesForDraw = 0
                    COUNT_DRAW = 0
                    AIThinking = False

        # AI move finder
        if not gameOver and not humanTurn and not moveUndone and not (multiplayerMode and networkConnected):
            if not AIThinking:
                AIThinking = True
                await asyncio.sleep(0.1)
                AIMove = await findBestMove(gs, validMoves)
                if AIMove is None:
                    AIMove = findRandomMoves(validMoves)

                if gs.board[AIMove.endRow][AIMove.endCol] != '--':
                    pieceCaptured = True

                gs.makeMove(AIMove)

                if AIMove.isPawnPromotion:
                    # Show pawn promotion popup and get the selected piece
                    promotion_choice = pawnPromotionPopup(screen, gs)
                    # Set the promoted piece on the board
                    gs.board[AIMove.endRow][AIMove.endCol] = AIMove.pieceMoved[0] + \
                        promotion_choice
                    promote_sound.play()
                    pieceCaptured = False

                # add sound for human move
                if (pieceCaptured or AIMove.isEnpassantMove):
                    # Play capture sound
                    capture_sound.play()
                    # print("capture sound")
                elif not AIMove.isPawnPromotion:
                    # Play move sound
                    move_sound.play()
                    # print("move sound")
                pieceCaptured = False
                AIThinking = False
                moveMade = True
                animate = True
                squareSelected = ()
                playerClicks = []

        if moveMade:
            if countMovesForDraw == 0 or countMovesForDraw == 1 or countMovesForDraw == 2 or countMovesForDraw == 3:
                countMovesForDraw += 1
            if countMovesForDraw == 4:
                positionHistory += gs.getBoardString()
                if previousPos == positionHistory:
                    COUNT_DRAW += 1
                    positionHistory = ""
                    countMovesForDraw = 0
                else:
                    previousPos = positionHistory
                    positionHistory = ""
                    countMovesForDraw = 0
                    COUNT_DRAW = 0
            # Call animateMove to animate the move
            if animate:
                animateMove(gs.moveLog[-1], screen, gs.board, clock)
            # genetare new set of valid move if valid move is made
            validMoves = gs.getValidMoves()
            moveMade = False
            animate = False
            moveUndone = False

        drawGameState(screen, gs, validMoves, squareSelected, moveLogFont)

        if COUNT_DRAW == 1:
            if not gameOver:
                gameOverTime = p.time.get_ticks()
            gameOver = True
            text = 'Draw due to repetition'
            drawEndGameText(screen, text)
        elif gs.stalemate:
            if not gameOver:
                gameOverTime = p.time.get_ticks()
            gameOver = True
            text = 'Stalemate'
            drawEndGameText(screen, text)
        elif gs.checkmate:
            if not gameOver:
                gameOverTime = p.time.get_ticks()
            gameOver = True
            text = 'Black wins by checkmate' if gs.whiteToMove else 'White wins by checkmate'
            drawEndGameText(screen, text)

        # Draw restart button
        restartBtnRect = p.Rect(BOARD_WIDTH + 200, BOARD_HEIGHT - 80, 150, 50)
        p.draw.rect(screen, p.Color(DARK_SQUARE_COLOR), restartBtnRect)
        btnFont = p.font.SysFont("Times New Roman", 24, True, False)
        textObject = btnFont.render("Restart", True, p.Color('white'))
        textLocation = restartBtnRect.move(
            restartBtnRect.width / 2 - textObject.get_width() / 2,
            restartBtnRect.height / 2 - textObject.get_height() / 2
        )
        screen.blit(textObject, textLocation)

        # Draw undo button
        undoBtnRect = p.Rect(BOARD_WIDTH + 25, BOARD_HEIGHT - 80, 150, 50)
        p.draw.rect(screen, p.Color(DARK_SQUARE_COLOR), undoBtnRect)
        textObjectUndo = btnFont.render("Undo", True, p.Color('white'))
        textLocationUndo = undoBtnRect.move(
            undoBtnRect.width / 2 - textObjectUndo.get_width() / 2,
            undoBtnRect.height / 2 - textObjectUndo.get_height() / 2
        )
        screen.blit(textObjectUndo, textLocationUndo)

        btn_w = 200
        btn_h = 40
        diff_font = p.font.SysFont("Times New Roman", 20, True, False)

        # Mode Button (always visible)
        modeBtnRect = p.Rect(BOARD_WIDTH + MOVE_LOG_PANEL_WIDTH // 2 - btn_w // 2, BOARD_HEIGHT - 180, btn_w, btn_h)
        p.draw.rect(screen, p.Color(DARK_SQUARE_COLOR), modeBtnRect)
        p.draw.rect(screen, p.Color('black'), modeBtnRect, 1)
        mode_text = "Mode: Online Multiplayer" if multiplayerMode else "Mode: Local vs AI"
        textObj = diff_font.render(mode_text, True, p.Color('white'))
        textLoc = modeBtnRect.move(
            modeBtnRect.width / 2 - textObj.get_width() / 2,
            modeBtnRect.height / 2 - textObj.get_height() / 2
        )
        screen.blit(textObj, textLoc)

        if multiplayerMode:
            if not networkConnected:
                hostBtn = p.Rect(BOARD_WIDTH + MOVE_LOG_PANEL_WIDTH // 2 - btn_w // 2, BOARD_HEIGHT - 280, btn_w, btn_h)
                p.draw.rect(screen, p.Color(DARK_SQUARE_COLOR), hostBtn)
                p.draw.rect(screen, p.Color('black'), hostBtn, 1)
                textObj = diff_font.render("Host Game (White)", True, p.Color('white'))
                screen.blit(textObj, hostBtn.move(hostBtn.width / 2 - textObj.get_width() / 2, hostBtn.height / 2 - textObj.get_height() / 2))

                inputRect = p.Rect(BOARD_WIDTH + MOVE_LOG_PANEL_WIDTH // 2 - btn_w // 2, BOARD_HEIGHT - 330, btn_w, btn_h)
                color = p.Color('white') if inputBoxActive else p.Color('lightgray')
                p.draw.rect(screen, color, inputRect)
                p.draw.rect(screen, p.Color('black'), inputRect, 1)
                textObj = diff_font.render(roomCode if roomCode else "Type Room ID", True, p.Color('black'))
                screen.blit(textObj, inputRect.move(inputRect.width / 2 - textObj.get_width() / 2, inputRect.height / 2 - textObj.get_height() / 2))

                joinBtn = p.Rect(BOARD_WIDTH + MOVE_LOG_PANEL_WIDTH // 2 - btn_w // 2, BOARD_HEIGHT - 230, btn_w, btn_h)
                p.draw.rect(screen, p.Color(DARK_SQUARE_COLOR), joinBtn)
                p.draw.rect(screen, p.Color('black'), joinBtn, 1)
                textObj = diff_font.render("Join Game (Black)", True, p.Color('white'))
                screen.blit(textObj, joinBtn.move(joinBtn.width / 2 - textObj.get_width() / 2, joinBtn.height / 2 - textObj.get_height() / 2))
            else:
                infoRect = p.Rect(BOARD_WIDTH + MOVE_LOG_PANEL_WIDTH // 2 - btn_w // 2, BOARD_HEIGHT - 230, btn_w, btn_h)
                textObj = diff_font.render(f"Connected to Room: {roomCode}", True, p.Color('black'))
                screen.blit(textObj, infoRect.move(infoRect.width / 2 - textObj.get_width() / 2, infoRect.height / 2 - textObj.get_height() / 2))
                
                if opponentRequestedUndo:
                    panel_rect = p.Rect(BOARD_WIDTH + 20, BOARD_HEIGHT - 350, MOVE_LOG_PANEL_WIDTH - 40, 100)
                    p.draw.rect(screen, p.Color(LIGHT_SQUARE_COLOR), panel_rect)
                    p.draw.rect(screen, p.Color("red"), panel_rect, 2)
                    textObj = diff_font.render("Opponent requested an Undo!", True, p.Color('black'))
                    screen.blit(textObj, panel_rect.move(10, 10))
                    
                    acceptBtn = p.Rect(panel_rect.x, panel_rect.y + 40, panel_rect.width // 2 - 5, 40)
                    denyBtn = p.Rect(panel_rect.x + panel_rect.width // 2 + 5, panel_rect.y + 40, panel_rect.width // 2 - 5, 40)
                    
                    p.draw.rect(screen, p.Color("green"), acceptBtn)
                    tAccept = diff_font.render("Accept", True, p.Color("white"))
                    screen.blit(tAccept, acceptBtn.move(acceptBtn.width/2 - tAccept.get_width()/2, 10))
                    
                    p.draw.rect(screen, p.Color("red"), denyBtn)
                    tDeny = diff_font.render("Deny", True, p.Color("white"))
                    screen.blit(tDeny, denyBtn.move(denyBtn.width/2 - tDeny.get_width()/2, 10))

        else:
            # Draw Dropdown
            dropdownMainRect = p.Rect(BOARD_WIDTH + MOVE_LOG_PANEL_WIDTH // 2 - btn_w // 2, BOARD_HEIGHT - 130, btn_w, btn_h)
            p.draw.rect(screen, p.Color(DARK_SQUARE_COLOR), dropdownMainRect)
            p.draw.rect(screen, p.Color('black'), dropdownMainRect, 1)

            titles = ["Easy", "Normal", "Hard", "Very Hard", "Impossible"]
            main_text = f"Difficulty: {titles[chessAi.DEPTH - 1]} \u25B2" if dropdown_open else f"Difficulty: {titles[chessAi.DEPTH - 1]} \u25BC"
            textObj = diff_font.render(main_text, True, p.Color('white'))
            screen.blit(textObj, dropdownMainRect.move(dropdownMainRect.width / 2 - textObj.get_width() / 2, dropdownMainRect.height / 2 - textObj.get_height() / 2))

            if dropdown_open:
                for i in range(5):
                    optRect = p.Rect(BOARD_WIDTH + MOVE_LOG_PANEL_WIDTH // 2 - btn_w // 2, BOARD_HEIGHT - 130 - (5 - i) * btn_h, btn_w, btn_h)
                    mouse_pos = p.mouse.get_pos()
                    color = p.Color(MOVE_HIGHLIGHT_COLOR) if optRect.collidepoint(mouse_pos) else p.Color(DARK_SQUARE_COLOR)
                    p.draw.rect(screen, color, optRect)
                    p.draw.rect(screen, p.Color('black'), optRect, 1)
                    optTextObj = diff_font.render(titles[i], True, p.Color('white'))
                    screen.blit(optTextObj, optRect.move(optRect.width / 2 - optTextObj.get_width() / 2, optRect.height / 2 - optTextObj.get_height() / 2))

        if gameOver and p.time.get_ticks() - gameOverTime > 4000:
            gs = GameState()
            if gs.playerWantsToPlayAsBlack:
                gs.board = gs.board1
            validMoves = gs.getValidMoves()
            squareSelected = ()
            playerClicks = []
            moveMade = False
            animate = False
            gameOver = False
            moveUndone = True
            positionHistory = ""
            previousPos = ""
            countMovesForDraw = 0
            COUNT_DRAW = 0
            AIThinking = False
            gameOverTime = 0

        clock.tick(MAX_FPS)
        p.display.flip()
        await asyncio.sleep(0)


def drawGameState(screen, gs, validMoves, squareSelected, moveLogFont):
    drawSquare(screen)  # draw square on board
    highlightSquares(screen, gs, validMoves, squareSelected)
    
    # Check/Checkmate effect: Highlight the king's square in red
    if gs.inCheck:
        row, col = gs.whiteKinglocation if gs.whiteToMove else gs.blackKinglocation
        s = p.Surface((SQ_SIZE, SQ_SIZE))
        s.set_alpha(200 if gs.checkmate else 100) # Darker red for checkmate, lighter for check
        s.fill(p.Color("red"))
        screen.blit(s, (col * SQ_SIZE, row * SQ_SIZE))
        
    drawPieces(screen, gs.board)
    drawMoveLog(screen, gs, moveLogFont)


def drawSquare(screen):
    global colors
    colors = [p.Color(LIGHT_SQUARE_COLOR), p.Color(DARK_SQUARE_COLOR)]
    for row in range(DIMENSION):
        for col in range(DIMENSION):
            color = colors[((row + col) % 2)]
            p.draw.rect(screen, color, p.Rect(
                col * SQ_SIZE, row * SQ_SIZE, SQ_SIZE, SQ_SIZE))
                
    # Draw rank and file labels
    font = p.font.SysFont("Times New Roman", 14, True, False)
    for row in range(DIMENSION):
        # Draw rank labels (8 to 1)
        rank_text = str(8 - row)
        text_color = p.Color(DARK_SQUARE_COLOR) if (row % 2) == 0 else p.Color(LIGHT_SQUARE_COLOR)
        text_obj = font.render(rank_text, True, text_color)
        text_loc = p.Rect(0, row * SQ_SIZE, SQ_SIZE, SQ_SIZE).move(2, 2)
        screen.blit(text_obj, text_loc)

    for col in range(DIMENSION):
        # Draw file labels (a to h)
        file_text = chr(ord('a') + col)
        text_color = p.Color(DARK_SQUARE_COLOR) if (7 + col) % 2 == 0 else p.Color(LIGHT_SQUARE_COLOR)
        text_obj = font.render(file_text, True, text_color)
        text_loc = p.Rect(col * SQ_SIZE, 7 * SQ_SIZE, SQ_SIZE, SQ_SIZE).move(SQ_SIZE - text_obj.get_width() - 2, SQ_SIZE - text_obj.get_height() - 2)
        screen.blit(text_obj, text_loc)


def highlightSquares(screen, gs, validMoves, squareSelected):
    if squareSelected != ():  # make sure there is a square to select
        row, col = squareSelected
        # make sure they click there own piece
        if gs.board[row][col][0] == ('w' if gs.whiteToMove else 'b'):
            # highlight selected piece square
            # Surface in pygame used to add images or transperency feature
            s = p.Surface((SQ_SIZE, SQ_SIZE))
            # set_alpha --> transperancy value (0 transparent)
            s.set_alpha(100)
            s.fill(p.Color(MOVE_HIGHLIGHT_COLOR))
            screen.blit(s, (col*SQ_SIZE, row*SQ_SIZE))
            # highlighting valid square
            s.fill(p.Color(POSSIBLE_MOVE_COLOR))
            for move in validMoves:
                if move.startRow == row and move.startCol == col:
                    screen.blit(s, (move.endCol*SQ_SIZE, move.endRow*SQ_SIZE))


def drawPieces(screen, board):
    for row in range(DIMENSION):
        for col in range(DIMENSION):
            piece = board[row][col]
            if piece != "--":
                screen.blit(IMAGES[piece], p.Rect(
                    col * SQ_SIZE, row * SQ_SIZE, SQ_SIZE, SQ_SIZE))


def drawMoveLog(screen, gs, font):
    # rectangle
    moveLogRect = p.Rect(
        BOARD_WIDTH, 0, MOVE_LOG_PANEL_WIDTH, MOVE_LOG_PANEL_HEIGHT)
    p.draw.rect(screen, p.Color(LIGHT_SQUARE_COLOR), moveLogRect)
    moveLog = gs.moveLog
    moveTexts = []

    for i in range(0, len(moveLog), 2):
        moveString = " " + str(i//2 + 1) + ". " + str(moveLog[i]) + " "
        if i+1 < len(moveLog):
            moveString += str(moveLog[i+1])
        moveTexts.append(moveString)

    movesPerRow = 3
    padding = 10  # Increase padding for better readability
    lineSpacing = 5  # Increase line spacing for better separation
    textY = padding

    for i in range(0, len(moveTexts), movesPerRow):
        text = ""
        for j in range(movesPerRow):
            if i + j < len(moveTexts):
                text += moveTexts[i+j]

        textObject = font.render(text, True, p.Color('black'))

        # Adjust text location based on padding and line spacing
        textLocation = moveLogRect.move(padding, textY)
        screen.blit(textObject, textLocation)

        # Update Y coordinate for the next line with increased line spacing
        textY += textObject.get_height() + lineSpacing


# animating a move
def animateMove(move, screen, board, clock):
    global colors
    # change in row, col
    deltaRow = move.endRow - move.startRow
    deltaCol = move.endCol - move.startCol
    framesPerSquare = 5  # frames move one square
    # how many frame the animation will take
    frameCount = (abs(deltaRow) + abs(deltaCol)) * framesPerSquare
    # generate all the coordinates
    for frame in range(frameCount + 1):
        # how much does the row and col move by
        row, col = ((move.startRow + deltaRow*frame/frameCount, move.startCol +
                    deltaCol*frame/frameCount))  # how far through the animation
        # for each frame draw the moved piece
        drawSquare(screen)
        drawPieces(screen, board)

        # erase the piece moved from its ending squares
        color = colors[(move.endRow + move.endCol) %
                       2]  # get color of the square
        endSquare = p.Rect(move.endCol*SQ_SIZE, move.endRow *
                           SQ_SIZE, SQ_SIZE, SQ_SIZE)  # pygame rectangle
        p.draw.rect(screen, color, endSquare)

        # draw the captured piece back
        if move.pieceCaptured != '--':
            if move.isEnpassantMove:
                enPassantRow = move.endRow + \
                    1 if move.pieceCaptured[0] == 'b' else move.endRow - 1
                endSquare = p.Rect(move.endCol*SQ_SIZE, enPassantRow *
                                   SQ_SIZE, SQ_SIZE, SQ_SIZE)  # pygame rectangle
            screen.blit(IMAGES[move.pieceCaptured], endSquare)

        # draw moving piece
        screen.blit(IMAGES[move.pieceMoved], p.Rect(
            col*SQ_SIZE, row*SQ_SIZE, SQ_SIZE, SQ_SIZE))

        p.display.flip()
        clock.tick(240)


def drawEndGameText(screen, text):
    # create font object with type and size of font you want
    font = p.font.SysFont("Times New Roman", 45, False, False)
    # use the above font and render text (0 ? antialias)
    textObject = font.render(text, True, p.Color('black'))

    # Get the width and height of the textObject
    text_width = textObject.get_width()
    text_height = textObject.get_height()

    # Calculate the position to center the text on the screen
    textLocation = p.Rect(0, 0, BOARD_WIDTH, BOARD_HEIGHT).move(
        BOARD_WIDTH/2 - text_width/2, BOARD_HEIGHT/2 - text_height/2)

    # Blit the textObject onto the screen at the calculated position
    screen.blit(textObject, textLocation)

    # Create a second rendering of the text with a slight offset for a shadow effect
    textObject = font.render(text, 0, p.Color('Black'))
    screen.blit(textObject, textLocation.move(1, 1))

    # Add subtitle "Click anywhere to restart"
    subFont = p.font.SysFont("Times New Roman", 25, False, False)
    subTextObject = subFont.render("Click anywhere or wait to restart", True, p.Color('darkgray'))
    subLocation = p.Rect(0, 0, BOARD_WIDTH, BOARD_HEIGHT).move(
        BOARD_WIDTH/2 - subTextObject.get_width()/2, BOARD_HEIGHT/2 + text_height/2 + 20)
        
    screen.blit(subTextObject, subLocation)
    subTextObject = subFont.render("Click anywhere or wait to restart", 0, p.Color('Black'))
    screen.blit(subTextObject, subLocation.move(1, 1))


# if we import main then main function wont run it will run only while running this file
if __name__ == "__main__":
    asyncio.run(main())
