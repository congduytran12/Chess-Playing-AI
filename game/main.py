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
import pgn
import random
import string
import time

# Explicitly seed random to fix deterministic room codes in WASM environments (Vercel)
random.seed(int(time.time() * 1000))

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
SMALL_IMAGES = {}  # piece icons for the captured pieces row
SMALL_PIECE_SIZE = 22
UI_CACHE = {}
FONT_CACHE = {}
# Liberation Serif, metric-compatible with Times New Roman (SIL Open Font License, see fonts/)
FONT_REGULAR = "fonts/LiberationSerif-Regular.ttf"
FONT_BOLD = "fonts/LiberationSerif-Bold.ttf"

# side panel: a player strip at the top and one above the controls, the move log in between,
# and rows of controls anchored to the bottom
PANEL_X = BOARD_WIDTH
PANEL_PADDING = 20
CONTROL_WIDTH = MOVE_LOG_PANEL_WIDTH - 2 * PANEL_PADDING
HALF_WIDTH = (CONTROL_WIDTH - 10) // 2
ROW_HEIGHT = 40
ROW_GAP = 8
STRIP_HEIGHT = 52

MODE_OPTIONS = ["Local vs AI", "Local 2-Player", "Online Multiplayer"]
LEVEL_OPTIONS = ["Easy", "Normal", "Hard", "Very Hard", "Impossible"]
SIDE_OPTIONS = ["White", "Black", "Random"]
# (label, (starting seconds, increment seconds per move)), None for no clock
CLOCK_OPTIONS = [("Off", None), ("1+0", (60, 0)), ("3+2", (180, 2)), ("5+0", (300, 0)),
                 ("10+5", (600, 5)), ("15+10", (900, 10))]
HINT_DEPTH = 3  # search depth used for hints, independent of the AI difficulty
# the AI accepts a draw offer only when its evaluation is below this (it is losing)
AI_DRAW_ACCEPT_SCORE = -1
PIECE_VALUES = {'Q': 9, 'R': 5, 'B': 3, 'N': 3, 'p': 1, 'K': 0}


def get_text_surface(text, size, color, bold=True):
    """
    Returns a cached text surface or renders a new one if not found.
    Reduces the number of font.render calls to once per dynamic change.
    """
    key = (text, size, color, bold)
    if key not in UI_CACHE:
        UI_CACHE[key] = get_font(size, bold).render(text, True, p.Color(color))
    return UI_CACHE[key]


# the font ships with the game: browsers have no system fonts, and SysFont there falls back
# to an already-bold sans font that turns smudgy when bolded again
# also used directly for text that changes every frame (clocks), which would otherwise fill the surface cache
def get_font(size, bold=True):
    key = (size, bold)
    if key not in FONT_CACHE:
        FONT_CACHE[key] = p.font.Font(FONT_BOLD if bold else FONT_REGULAR, size)
    return FONT_CACHE[key]


# largest text surface (up to size) that fits in maxWidth
def get_fitting_text(text, maxWidth, size, color, bold=True):
    surface = get_text_surface(text, size, color, bold)
    while surface.get_width() > maxWidth and size > 12:
        size -= 2
        surface = get_text_surface(text, size, color, bold)
    return surface


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
LAST_MOVE_COLOR = (205, 210, 106)
HINT_COLOR = (64, 160, 220)
STRIP_COLOR = (222, 224, 190)
DISABLED_COLOR = (165, 165, 165)

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
        SMALL_IMAGES[piece] = p.transform.smoothscale(
            original_image, (SMALL_PIECE_SIZE, SMALL_PIECE_SIZE))


# color is the side promoting ('w' or 'b'); returns 'Q', 'R', 'B' or 'N'
async def pawnPromotionPopup(screen, color):
    font = get_font(45, False)
    text = font.render("Choose promotion:", True, p.Color("black"))

    # Create buttons for promotion choices with images
    button_width, button_height = 150, 150
    buttons = [
        p.Rect(50, 300, button_width, button_height),
        p.Rect(225, 300, button_width, button_height),
        p.Rect(400, 300, button_width, button_height),
        p.Rect(575, 300, button_width, button_height)
    ]
    choices = ["Q", "R", "B", "N"]
    button_images = [p.transform.smoothscale(p.image.load("images1/" + color + piece + ".png"), (150, 150))
                     for piece in choices]

    while True:
        for e in p.event.get():
            if e.type == p.QUIT:
                p.quit()
                sys.exit()
            elif e.type == p.MOUSEBUTTONDOWN:
                mouse_pos = e.pos
                for i, button in enumerate(buttons):
                    if button.collidepoint(mouse_pos):
                        return choices[i]

        screen.fill(p.Color(LIGHT_SQUARE_COLOR))
        screen.blit(text, (110, 150))

        for i, button in enumerate(buttons):
            p.draw.rect(screen, p.Color("white"), button)
            screen.blit(button_images[i], button.topleft)

        p.display.flip()
        await asyncio.sleep(0) # Yield for browser UI


# rects of the panel controls, by name; which controls exist depends on the mode
def panelLayout(modeIndex, connected):
    if modeIndex == 0:  # Local vs AI
        rows = [['mode'], ['level', 'side'], ['clock', 'hint']]
    elif modeIndex == 1:  # Local 2-Player
        rows = [['mode'], ['clock', 'hint']]
    elif not connected:  # Online, choosing a room
        rows = [['mode'], ['room', 'clock'], ['host', 'join']]
    else:  # Online, in a room
        rows = [['mode'], ['roomInfo']]
    rows += [['save', 'load'], ['resign', 'draw'], ['undo', 'restart']]

    rects = {}
    y = BOARD_HEIGHT - PANEL_PADDING - len(rows) * ROW_HEIGHT - (len(rows) - 1) * ROW_GAP
    for row in rows:
        if len(row) == 1:
            rects[row[0]] = p.Rect(PANEL_X + PANEL_PADDING, y, CONTROL_WIDTH, ROW_HEIGHT)
        else:
            rects[row[0]] = p.Rect(PANEL_X + PANEL_PADDING, y, HALF_WIDTH, ROW_HEIGHT)
            rects[row[1]] = p.Rect(PANEL_X + MOVE_LOG_PANEL_WIDTH - PANEL_PADDING - HALF_WIDTH, y,
                                   HALF_WIDTH, ROW_HEIGHT)
        y += ROW_HEIGHT + ROW_GAP
    return rects


def dropdownLabels(name):
    if name == 'mode':
        return MODE_OPTIONS
    if name == 'level':
        return LEVEL_OPTIONS
    if name == 'side':
        return SIDE_OPTIONS
    return [label for label, _ in CLOCK_OPTIONS]


# dropdown options open upwards from the dropdown button
def dropdownOptionRects(rect, count):
    return [p.Rect(rect.x, rect.y - (count - i) * ROW_HEIGHT, rect.width, ROW_HEIGHT) for i in range(count)]


# Accept / Decline prompt for undo requests and draw offers, drawn over the move log
def promptRects():
    panel = p.Rect(PANEL_X + PANEL_PADDING, 150, CONTROL_WIDTH, 100)
    accept = p.Rect(panel.x + 10, panel.y + 48, panel.width // 2 - 15, 40)
    decline = p.Rect(panel.centerx + 5, panel.y + 48, panel.width // 2 - 15, 40)
    return panel, accept, decline


async def main():
    # initialize py game
    p.init()
    print("Main: v13.0 Loaded (Clocks, Hints, PGN)")
    screen = p.display.set_mode(
        (BOARD_WIDTH + MOVE_LOG_PANEL_WIDTH, BOARD_HEIGHT))
    if sys.platform == 'emscripten':
        # the page fits the canvas to the window using the canvas's aspect ratio, and may have done so
        # while the canvas was still its 1x1 placeholder (stretching the game into a square)
        try:
            import platform
            platform.window.window_resize()
        except Exception as e:
            print("Main: could not refit canvas:", e)

    clock = p.time.Clock()
    screen.fill(p.Color(LIGHT_SQUARE_COLOR))
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
    gameOver = False  # gameover if checkmate, stalemate, draw, resignation or time out
    playerWhiteHuman = not SET_WHITE_AS_BOT
    playerBlackHuman = not SET_BLACK_AS_BOT
    AIThinking = False  # True if ai is thinking
    openDropdown = None  # name of the dropdown whose options are showing

    currentModeIndex = 0 # 0: Local vs AI, 1: Local 2-Player, 2: Online Multiplayer
    sideIndex = 0  # vs AI: play as White, Black or Random
    clockIndex = 0  # index into CLOCK_OPTIONS
    multiplayerMode = False
    multiplayerRole = None
    roomCode = ""
    inputBoxActive = False
    myPlayerId = "".join(random.choices(string.ascii_letters + string.digits, k=10))
    networkConnected = False
    pendingPrompt = None  # {'kind': 'undo' | 'draw' | 'localDraw', 'text': ...} waiting for Accept / Decline

    moveUndone = False
    positionHistory = [gs.getPositionKey()]  # one position key per ply, for threefold repetition
    moveLogScroll = 0  # move log lines scrolled back from the latest
    gameResult = None  # (text, PGN result) when the game ended by resignation, agreement or time
    hintMove = None  # suggested move shown on the board
    hintState = None  # 'requested' -> 'searching' -> None
    statusText = ""  # short message shown at the bottom of the board
    statusUntil = 0

    timeControl = None  # (starting seconds, increment seconds) of the current game, None for no clock
    clocks = {'w': 0, 'b': 0}  # milliseconds left
    clockHistory = [dict(clocks)]  # clocks after each ply, so an undo can restore them
    lastClockTick = p.time.get_ticks()

    def showStatus(text, duration=3000):
        nonlocal statusText, statusUntil
        statusText = text
        statusUntil = p.time.get_ticks() + duration

    def resetGame():
        nonlocal gs, validMoves, squareSelected, playerClicks, moveMade, animate, gameOver, moveUndone
        nonlocal positionHistory, AIThinking, gameResult, hintMove, hintState, pendingPrompt, moveLogScroll
        nonlocal playerWhiteHuman, playerBlackHuman, timeControl, clocks, clockHistory, lastClockTick
        gs = GameState()
        if gs.playerWantsToPlayAsBlack:
            gs.board = gs.board1
        validMoves = gs.getValidMoves()
        squareSelected = ()
        playerClicks = []
        moveMade = False
        animate = False
        gameOver = False
        moveUndone = False
        positionHistory = [gs.getPositionKey()]
        AIThinking = False
        gameResult = None
        hintMove = None
        hintState = None
        pendingPrompt = None
        moveLogScroll = 0
        if currentModeIndex == 0:
            humanColor = random.choice('wb') if SIDE_OPTIONS[sideIndex] == "Random" else 'wb'[sideIndex]
            playerWhiteHuman = humanColor == 'w'
            playerBlackHuman = humanColor == 'b'
        elif currentModeIndex == 1:
            playerWhiteHuman = playerBlackHuman = True
        timeControl = CLOCK_OPTIONS[clockIndex][1]
        startMs = timeControl[0] * 1000 if timeControl else 0
        clocks = {'w': startMs, 'b': startMs}
        clockHistory = [dict(clocks)]
        lastClockTick = p.time.get_ticks()

    # clocks run from the first move until the game ends
    def clockRunning():
        return (timeControl is not None and not gameOver and gameResult is None and len(gs.moveLog) > 0
                and (currentModeIndex != 2 or networkConnected))

    # the side to move pays for the time since the last charge
    def chargeClock():
        nonlocal lastClockTick
        now = p.time.get_ticks()
        if clockRunning():
            clocks['w' if gs.whiteToMove else 'b'] -= now - lastClockTick
        lastClockTick = now

    # every move of the game (player, AI, opponent or loaded) goes through here
    def playMove(move, sound=True):
        nonlocal validMoves, hintMove, moveLogScroll
        chargeClock()
        mover = move.pieceMoved[0]
        validMoves = gs.makeMoveWithSan(move, validMoves)
        if timeControl is not None:
            clocks[mover] += timeControl[1] * 1000
        del clockHistory[len(gs.moveLog):]
        clockHistory.append(dict(clocks))
        updatePositionHistory(gs, positionHistory)
        hintMove = None
        moveLogScroll = 0  # jump back to the latest moves
        if sound:
            if move.isPawnPromotion:
                promote_sound.play()
            elif move.isCapture:
                capture_sound.play()
            else:
                move_sound.play()

    # undo plies and restore everything tied to them
    def takeBack(plies):
        nonlocal moveMade, animate, gameOver, moveUndone, squareSelected, playerClicks
        nonlocal gameResult, hintMove, hintState, clocks, lastClockTick
        for _ in range(plies):
            gs.undoMove()
        updatePositionHistory(gs, positionHistory)
        del clockHistory[len(gs.moveLog) + 1:]
        clocks = dict(clockHistory[-1])
        lastClockTick = p.time.get_ticks()
        moveMade = True
        animate = False
        gameOver = False
        moveUndone = True
        squareSelected = ()
        playerClicks = []
        gameResult = None
        hintMove = None
        hintState = None

    # Undo button / z key outside online play
    def playerUndo():
        if currentModeIndex == 0:
            # take back the AI's reply too, so it's the player's turn again
            humanColor = 'w' if playerWhiteHuman else 'b'
            plies = 0
            for move in reversed(gs.moveLog):
                plies += 1
                if move.pieceMoved[0] == humanColor:
                    takeBack(plies)
                    return
        elif gs.moveLog:
            takeBack(1)

    def myColor():
        if currentModeIndex == 2:
            return 'w' if multiplayerRole == 'host' else 'b'
        if currentModeIndex == 0:
            return 'w' if playerWhiteHuman else 'b'
        return 'w' if gs.whiteToMove else 'b'  # local game: the side to move

    def playerName(color, forPgn=False):
        if currentModeIndex == 0:
            if (color == 'w') == playerWhiteHuman:
                return "Player" if forPgn else "You"
            return "Computer (" + LEVEL_OPTIONS[chessAi.DEPTH - 1] + ")"
        if currentModeIndex == 2 and networkConnected:
            if forPgn:
                return "Host" if color == 'w' else "Guest"
            return "You" if color == myColor() else "Opponent"
        return "White" if color == 'w' else "Black"

    # which controls can be clicked right now
    def controlStates():
        inProgress = not gameOver
        online = currentModeIndex == 2
        return {
            'hint': inProgress and humanTurn and not online and hintState is None,
            'resign': inProgress and (not online or networkConnected),
            'draw': inProgress and (not online or networkConnected) and pendingPrompt is None,
            'save': len(gs.moveLog) > 0,
            'load': not online,
            'join': bool(roomCode),
        }

    def savePgnFile():
        outcome = getOutcome(gs, positionHistory, gameResult)
        result = outcome[1] if outcome else '*'
        headers = [("Event", "Casual game"), ("Site", "Chess-Playing-AI"), ("Date", time.strftime("%Y.%m.%d")),
                   ("Round", "-"), ("White", playerName('w', True)), ("Black", playerName('b', True)),
                   ("Result", result)]
        if timeControl:
            headers.append(("TimeControl", "%d+%d" % timeControl))
        text = pgn.buildPgn(gs.moveLog, headers, result)
        showStatus(pgn.savePgn(text, time.strftime("chess-%Y%m%d-%H%M%S.pgn")))

    def loadPgnText(text):
        nonlocal moveMade, moveUndone, clocks, clockHistory
        headers, sans = pgn.parsePgn(text)
        if headers.get('SetUp') == '1' or 'FEN' in headers:
            showStatus("Games from a custom start position aren't supported")
            return
        resetGame()
        loaded = 0
        for san in sans:
            move = gs.findMoveBySan(san, validMoves)
            if move is None:
                break
            playMove(move, sound=False)
            loaded += 1
        if loaded < len(sans):
            showStatus("Stopped at move %d: can't play %s" % (loaded // 2 + 1, sans[loaded]), 5000)
        else:
            showStatus("Loaded %d moves" % loaded)
        # clocks start fresh from the loaded position
        clocks = dict(clockHistory[0])
        clockHistory = [dict(clocks) for _ in range(len(gs.moveLog) + 1)]
        moveMade = True
        moveUndone = True  # let the position show before the AI replies

    while running:

        if multiplayerMode and networkConnected:
            for msg in net.get_messages():
                if msg.get('sender') == myPlayerId:
                    continue
                mtype = msg.get('type')
                sender = msg.get('sender', '???')
                print(f"Main: Received message type='{mtype}' from sender={sender}")
                opponentColor = 'b' if multiplayerRole == 'host' else 'w'
                if mtype == 'join' and multiplayerRole == 'host':
                    pass
                elif mtype == 'move':
                    if gameResult is not None:
                        print("Main: Ignoring move after the game ended")
                        continue
                    try:
                        moveStr = msg.get('move')
                        startPoint = (int(moveStr[0][0]), int(moveStr[0][1]))
                        endPoint = (int(moveStr[1][0]), int(moveStr[1][1]))
                    except (TypeError, IndexError, ValueError):
                        print(f"Main: Ignoring malformed move message {msg}")
                        continue
                    # Match against our own legal moves so castling / en passant flags are set,
                    # and reject illegal moves or moves of our own pieces
                    remoteMove = None
                    for m in validMoves:
                        if (m.startRow, m.startCol) == startPoint and (m.endRow, m.endCol) == endPoint:
                            remoteMove = m
                            break
                    if remoteMove is None or remoteMove.pieceMoved[0] != opponentColor:
                        print(f"Main: Ignoring illegal move from {startPoint} to {endPoint}")
                        continue

                    # the host's time control applies to both players
                    if multiplayerRole == 'client':
                        tc = msg.get('tc')
                        newTimeControl = (int(tc[0]), int(tc[1])) if isinstance(tc, list) and len(tc) == 2 else None
                        if newTimeControl != timeControl:
                            timeControl = newTimeControl
                            if not gs.moveLog:
                                startMs = timeControl[0] * 1000 if timeControl else 0
                                clocks = {'w': startMs, 'b': startMs}
                                clockHistory = [dict(clocks)]

                    if remoteMove.isPawnPromotion:
                        promoPiece = msg.get('promoPiece')
                        remoteMove.promotionChoice = promoPiece if promoPiece in ('Q', 'R', 'B', 'N') else 'Q'
                    print(f"Main: Received move {remoteMove.getChessNotation()}")
                    playMove(remoteMove)
                    # the mover's own clock reading is the one that counts
                    remaining = msg.get('clock')
                    if timeControl is not None and isinstance(remaining, (int, float)):
                        clocks[opponentColor] = int(remaining)
                        clockHistory[-1] = dict(clocks)

                    moveMade = True
                    animate = True
                    squareSelected = ()
                    playerClicks = []
                elif mtype == 'undo_request':
                    pendingPrompt = {'kind': 'undo', 'text': "Opponent requested an undo"}
                elif mtype == 'undo_response':
                    if msg.get('accepted'):
                        takeBack(2)
                    else:
                        showStatus("Opponent declined the undo")
                elif mtype == 'resign':
                    if msg.get('color') in ('w', 'b'):
                        gameResult = resignationResult(msg.get('color'))
                        pendingPrompt = None
                elif mtype == 'draw_offer':
                    if gameResult is None:
                        pendingPrompt = {'kind': 'draw', 'text': "Opponent offers a draw"}
                elif mtype == 'draw_response':
                    if msg.get('accepted'):
                        gameResult = ('Draw by agreement', '1/2-1/2')
                    else:
                        showStatus("Opponent declined the draw")
                elif mtype == 'new_game':
                    resetGame()
                    showStatus("Opponent started a new game")

        humanTurn = (gs.whiteToMove and playerWhiteHuman) or (
            not gs.whiteToMove and playerBlackHuman)
        if multiplayerMode and networkConnected:
            humanTurn = (gs.whiteToMove and multiplayerRole == 'host') or (not gs.whiteToMove and multiplayerRole == 'client')
        # Black at the bottom for the online guest, and when playing Black against the AI
        flip_board = (multiplayerMode and networkConnected and multiplayerRole == 'client') or \
            (currentModeIndex == 0 and playerBlackHuman and not playerWhiteHuman)

        for e in p.event.get():
            if e.type == p.QUIT:
                running = False
            # Mouse Handler
            elif e.type == p.MOUSEWHEEL:
                if p.mouse.get_pos()[0] >= BOARD_WIDTH:
                    moveLogScroll += e.y  # wheel up scrolls back through older moves
            elif e.type == p.MOUSEBUTTONDOWN:
                if e.button in (4, 5):  # wheel also fires button events; handled by MOUSEWHEEL
                    continue
                location = p.mouse.get_pos()
                layout = panelLayout(currentModeIndex, networkConnected)

                # an open dropdown takes the click: choose an option or close it
                if openDropdown:
                    name = openDropdown
                    openDropdown = None
                    if name not in layout:
                        continue
                    chosen = None
                    for i, optRect in enumerate(dropdownOptionRects(layout[name], len(dropdownLabels(name)))):
                        if optRect.collidepoint(location):
                            chosen = i
                    if chosen is None:
                        continue
                    if name == 'level':
                        chessAi.DEPTH = chosen + 1
                    elif name == 'side':
                        if chosen != sideIndex or SIDE_OPTIONS[chosen] == "Random":
                            sideIndex = chosen
                            resetGame()
                    elif name == 'clock':
                        if chosen != clockIndex:
                            clockIndex = chosen
                            resetGame()
                    elif name == 'mode' and chosen != currentModeIndex:
                        currentModeIndex = chosen
                        multiplayerMode = currentModeIndex == 2
                        inputBoxActive = False
                        # Reset multiplayer state on every mode change
                        net.running = False
                        roomCode = ""
                        networkConnected = False
                        multiplayerRole = None
                        # Reset game on mode change
                        resetGame()
                    continue

                if pendingPrompt:
                    _, acceptRect, declineRect = promptRects()
                    if acceptRect.collidepoint(location) or declineRect.collidepoint(location):
                        accepted = acceptRect.collidepoint(location)
                        kind = pendingPrompt['kind']
                        pendingPrompt = None
                        if kind == 'undo':
                            asyncio.ensure_future(net.send({'type': 'undo_response', 'accepted': accepted, 'sender': myPlayerId}))
                            if accepted:
                                takeBack(2)
                        elif kind == 'draw':
                            asyncio.ensure_future(net.send({'type': 'draw_response', 'accepted': accepted, 'sender': myPlayerId}))
                            if accepted:
                                gameResult = ('Draw by agreement', '1/2-1/2')
                        elif kind == 'localDraw':
                            if accepted:
                                gameResult = ('Draw by agreement', '1/2-1/2')
                            else:
                                showStatus("Draw declined")
                        continue

                clicked = None
                for name, rect in layout.items():
                    if rect.collidepoint(location):
                        clicked = name
                inputBoxActive = clicked == 'room'
                if clicked is not None and not controlStates().get(clicked, True):
                    continue

                if clicked in ('mode', 'level', 'side', 'clock'):
                    openDropdown = clicked
                elif clicked == 'undo':
                    if multiplayerMode and networkConnected:
                        asyncio.ensure_future(net.send({'type': 'undo_request', 'sender': myPlayerId}))
                        showStatus("Undo request sent")
                    else:
                        playerUndo()
                elif clicked == 'restart':
                    # In multiplayer, reset network state so a fresh game can be hosted
                    if multiplayerMode:
                        net.running = False
                        roomCode = ""
                        networkConnected = False
                        multiplayerRole = None
                    resetGame()
                elif clicked == 'hint':
                    hintState = 'requested'
                    showStatus("Looking for a good move...", 10000)
                elif clicked == 'resign':
                    loser = myColor()
                    if multiplayerMode and networkConnected:
                        asyncio.ensure_future(net.send({'type': 'resign', 'color': loser, 'sender': myPlayerId}))
                    gameResult = resignationResult(loser)
                    pendingPrompt = None
                elif clicked == 'draw':
                    if currentModeIndex == 0:
                        aiSign = 1 if playerBlackHuman else -1  # scoreBoard is positive when White is better
                        if aiSign * chessAi.scoreBoard(gs) < AI_DRAW_ACCEPT_SCORE:
                            gameResult = ('Draw by agreement', '1/2-1/2')
                        else:
                            showStatus("The computer declines the draw")
                    elif currentModeIndex == 1:
                        offering = "White" if gs.whiteToMove else "Black"
                        pendingPrompt = {'kind': 'localDraw', 'text': offering + " offers a draw"}
                    else:
                        asyncio.ensure_future(net.send({'type': 'draw_offer', 'sender': myPlayerId}))
                        showStatus("Draw offer sent")
                elif clicked == 'save':
                    savePgnFile()
                elif clicked == 'load':
                    message = pgn.requestPgnLoad()
                    if message:
                        showStatus(message)
                elif clicked == 'host':
                    print("DEBUG: Host button clicked.")
                    if not roomCode:
                        roomCode = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
                    multiplayerRole = 'host'
                    net.set_topic(roomCode)
                    print(f"DEBUG: I am HOST. Full Network Topic: [{net.topic}]")
                    networkConnected = True
                    resetGame()
                    await asyncio.sleep(0)  # yield so poll task can start
                elif clicked == 'join':
                    print("DEBUG: Join button clicked.")
                    multiplayerRole = 'client'
                    net.set_topic(roomCode)
                    print(f"DEBUG: I am CLIENT. Full Network Topic: [{net.topic}]")
                    networkConnected = True
                    resetGame()
                    await asyncio.sleep(0)  # yield so poll task can start

                elif clicked is None and location[0] < BOARD_WIDTH:  # board click
                    if gameOver:
                        # clicking the board after the game starts a new one
                        if multiplayerMode and networkConnected:
                            asyncio.ensure_future(net.send({'type': 'new_game', 'sender': myPlayerId}))
                        resetGame()
                        continue
                    col = location[0]//SQ_SIZE
                    row = location[1]//SQ_SIZE
                    if flip_board:
                        row = 7 - row
                        col = 7 - col
                    # if user clicked on same square twice
                    if squareSelected == (row, col):
                        squareSelected = ()  # deselect
                        playerClicks = []  # clear player clicks
                    else:
                        squareSelected = (row, col)
                        # append player both clicks (place and destination)
                        playerClicks.append(squareSelected)
                    # after second click (at destination)
                    if len(playerClicks) == 2:
                        if not humanTurn:
                            print("Main: Wait for opponent turn.")
                            squareSelected = ()
                            playerClicks = []
                            continue

                        # user generated a move
                        move = Move(playerClicks[0], playerClicks[1], gs.board)
                        for candidate in validMoves:
                            # check if the move is in the validMoves
                            if move == candidate:
                                if candidate.isPawnPromotion:
                                    # Show pawn promotion popup and get the selected piece
                                    candidate.promotionChoice = await pawnPromotionPopup(screen, candidate.pieceMoved[0])
                                playMove(candidate)
                                if multiplayerMode and networkConnected:
                                    move_data = {
                                        'type': 'move',
                                        'move': [(candidate.startRow, candidate.startCol), (candidate.endRow, candidate.endCol)],
                                        'promo': candidate.isPawnPromotion,
                                        'promoPiece': candidate.promotionChoice if candidate.isPawnPromotion else "",
                                        'clock': clocks[candidate.pieceMoved[0]] if timeControl else None,
                                        'tc': list(timeControl) if timeControl else None,
                                        'sender': myPlayerId
                                    }
                                    print(f"Main: Sending move {candidate.getChessNotation()}")
                                    asyncio.ensure_future(net.send(move_data))
                                moveMade = True
                                animate = True
                                squareSelected = ()
                                playerClicks = []
                                break
                        if not moveMade:
                            playerClicks = [squareSelected]

            # Key Handler
            elif e.type == p.KEYDOWN:
                if inputBoxActive:
                    if e.key == p.K_BACKSPACE:
                        roomCode = roomCode[:-1]
                    elif e.key == p.K_RETURN:
                        inputBoxActive = False
                    else:
                        if len(roomCode) < 12:
                            roomCode += e.unicode.upper()
                    continue

                if e.key == p.K_z:  # undo when z is pressed
                    if multiplayerMode and networkConnected:
                        asyncio.ensure_future(net.send({'type': 'undo_request', 'sender': myPlayerId}))
                        showStatus("Undo request sent")
                        continue
                    playerUndo()
                if e.key == p.K_r:  # reset board when 'r' is pressed
                    resetGame()

        # clocks: charge the side to move and check for a flag fall
        chargeClock()
        if clockRunning():
            side = 'w' if gs.whiteToMove else 'b'
            if clocks[side] <= 0:
                clocks[side] = 0
                gameResult = timeoutResult(gs, side)
                pendingPrompt = None

        # a PGN file the player picked (arrives later in the browser)
        if currentModeIndex != 2:
            loadedText = pgn.takeLoadedPgn()
            if loadedText:
                loadPgnText(loadedText)

        # AI move finder
        if currentModeIndex == 0 and not gameOver and gameResult is None and not humanTurn and not moveUndone and validMoves:
            if not AIThinking:
                AIThinking = True
                await asyncio.sleep(0.1)
                AIMove = await findBestMove(gs, validMoves)
                if AIMove is None:
                    AIMove = findRandomMoves(validMoves)
                playMove(AIMove)  # promotes to a queen, which is what the AI always picks
                AIThinking = False
                moveMade = True
                animate = True
                squareSelected = ()
                playerClicks = []

        # hint: wait one frame so the "Looking..." message is on screen during the search
        if hintState == 'requested':
            hintState = 'searching'
        elif hintState == 'searching':
            hintState = None
            if humanTurn and not gameOver and gameResult is None and validMoves:
                savedDepth = chessAi.DEPTH
                chessAi.DEPTH = HINT_DEPTH
                try:
                    suggestion = await findBestMove(gs, list(validMoves))
                finally:
                    chessAi.DEPTH = savedDepth
                if suggestion is None:
                    suggestion = findRandomMoves(validMoves)
                # the search leaves check and pin flags from deeper positions behind
                validMoves = gs.getValidMoves()
                hintMove = suggestion
                showStatus("Hint: " + gs.getSan(suggestion, validMoves), 4000)

        # genetare new set of valid move if valid move is made
        if moveMade:
            updatePositionHistory(gs, positionHistory)
            if animate:
                await animateMove(gs.moveLog[-1], screen, gs.board, clock, flip_board)
            validMoves = gs.getValidMoves()
            moveMade = False
            animate = False
            moveUndone = False

        outcome = getOutcome(gs, positionHistory, gameResult)
        gameOver = outcome is not None
        if gameOver and pendingPrompt and pendingPrompt['kind'] != 'undo':
            pendingPrompt = None

        drawGameState(screen, gs, validMoves, squareSelected, flip_board, hintMove)

        # side panel
        layout = panelLayout(currentModeIndex, networkConnected)
        stripY = min(rect.y for rect in layout.values()) - ROW_GAP - STRIP_HEIGHT
        p.draw.rect(screen, p.Color(LIGHT_SQUARE_COLOR), p.Rect(PANEL_X, 0, MOVE_LOG_PANEL_WIDTH, MOVE_LOG_PANEL_HEIGHT))
        moveLogScroll = drawMoveLog(screen, gs, moveLogScroll, STRIP_HEIGHT, stripY)
        taken = capturedPieces(gs)
        balance = materialBalance(gs.board)
        sideToMove = 'w' if gs.whiteToMove else 'b'
        for color, y in ((('w' if flip_board else 'b'), 0), (('b' if flip_board else 'w'), stripY)):
            drawPlayerStrip(screen, y, color, playerName(color), taken[color],
                            balance if color == 'w' else -balance,
                            clocks[color] if timeControl else None,
                            clockRunning() and sideToMove == color)

        mouse_pos = p.mouse.get_pos()
        states = controlStates()
        labels = {
            'mode': "Mode: " + MODE_OPTIONS[currentModeIndex],
            'level': "AI: " + LEVEL_OPTIONS[chessAi.DEPTH - 1],
            'side': "Play as: " + SIDE_OPTIONS[sideIndex],
            'clock': "Clock: " + CLOCK_OPTIONS[clockIndex][0],
            'hint': "Hint",
            'host': "Host (White)",
            'join': "Join (Black)",
            'save': "Save PGN",
            'load': "Load PGN",
            'resign': "Resign",
            'draw': "Offer Draw",
            'undo': "Undo",
            'restart': "Restart",
        }
        for name, rect in layout.items():
            if name == 'room':
                p.draw.rect(screen, p.Color('white') if inputBoxActive else p.Color('lightgray'), rect)
                p.draw.rect(screen, p.Color('black'), rect, 1)
                textObj = get_fitting_text(roomCode if roomCode else "Type Room ID", rect.width - 12, 20, "black")
                screen.blit(textObj, rect.move(rect.width / 2 - textObj.get_width() / 2, rect.height / 2 - textObj.get_height() / 2))
            elif name == 'roomInfo':
                textObj = get_text_surface(f"Room: {roomCode}", 20, "black", True)
                textLoc = rect.move(rect.width / 2 - textObj.get_width() / 2, 0)
                screen.blit(textObj, textLoc)
                # Connection Indicator (Traffic Light System)
                if "HEALTHY" in net.last_status or "READY" in net.last_status:
                    dot_color = p.Color('green')
                elif "CONNECTING" in net.last_status or "INITIALIZING" in net.last_status or "RETRYING" in net.last_status:
                    dot_color = p.Color('orange')
                else:
                    dot_color = p.Color('red')
                p.draw.circle(screen, dot_color, (textLoc.x + textObj.get_width() + 15, textLoc.y + textObj.get_height() / 2), 6)
                # Network Stats
                stats_text = f"Msgs: {net.msg_count} | Polls: {net.poll_count} | {net.current_interval:.1f}s Wait | {net.last_status}"
                statsObj = get_text_surface(stats_text, 14, "gray", False)
                screen.blit(statsObj, (rect.centerx - statsObj.get_width() / 2, rect.y + 24))
            else:
                arrow = None
                if name in ('mode', 'level', 'side', 'clock'):
                    arrow = 'up' if openDropdown == name else 'down'
                drawButton(screen, rect, labels[name], states.get(name, True), mouse_pos, arrow)

        if gameOver:
            drawEndGameText(screen, outcome[0])

        # overlays: open dropdown options and the Accept / Decline prompt
        if openDropdown in layout:
            options = dropdownLabels(openDropdown)
            for i, optRect in enumerate(dropdownOptionRects(layout[openDropdown], len(options))):
                drawButton(screen, optRect, options[i], True, mouse_pos)
        if pendingPrompt:
            panel_rect, acceptBtn, denyBtn = promptRects()
            p.draw.rect(screen, p.Color(LIGHT_SQUARE_COLOR), panel_rect)
            p.draw.rect(screen, p.Color("red"), panel_rect, 2)
            textObj = get_fitting_text(pendingPrompt['text'], panel_rect.width - 20, 20, "black")
            screen.blit(textObj, (panel_rect.centerx - textObj.get_width() / 2, panel_rect.y + 12))
            p.draw.rect(screen, p.Color("green"), acceptBtn)
            tAccept = get_text_surface("Accept", 20, "white", True)
            screen.blit(tAccept, acceptBtn.move(acceptBtn.width/2 - tAccept.get_width()/2, acceptBtn.height/2 - tAccept.get_height()/2))
            p.draw.rect(screen, p.Color("red"), denyBtn)
            tDeny = get_text_surface("Decline", 20, "white", True)
            screen.blit(tDeny, denyBtn.move(denyBtn.width/2 - tDeny.get_width()/2, denyBtn.height/2 - tDeny.get_height()/2))
        if statusText and p.time.get_ticks() < statusUntil:
            drawStatus(screen, statusText)

        clock.tick(MAX_FPS)
        await asyncio.sleep(0) # Essential for WASM performance/UI responsiveness
        p.display.flip()
        await asyncio.sleep(0)


def drawButton(screen, rect, text, enabled=True, mouse_pos=(-1, -1), arrow=None):
    if not enabled:
        color = p.Color(DISABLED_COLOR)
    elif rect.collidepoint(mouse_pos):
        color = p.Color(MOVE_HIGHLIGHT_COLOR)
    else:
        color = p.Color(DARK_SQUARE_COLOR)
    p.draw.rect(screen, color, rect)
    p.draw.rect(screen, p.Color('black'), rect, 1)

    # leave room on the right for the dropdown arrow
    textArea = rect.width - (36 if arrow else 12)
    textObj = get_fitting_text(text, textArea, 24 if rect.width > HALF_WIDTH else 20, "white")
    textX = rect.x + (rect.width - (24 if arrow else 0)) / 2 - textObj.get_width() / 2
    screen.blit(textObj, (textX, rect.centery - textObj.get_height() / 2))

    if arrow:
        center_x = rect.right - 20
        center_y = rect.centery
        if arrow == 'up':
            p.draw.polygon(screen, p.Color('white'), [(center_x - 6, center_y + 4), (center_x + 6, center_y + 4), (center_x, center_y - 4)])
        else:
            p.draw.polygon(screen, p.Color('white'), [(center_x - 6, center_y - 4), (center_x + 6, center_y - 4), (center_x, center_y + 4)])


# name, captured pieces, material lead and clock of one player
def drawPlayerStrip(screen, y, color, name, captured, advantage, clockMs, clockActive):
    rect = p.Rect(PANEL_X, y, MOVE_LOG_PANEL_WIDTH, STRIP_HEIGHT)
    p.draw.rect(screen, p.Color(STRIP_COLOR), rect)
    p.draw.line(screen, p.Color(DARK_SQUARE_COLOR), (rect.x, rect.bottom - 1), (rect.right, rect.bottom - 1))

    # side marker and name
    p.draw.circle(screen, p.Color('white' if color == 'w' else 'black'), (rect.x + 18, rect.y + 15), 7)
    p.draw.circle(screen, p.Color('black'), (rect.x + 18, rect.y + 15), 7, 1)
    nameObj = get_text_surface(name, 18, "black", True)
    screen.blit(nameObj, (rect.x + 32, rect.y + 15 - nameObj.get_height() / 2))

    # captured pieces, grouped by type, then the material lead
    x = rect.x + 10
    previous = None
    for piece in captured:
        if previous is not None:
            x += 10 if piece == previous else 18
        screen.blit(SMALL_IMAGES[piece], (x, rect.y + 27))
        previous = piece
    if advantage > 0:
        leadObj = get_text_surface("+" + str(advantage), 16, "dimgray", True)
        screen.blit(leadObj, (x + (SMALL_PIECE_SIZE + 4 if captured else 0), rect.y + 38 - leadObj.get_height() / 2))

    if clockMs is not None:
        clockRect = p.Rect(rect.right - 12 - 96, rect.y + 8, 96, 36)
        p.draw.rect(screen, p.Color('white') if clockActive else p.Color(200, 200, 200), clockRect)
        p.draw.rect(screen, p.Color('black'), clockRect, 1)
        textColor = p.Color('red') if clockActive and clockMs < 20000 else p.Color('black')
        textObj = get_font(24, True).render(formatClock(clockMs), True, textColor)
        screen.blit(textObj, (clockRect.centerx - textObj.get_width() / 2, clockRect.centery - textObj.get_height() / 2))


def formatClock(ms):
    ms = max(0, ms)
    if ms < 10000:
        return "%.1f" % (ms / 1000)  # tenths in the last ten seconds
    seconds = (ms + 999) // 1000
    return "%d:%02d" % (seconds // 60, seconds % 60)


# pieces each side has taken, most valuable first
def capturedPieces(gs):
    taken = {'w': [], 'b': []}
    for move in gs.moveLog:
        if move.pieceCaptured != '--':
            taken[move.pieceMoved[0]].append(move.pieceCaptured)
    for color in taken:
        taken[color].sort(key=lambda piece: -PIECE_VALUES[piece[1]])
    return taken


# white material minus black material (promotions count as the new piece)
def materialBalance(board):
    balance = 0
    for row in board:
        for square in row:
            if square != '--':
                balance += PIECE_VALUES[square[1]] if square[0] == 'w' else -PIECE_VALUES[square[1]]
    return balance


def drawStatus(screen, text):
    textObj = get_fitting_text(text, BOARD_WIDTH - 60, 20, "white")
    rect = p.Rect(0, 0, textObj.get_width() + 30, textObj.get_height() + 14)
    rect.center = (BOARD_WIDTH // 2, BOARD_HEIGHT - 40)
    s = p.Surface(rect.size)
    s.set_alpha(210)
    s.fill(p.Color(40, 40, 40))
    screen.blit(s, rect.topleft)
    screen.blit(textObj, (rect.x + 15, rect.y + 7))


def drawGameState(screen, gs, validMoves, squareSelected, flip=False, hintMove=None):
    drawSquare(screen, flip)  # draw square on board
    # last move played, and the hint if one is showing
    if gs.moveLog:
        lastMove = gs.moveLog[-1]
        tintSquare(screen, lastMove.startRow, lastMove.startCol, LAST_MOVE_COLOR, 170, flip)
        tintSquare(screen, lastMove.endRow, lastMove.endCol, LAST_MOVE_COLOR, 170, flip)
    if hintMove is not None:
        tintSquare(screen, hintMove.startRow, hintMove.startCol, HINT_COLOR, 150, flip)
        tintSquare(screen, hintMove.endRow, hintMove.endCol, HINT_COLOR, 150, flip)
    highlightSquares(screen, gs, validMoves, squareSelected, flip)

    # Check/Checkmate effect: Highlight the king's square in red
    if gs.inCheck:
        row, col = gs.whiteKinglocation if gs.whiteToMove else gs.blackKinglocation
        if flip:
            row, col = 7 - row, 7 - col
        s = p.Surface((SQ_SIZE, SQ_SIZE))
        s.set_alpha(200 if gs.checkmate else 100)
        s.fill(p.Color("red"))
        screen.blit(s, (col * SQ_SIZE, row * SQ_SIZE))

    drawPieces(screen, gs.board, flip)


def tintSquare(screen, row, col, color, alpha, flip=False):
    if flip:
        row, col = 7 - row, 7 - col
    s = p.Surface((SQ_SIZE, SQ_SIZE))
    s.set_alpha(alpha)
    s.fill(p.Color(color))
    screen.blit(s, (col * SQ_SIZE, row * SQ_SIZE))


def drawSquare(screen, flip=False):
    global colors
    colors = [p.Color(LIGHT_SQUARE_COLOR), p.Color(DARK_SQUARE_COLOR)]
    for row in range(DIMENSION):
        for col in range(DIMENSION):
            color = colors[((row + col) % 2)]
            p.draw.rect(screen, color, p.Rect(
                col * SQ_SIZE, row * SQ_SIZE, SQ_SIZE, SQ_SIZE))

    # Draw rank and file labels
    for row in range(DIMENSION):
        # Draw rank labels (1 to 8 from bottom, or 8 to 1 when flipped)
        rank_num = (row + 1) if flip else (8 - row)
        rank_text = str(rank_num)
        text_color = "gray" # Simplified for better caching
        text_obj = get_text_surface(rank_text, 14, text_color, True)
        text_loc = p.Rect(0, row * SQ_SIZE, SQ_SIZE, SQ_SIZE).move(2, 2)
        screen.blit(text_obj, text_loc)

    for col in range(DIMENSION):
        # Draw file labels (a-h left to right, or h-a when flipped)
        file_char = chr(ord('h') - col) if flip else chr(ord('a') + col)
        file_text = file_char
        text_color = "gray"
        text_obj = get_text_surface(file_text, 14, text_color, True)
        text_loc = p.Rect(col * SQ_SIZE, 7 * SQ_SIZE, SQ_SIZE, SQ_SIZE).move(SQ_SIZE - text_obj.get_width() - 2, SQ_SIZE - text_obj.get_height() - 2)
        screen.blit(text_obj, text_loc)



def highlightSquares(screen, gs, validMoves, squareSelected, flip=False):
    if squareSelected != ():  # make sure there is a square to select
        row, col = squareSelected
        draw_row = (7 - row) if flip else row
        draw_col = (7 - col) if flip else col
        if gs.board[row][col][0] == ('w' if gs.whiteToMove else 'b'):  # only highlight if selected piece belongs to current player
            # highlight selected square
            s = p.Surface((SQ_SIZE, SQ_SIZE))
            s.set_alpha(100)  # transparency value
            s.fill(p.Color(MOVE_HIGHLIGHT_COLOR))
            screen.blit(s, (draw_col*SQ_SIZE, draw_row*SQ_SIZE))
            # highlighting valid square
            s.fill(p.Color(POSSIBLE_MOVE_COLOR))
            for move in validMoves:
                if move.startRow == row and move.startCol == col:
                    end_r = (7 - move.endRow) if flip else move.endRow
                    end_c = (7 - move.endCol) if flip else move.endCol
                    screen.blit(s, (end_c*SQ_SIZE, end_r*SQ_SIZE))


def drawPieces(screen, board, flip=False):
    for row in range(DIMENSION):
        for col in range(DIMENSION):
            piece = board[row][col]
            if piece != "--":
                draw_row = (7 - row) if flip else row
                draw_col = (7 - col) if flip else col
                screen.blit(IMAGES[piece], p.Rect(
                    draw_col * SQ_SIZE, draw_row * SQ_SIZE, SQ_SIZE, SQ_SIZE))


# draws the moves between top and bottom, two moves (white and black) per pair and two pairs per line
# returns the scroll offset clamped to the available lines
def drawMoveLog(screen, gs, scroll, top, bottom):
    moveLog = gs.moveLog
    pairs = []
    for i in range(0, len(moveLog), 2):
        whiteMove = moveLog[i].san or str(moveLog[i])
        blackMove = (moveLog[i + 1].san or str(moveLog[i + 1])) if i + 1 < len(moveLog) else ""
        pairs.append((str(i // 2 + 1) + ".", whiteMove, blackMove))
    lines = [pairs[i:i + 2] for i in range(0, len(pairs), 2)]

    padding = 8
    lineHeight = 24
    # only show the lines that fit, newest at the bottom
    visibleLines = max(1, (bottom - top - 2 * padding) // lineHeight)
    scroll = min(max(scroll, 0), max(0, len(lines) - visibleLines))
    start = max(0, len(lines) - visibleLines - scroll)

    textY = top + padding
    for line in lines[start:start + visibleLines]:
        for k, (number, whiteMove, blackMove) in enumerate(line):
            x = PANEL_X + 10 + k * 180
            numberObj = get_text_surface(number, 18, "dimgray", False)
            screen.blit(numberObj, (x + 30 - numberObj.get_width(), textY))  # right-aligned
            screen.blit(get_text_surface(whiteMove, 18, "black", False), (x + 36, textY))
            if blackMove:
                screen.blit(get_text_surface(blackMove, 18, "black", False), (x + 106, textY))
        textY += lineHeight

    return scroll



# animating a move
async def animateMove(move, screen, board, clock, flip=False):
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
        drawSquare(screen, flip)
        drawPieces(screen, board, flip)

        # erase the piece moved from its ending squares
        color = colors[(move.endRow + move.endCol) %
                       2]  # get color of the square

        draw_end_row = (7 - move.endRow) if flip else move.endRow
        draw_end_col = (7 - move.endCol) if flip else move.endCol

        endSquare = p.Rect(draw_end_col*SQ_SIZE, draw_end_row *
                           SQ_SIZE, SQ_SIZE, SQ_SIZE)  # pygame rectangle
        p.draw.rect(screen, color, endSquare)

        # draw the captured piece back
        if move.pieceCaptured != '--':
            if move.isEnpassantMove:
                enPassantRow = move.endRow + \
                    1 if move.pieceCaptured[0] == 'b' else move.endRow - 1

                draw_ep_row = (7 - enPassantRow) if flip else enPassantRow
                draw_ep_col = (7 - move.endCol) if flip else move.endCol

                endSquare = p.Rect(draw_ep_col*SQ_SIZE, draw_ep_row *
                                   SQ_SIZE, SQ_SIZE, SQ_SIZE)  # pygame rectangle
            screen.blit(IMAGES[move.pieceCaptured], endSquare)

        # draw moving piece
        draw_curr_row = (7 - row) if flip else row
        draw_curr_col = (7 - col) if flip else col

        screen.blit(IMAGES[move.pieceMoved], p.Rect(
            draw_curr_col*SQ_SIZE, draw_curr_row*SQ_SIZE, SQ_SIZE, SQ_SIZE))

        p.display.flip()
        await asyncio.sleep(0) # Yield for browser interaction


def drawEndGameText(screen, text):
    # use surface cache for end game text
    textObject = get_fitting_text(text, BOARD_WIDTH - 40, 45, "black")

    text_width = textObject.get_width()
    text_height = textObject.get_height()

    textLocation = p.Rect(0, 0, BOARD_WIDTH, BOARD_HEIGHT).move(
        BOARD_WIDTH/2 - text_width/2, BOARD_HEIGHT/2 - text_height/2)

    screen.blit(textObject, textLocation)
    # Shadow effect
    shadowObject = get_fitting_text(text, BOARD_WIDTH - 40, 45, "gray")
    screen.blit(shadowObject, textLocation.move(1, 1))

    # Add subtitle
    msg = "Click the board to play again"
    subTextObject = get_text_surface(msg, 25, "darkgray", False)
    subLocation = p.Rect(0, 0, BOARD_WIDTH, BOARD_HEIGHT).move(
        BOARD_WIDTH/2 - subTextObject.get_width()/2, BOARD_HEIGHT/2 + text_height/2 + 20)

    screen.blit(subTextObject, subLocation)
    subShadow = get_text_surface(msg, 25, "black", False)
    screen.blit(subShadow, subLocation.move(1, 1))


# keep one position key per ply plus the start position, so an undo just truncates the list
def updatePositionHistory(gs, positionHistory):
    del positionHistory[len(gs.moveLog) + 1:]
    if len(positionHistory) < len(gs.moveLog) + 1:
        positionHistory.append(gs.getPositionKey())


def getDrawReason(gs, positionHistory):
    if positionHistory and positionHistory.count(positionHistory[-1]) >= 3:
        return 'Draw by threefold repetition'
    if gs.fiftyMoveRuleReached():
        return 'Draw by 50-move rule'
    if gs.insufficientMaterial():
        return 'Draw by insufficient material'
    return None


# (text, PGN result) when the game is over, otherwise None; checkmate takes precedence over draws
def getOutcome(gs, positionHistory, gameResult):
    if gameResult is not None:
        return gameResult
    if gs.checkmate:
        return ('Black wins by checkmate', '0-1') if gs.whiteToMove else ('White wins by checkmate', '1-0')
    if gs.stalemate:
        return ('Stalemate', '1/2-1/2')
    reason = getDrawReason(gs, positionHistory)
    if reason:
        return (reason, '1/2-1/2')
    return None


def resignationResult(loser):
    if loser == 'w':
        return ('Black wins by resignation', '0-1')
    return ('White wins by resignation', '1-0')


# a flag fall loses, unless the opponent has only their king left
def timeoutResult(gs, flagged):
    winner = 'b' if flagged == 'w' else 'w'
    winnerHasMaterial = any(square[0] == winner and square[1] != 'K' for row in gs.board for square in row)
    if not winnerHasMaterial:
        return ('Draw: time out vs lone king', '1/2-1/2')
    if winner == 'w':
        return ('White wins on time', '1-0')
    return ('Black wins on time', '0-1')



# if we import main then main function wont run it will run only while running this file
if __name__ == "__main__":
    asyncio.run(main())
