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
LEVEL_OPTIONS = [level[0] for level in chessAi.LEVELS]
SIDE_OPTIONS = ["White", "Black", "Random"]
# (label, (starting seconds, increment seconds per move)), None for no clock
CLOCK_OPTIONS = [("Off", None), ("1+0", (60, 0)), ("3+2", (180, 2)), ("5+0", (300, 0)),
                 ("10+5", (600, 5)), ("15+10", (900, 10))]
HINT_SECONDS = 1.0  # thinking time for hints, independent of the AI difficulty
ANALYSIS_SECONDS = 0.8  # thinking time per position when analyzing a finished game
# a move that loses at least this much (in pawns, against the best move) is marked in the move log
MOVE_MARKS = [(3.0, "??"), (1.5, "?"), (0.8, "?!")]  # blunder, mistake, inaccuracy
MARK_COLORS = {"??": (200, 30, 30), "?": (225, 110, 0), "?!": (185, 150, 0)}
EVAL_CAP = 10  # evaluations are capped at +-10 pawns before comparing, so won positions don't flag everything
# the AI accepts a draw offer only when its evaluation is below this (it is losing)
AI_DRAW_ACCEPT_SCORE = -1
PIECE_VALUES = {'Q': 9, 'R': 5, 'B': 3, 'N': 3, 'p': 1, 'K': 0}
# online: the player waiting for the opponent re-sends the game state this often (ms), so a dropped
# message is noticed and the side that is behind catches up; ntfy.sh allows about one message per 5s
HEARTBEAT_MS = 15000
SYNC_REPLY_MS = 2000  # at most one state reply to a player who is behind per this many ms


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
def panelLayout(modeIndex, connected, canRejoin=False, reviewing=False):
    if modeIndex == 0:  # Local vs AI
        rows = [['mode'], ['level', 'side'], ['clock', 'hint']]
    elif modeIndex == 1:  # Local 2-Player
        rows = [['mode'], ['clock', 'hint']]
    elif not connected:  # Online, choosing a room
        rows = [['mode'], ['room', 'clock'], ['host', 'join']]
        if canRejoin:
            rows.append(['rejoin'])
    else:  # Online, in a room
        rows = [['mode'], ['roomInfo']]
    rows.append(['save', 'load'])
    if reviewing:  # after the game: analysis and stepping through the moves
        rows += [['analyze'], ['first', 'prev', 'next', 'last']]
    else:
        rows.append(['resign', 'draw'])
    rows.append(['undo', 'restart'])

    rects = {}
    y = BOARD_HEIGHT - PANEL_PADDING - len(rows) * ROW_HEIGHT - (len(rows) - 1) * ROW_GAP
    for row in rows:
        # controls share the row width, 10px apart
        width = (CONTROL_WIDTH - 10 * (len(row) - 1)) // len(row)
        for i, name in enumerate(row):
            x = PANEL_X + PANEL_PADDING + i * (width + 10)
            if i == len(row) - 1:
                width = PANEL_X + MOVE_LOG_PANEL_WIDTH - PANEL_PADDING - x  # last one absorbs rounding
            rects[name] = p.Rect(x, y, width, ROW_HEIGHT)
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
    # online games are synced by sending the whole game state; the newer (game, version) wins
    onlineGame = 0  # game number in the room, bumped by every new game
    onlineVersion = 0  # bumped by every change to the game: move, undo, resignation, draw
    lastStateSent = 0  # ticks when we last sent our state
    lastStateHeard = 0  # ticks when we last heard a state matching ours
    lastSyncReply = 0  # ticks when we last answered a player who is behind
    savedSession = net.load_session()  # last room and role, offered as Rejoin

    moveUndone = False
    positionHistory = [gs.getPositionKey()]  # one position key per ply, for threefold repetition
    moveLogScroll = 0  # move log lines scrolled back from the latest
    gameResult = None  # (text, PGN result) when the game ended by resignation, agreement or time
    hintMove = None  # suggested move shown on the board
    hintState = None  # 'requested' -> 'searching' -> None
    statusText = ""  # short message shown at the bottom of the board
    statusUntil = 0
    # after the game: stepping through the moves, and the AI's analysis of them
    reviewPly = None  # number of moves shown on the board, None for the final position
    reviewGs = None  # the position at reviewPly
    reviewScroll = False  # scroll the move log to the shown move on the next draw
    analysis = None  # {'evals', 'best', 'bestSan', 'done', 'task'}, filled in while the analysis runs
    moveRects = []  # (rect, ply) of the moves in the log, for clicking

    timeControl = None  # (starting seconds, increment seconds) of the current game, None for no clock
    clocks = {'w': 0, 'b': 0}  # milliseconds left
    clockHistory = [dict(clocks)]  # clocks after each ply, so an undo can restore them
    lastClockTick = p.time.get_ticks()

    def showStatus(text, duration=3000):
        nonlocal statusText, statusUntil
        statusText = text
        statusUntil = p.time.get_ticks() + duration

    # leaves the review of a finished game and stops its analysis; the game is about to change
    def clearReview():
        nonlocal reviewPly, reviewGs, analysis
        if analysis is not None and analysis['task'] is not None:
            analysis['task'].cancel()
        reviewPly = None
        reviewGs = None
        analysis = None

    # shows the position after the first ply moves (the final position leaves the review)
    def reviewTo(ply):
        nonlocal reviewPly, reviewGs, reviewScroll
        ply = max(0, min(ply, len(gs.moveLog)))
        reviewScroll = True
        if ply == len(gs.moveLog):
            reviewPly = None
            reviewGs = None
            return
        reviewPly = ply
        reviewGs = GameState()
        if reviewGs.playerWantsToPlayAsBlack:
            reviewGs.board = reviewGs.board1
        for move in gs.moveLog[:ply]:
            reviewGs.makeMove(move)
        reviewGs.getValidMoves()  # sets the check flag for the red king square

    # searches every position of the finished game in the background; result fills in as it goes
    async def analyzeGame(result):
        try:
            log = list(gs.moveLog)
            board = GameState()
            if board.playerWantsToPlayAsBlack:
                board.board = board.board1
            moves = board.getValidMoves()
            history = [board.getPositionKey()]
            for i in range(len(log) + 1):
                if moves:
                    score, best, _ = await chessAi.searchPosition(board, moves, ANALYSIS_SECONDS, history=history)
                    result['best'].append(best.getCode())
                    result['bestSan'].append(board.getSan(best, moves))
                else:
                    score = -chessAi.CHECKMATE if board.inCheck else chessAi.STALEMATE
                    result['best'].append(None)
                    result['bestSan'].append(None)
                result['evals'].append(score if board.whiteToMove else -score)  # from White's point of view
                if i < len(log):
                    board.makeMove(board.findMoveByCode(log[i].getCode(), moves))
                    moves = board.getValidMoves()
                    history.append(board.getPositionKey())
        except Exception as e:
            print("Main: analysis failed:", e)
        result['done'] = True

    def resetGame():
        nonlocal gs, validMoves, squareSelected, playerClicks, moveMade, animate, gameOver, moveUndone
        nonlocal positionHistory, AIThinking, gameResult, hintMove, hintState, pendingPrompt, moveLogScroll
        nonlocal playerWhiteHuman, playerBlackHuman, timeControl, clocks, clockHistory, lastClockTick
        clearReview()
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
        clearReview()
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
        clearReview()
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

    # takes back the last move of color, and the reply after it, so it's color's turn again
    # returns False when color hasn't moved yet
    def takeBackMoveOf(color):
        plies = 0
        for move in reversed(gs.moveLog):
            plies += 1
            if move.pieceMoved[0] == color:
                takeBack(plies)
                return True
        return False

    # Undo button / z key outside online play
    def playerUndo():
        if currentModeIndex == 0:
            # take back the AI's reply too, so it's the player's turn again
            takeBackMoveOf('w' if playerWhiteHuman else 'b')
        elif gs.moveLog:
            takeBack(1)

    def sendOnline(message):
        message.update({'game': onlineGame, 'version': onlineVersion, 'role': multiplayerRole, 'sender': myPlayerId})
        asyncio.ensure_future(net.send(message))

    # the whole game, so a player who missed messages or rejoined can rebuild it
    def sendState(reason):
        nonlocal lastStateSent
        sendOnline({
            'type': 'state',
            'reason': reason,
            'moves': " ".join(move.getCode() for move in gs.moveLog),
            'tc': list(timeControl) if timeControl else None,
            'clocks': dict(clocks) if timeControl else None,
            'result': list(gameResult) if gameResult else None,
        })
        lastStateSent = p.time.get_ticks()

    # after every local change to an online game
    def publishChange(reason):
        nonlocal onlineVersion
        onlineVersion += 1
        sendState(reason)

    def startOnlineGame():  # a new game in the same room, keeping the time control
        nonlocal onlineGame, onlineVersion, timeControl, clocks, clockHistory
        keptTimeControl = timeControl
        resetGame()
        onlineGame += 1
        onlineVersion = 0
        timeControl = keptTimeControl
        startMs = timeControl[0] * 1000 if timeControl else 0
        clocks = {'w': startMs, 'b': startMs}
        clockHistory = [dict(clocks)]
        sendState('new_game')

    def connectOnline(role):
        nonlocal multiplayerRole, networkConnected, onlineGame, onlineVersion, savedSession, lastStateHeard
        multiplayerRole = role
        net.set_topic(roomCode)
        print(f"DEBUG: I am {role.upper()}. Full Network Topic: [{net.topic}]")
        networkConnected = True
        resetGame()
        onlineGame = 0
        onlineVersion = 0
        lastStateHeard = p.time.get_ticks()
        net.save_session(roomCode, role)
        savedSession = {'room': roomCode, 'role': role}
        # the opponent answers with the current game, so a rejoining player catches up
        sendOnline({'type': 'sync_request'})

    # rebuilds the game from a newer state: undo back to the common moves, then play the rest
    def adoptState(state):
        nonlocal onlineGame, onlineVersion, timeControl, clocks, gameResult, moveMade, animate
        nonlocal lastClockTick, pendingPrompt, squareSelected, playerClicks
        codes = str(state.get('moves') or "").split()
        newGame = state['game'] != onlineGame
        if newGame:
            resetGame()
        mine = [move.getCode() for move in gs.moveLog]
        common = 0
        while common < min(len(mine), len(codes)) and mine[common] == codes[common]:
            common += 1
        undone = len(mine) - common
        if undone:
            takeBack(undone)

        tc = state.get('tc')
        timeControl = (int(tc[0]), int(tc[1])) if isinstance(tc, list) and len(tc) == 2 else None
        added = 0
        for code in codes[common:]:
            move = gs.findMoveByCode(code, validMoves)
            if move is None:
                print(f"Main: State has an illegal move {code}, stopping there")
                break
            playMove(move, sound=(common + added == len(codes) - 1))  # one sound, for the last move
            added += 1

        stateClocks = state.get('clocks')
        if timeControl is not None and isinstance(stateClocks, dict):
            clocks = {'w': int(stateClocks.get('w', 0)), 'b': int(stateClocks.get('b', 0))}
            clockHistory[-1] = dict(clocks)
        lastClockTick = p.time.get_ticks()
        result = state.get('result')
        gameResult = (str(result[0]), str(result[1])) if isinstance(result, list) and len(result) == 2 else None
        onlineGame = state['game']
        onlineVersion = state['version']

        moveMade = True
        animate = added == 1 and undone == 0 and not newGame  # the usual case: the opponent's move
        squareSelected = ()
        playerClicks = []
        if undone or newGame:
            pendingPrompt = None
        if newGame and not codes:
            showStatus("New game started")
        elif state.get('reason') == 'undo':
            showStatus("Undo accepted")
        elif undone or added > 1 or (newGame and codes):
            showStatus("Caught up with the game (move %d)" % (len(gs.moveLog) // 2 + 1))

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
            return "Computer (" + LEVEL_OPTIONS[chessAi.LEVEL] + ")"
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
            'analyze': analysis is None and len(gs.moveLog) > 0,
            'first': shownPly() > 0,
            'prev': shownPly() > 0,
            'next': shownPly() < len(gs.moveLog),
            'last': shownPly() < len(gs.moveLog),
        }

    def shownPly():  # number of moves of the position on the board
        return len(gs.moveLog) if reviewPly is None else reviewPly

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
        nonlocal moveMade, moveUndone, clocks, clockHistory, gameResult
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
            # a game that ended by resignation or agreement is over too, so it can be reviewed (Undo resumes it)
            result = headers.get('Result')
            names = {'1-0': "White won", '0-1': "Black won", '1/2-1/2': "Draw"}
            if result in names and getOutcome(gs, positionHistory, None) is None:
                gameResult = (names[result] + " (PGN result)", result)
        # clocks start fresh from the loaded position
        clocks = dict(clockHistory[0])
        clockHistory = [dict(clocks) for _ in range(len(gs.moveLog) + 1)]
        moveMade = True
        moveUndone = True  # let the position show before the AI replies

    while running:

        if multiplayerMode and networkConnected:
            now = p.time.get_ticks()
            opponentRole = 'client' if multiplayerRole == 'host' else 'host'
            messages = [msg for msg in net.get_messages() if msg.get('sender') != myPlayerId]
            for msg in messages:
                print(f"Main: Received message type='{msg.get('type')}' from {msg.get('role')} sender={msg.get('sender', '???')}")

            # game states: a replay after joining can deliver many, so only the newest one is used
            newest = None
            for msg in messages:
                if msg.get('type') == 'state' and isinstance(msg.get('game'), int) and isinstance(msg.get('version'), int):
                    if newest is None or (msg['game'], msg['version']) > (newest['game'], newest['version']):
                        newest = msg
            if newest is not None:
                theirs = (newest['game'], newest['version'])
                mine = (onlineGame, onlineVersion)
                sameGame = (str(newest.get('moves') or "") == " ".join(move.getCode() for move in gs.moveLog)
                            and (newest.get('result') or None) == (list(gameResult) if gameResult else None)
                            and (newest.get('tc') or None) == (list(timeControl) if timeControl else None))
                if theirs > mine or (theirs == mine and not sameGame and multiplayerRole == 'client'):
                    # newer, or the same version told differently: the host's account wins
                    adoptState(newest)
                    lastStateHeard = now
                elif theirs == mine:
                    if sameGame:
                        lastStateHeard = now
                    elif now - lastSyncReply > SYNC_REPLY_MS:
                        sendState('sync')
                        lastSyncReply = now
                elif now - lastSyncReply > SYNC_REPLY_MS:
                    # they are behind (a message was lost, or they rejoined): send them the game
                    sendState('sync')
                    lastSyncReply = now

            # requests and offers only count when they come from the opponent about the current position,
            # which also skips stale ones replayed after joining
            for msg in messages:
                mtype = msg.get('type')
                if mtype == 'sync_request':
                    if now - lastSyncReply > SYNC_REPLY_MS:
                        sendState('sync')
                        lastSyncReply = now
                    continue
                current = (msg.get('role') == opponentRole and msg.get('game') == onlineGame
                           and msg.get('version') == onlineVersion)
                if not current:
                    continue
                if mtype == 'undo_request':
                    pendingPrompt = {'kind': 'undo', 'text': "Opponent requested an undo"}
                elif mtype == 'undo_declined':
                    showStatus("Opponent declined the undo")
                elif mtype == 'draw_offer':
                    if gameResult is None:
                        pendingPrompt = {'kind': 'draw', 'text': "Opponent offers a draw"}
                elif mtype == 'draw_declined':
                    showStatus("Opponent declined the draw")

        humanTurn = (gs.whiteToMove and playerWhiteHuman) or (
            not gs.whiteToMove and playerBlackHuman)
        if multiplayerMode and networkConnected:
            humanTurn = (gs.whiteToMove and multiplayerRole == 'host') or (not gs.whiteToMove and multiplayerRole == 'client')
        # Black at the bottom for the online guest, and when playing Black against the AI
        flip_board = (multiplayerMode and networkConnected and multiplayerRole == 'client') or \
            (currentModeIndex == 0 and playerBlackHuman and not playerWhiteHuman)
        canRejoin = currentModeIndex == 2 and not networkConnected and savedSession is not None

        # online: while waiting for the opponent (or after the game), keep re-sending our state so a
        # lost message can't leave both players waiting for each other
        if multiplayerMode and networkConnected:
            interval = HEARTBEAT_MS * (2 if gameOver else 1)
            if (gameOver or not humanTurn) and p.time.get_ticks() - max(lastStateSent, lastStateHeard) > interval:
                sendState('heartbeat')

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
                layout = panelLayout(currentModeIndex, networkConnected, canRejoin, gameOver)

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
                        chessAi.LEVEL = chosen
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
                            if accepted:
                                # the opponent's last move comes back, and our reply after it
                                takeBackMoveOf('b' if multiplayerRole == 'host' else 'w')
                                publishChange('undo')
                            else:
                                sendOnline({'type': 'undo_declined'})
                        elif kind == 'draw':
                            if accepted:
                                gameResult = ('Draw by agreement', '1/2-1/2')
                                publishChange('draw')
                            else:
                                sendOnline({'type': 'draw_declined'})
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
                        sendOnline({'type': 'undo_request'})
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
                    gameResult = resignationResult(myColor())
                    pendingPrompt = None
                    if multiplayerMode and networkConnected:
                        publishChange('resign')
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
                        sendOnline({'type': 'draw_offer'})
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
                    connectOnline('host')
                    await asyncio.sleep(0)  # yield so poll task can start
                elif clicked == 'join':
                    print("DEBUG: Join button clicked.")
                    connectOnline('client')
                    await asyncio.sleep(0)  # yield so poll task can start
                elif clicked == 'rejoin':
                    print("DEBUG: Rejoin button clicked.")
                    roomCode = savedSession['room']
                    connectOnline(savedSession['role'])
                    showStatus("Rejoining room " + roomCode)
                    await asyncio.sleep(0)  # yield so poll task can start

                elif clicked == 'analyze':
                    analysis = {'evals': [], 'best': [], 'bestSan': [], 'done': False, 'task': None}
                    analysis['task'] = asyncio.ensure_future(analyzeGame(analysis))
                elif clicked == 'first':
                    reviewTo(0)
                elif clicked == 'prev':
                    reviewTo(shownPly() - 1)
                elif clicked == 'next':
                    reviewTo(shownPly() + 1)
                elif clicked == 'last':
                    reviewTo(len(gs.moveLog))
                elif clicked is None and gameOver and location[0] >= BOARD_WIDTH:
                    # clicking a move in the log shows the position after it
                    for rect, ply in moveRects:
                        if rect.collidepoint(location):
                            reviewTo(ply + 1)

                elif clicked is None and location[0] < BOARD_WIDTH:  # board click
                    if gameOver:
                        if reviewPly is not None:
                            continue  # stepping through the moves; the board isn't playable
                        # clicking the board after the game starts a new one
                        if multiplayerMode and networkConnected:
                            startOnlineGame()
                        else:
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
                                    print(f"Main: Sending move {candidate.getCode()}")
                                    publishChange('move')
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

                # after the game, the arrow keys step through the moves
                if gameOver and e.key in (p.K_LEFT, p.K_RIGHT, p.K_HOME, p.K_END, p.K_UP, p.K_DOWN):
                    if e.key in (p.K_LEFT, p.K_UP):
                        reviewTo(shownPly() - 1)
                    elif e.key in (p.K_RIGHT, p.K_DOWN):
                        reviewTo(shownPly() + 1)
                    elif e.key == p.K_HOME:
                        reviewTo(0)
                    else:
                        reviewTo(len(gs.moveLog))
                    continue

                if e.key == p.K_z:  # undo when z is pressed
                    if multiplayerMode and networkConnected:
                        sendOnline({'type': 'undo_request'})
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
                AIMove = await findBestMove(gs, validMoves, history=positionHistory)
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
                _, suggestion, _ = await chessAi.searchPosition(gs, validMoves, HINT_SECONDS, history=positionHistory)
                if suggestion is None:
                    suggestion = findRandomMoves(validMoves)
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

        if not gameOver and reviewPly is not None:
            clearReview()  # the game went on (e.g. an undo from the opponent)
        # the board shows the reviewed position while stepping through a finished game
        shownGs = reviewGs if reviewGs is not None else gs
        if reviewGs is not None:
            drawGameState(screen, reviewGs, [], (), flip_board)
        else:
            drawGameState(screen, gs, validMoves, squareSelected, flip_board, hintMove)

        # side panel
        layout = panelLayout(currentModeIndex, networkConnected, canRejoin, gameOver)
        stripY = min(rect.y for rect in layout.values()) - ROW_GAP - STRIP_HEIGHT
        p.draw.rect(screen, p.Color(LIGHT_SQUARE_COLOR), p.Rect(PANEL_X, 0, MOVE_LOG_PANEL_WIDTH, MOVE_LOG_PANEL_HEIGHT))
        marks = moveMarks(analysis, gs.moveLog) if analysis else {}
        if gameOver:
            # below the moves: the shown position, its evaluation and the analysis
            infoRect = p.Rect(PANEL_X + 10, stripY - 60, MOVE_LOG_PANEL_WIDTH - 20, 54)
            moveLogScroll, moveRects = drawMoveLog(screen, gs, moveLogScroll, STRIP_HEIGHT, infoRect.y - 4,
                                                   shownPly() - 1, marks, reviewScroll)
            drawReviewInfo(screen, infoRect, gs.moveLog, shownPly(), analysis, marks, shownGs.checkmate)
        else:
            moveLogScroll, moveRects = drawMoveLog(screen, gs, moveLogScroll, STRIP_HEIGHT, stripY)
        reviewScroll = False
        taken = capturedPieces(shownGs)
        balance = materialBalance(shownGs.board)
        sideToMove = 'w' if shownGs.whiteToMove else 'b'
        shownClocks = clockHistory[reviewPly] if reviewPly is not None and reviewPly < len(clockHistory) else clocks
        for color, y in ((('w' if flip_board else 'b'), 0), (('b' if flip_board else 'w'), stripY)):
            drawPlayerStrip(screen, y, color, playerName(color), taken[color],
                            balance if color == 'w' else -balance,
                            shownClocks[color] if timeControl else None,
                            clockRunning() and sideToMove == color)

        mouse_pos = p.mouse.get_pos()
        states = controlStates()
        labels = {
            'mode': "Mode: " + MODE_OPTIONS[currentModeIndex],
            'level': "AI: " + LEVEL_OPTIONS[chessAi.LEVEL],
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
            'first': "", 'prev': "", 'next': "", 'last': "",  # drawn as arrow icons
        }
        if analysis is None:
            labels['analyze'] = "Analyze game"
        elif not analysis['done']:
            labels['analyze'] = "Analyzing... %d/%d" % (len(analysis['evals']), len(gs.moveLog) + 1)
        else:
            labels['analyze'] = "Analysis done"
        if savedSession:
            labels['rejoin'] = "Rejoin %s as %s" % (savedSession['room'], "White" if savedSession['role'] == 'host' else "Black")
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
                stats_text = f"Game {onlineGame + 1}, change {onlineVersion} | Msgs: {net.msg_count} | Polls: {net.poll_count} | {net.last_status}"
                statsObj = get_text_surface(stats_text, 14, "gray", False)
                screen.blit(statsObj, (rect.centerx - statsObj.get_width() / 2, rect.y + 24))
            else:
                arrow = None
                if name in ('mode', 'level', 'side', 'clock'):
                    arrow = 'up' if openDropdown == name else 'down'
                drawButton(screen, rect, labels[name], states.get(name, True), mouse_pos, arrow)
                if name in ('first', 'prev', 'next', 'last'):
                    drawNavIcon(screen, rect, name)

        if gameOver and reviewPly is None:
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
    textObj = get_fitting_text(text, textArea, 24 if rect.width > CONTROL_WIDTH // 2 + 5 else 20, "white")
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
# currentPly: index of the move to highlight; marks: ply -> (mark, loss) from the analysis
# follow: scroll so the highlighted move is visible
# returns the scroll offset clamped to the available lines, and (rect, ply) of each move drawn
def drawMoveLog(screen, gs, scroll, top, bottom, currentPly=None, marks=None, follow=False):
    moveLog = gs.moveLog
    marks = marks or {}
    lineCount = (len(moveLog) + 3) // 4
    padding = 8
    lineHeight = 24
    # only show the lines that fit, newest at the bottom
    visibleLines = max(1, (bottom - top - 2 * padding) // lineHeight)
    if follow and currentPly is not None:
        line = max(currentPly, 0) // 4
        start = max(0, lineCount - visibleLines - scroll)
        if line < start:
            scroll = lineCount - visibleLines - line
        elif line >= start + visibleLines:
            scroll = lineCount - 1 - line
    scroll = min(max(scroll, 0), max(0, lineCount - visibleLines))
    start = max(0, lineCount - visibleLines - scroll)

    rects = []
    for i in range(start * 4, min(len(moveLog), (start + visibleLines) * 4)):
        y = top + padding + (i // 4 - start) * lineHeight
        x = PANEL_X + 10 + ((i % 4) // 2) * 180
        if i % 2 == 0:
            numberObj = get_text_surface(str(i // 2 + 1) + ".", 18, "dimgray", False)
            screen.blit(numberObj, (x + 30 - numberObj.get_width(), y))  # right-aligned
        moveX = x + (36 if i % 2 == 0 else 106)
        rect = p.Rect(moveX - 3, y - 1, 68, lineHeight - 2)
        if i == currentPly:
            p.draw.rect(screen, p.Color(LAST_MOVE_COLOR), rect)
        textObj = get_text_surface(moveLog[i].san or str(moveLog[i]), 18, "black", False)
        screen.blit(textObj, (moveX, y))
        if i in marks:
            mark = marks[i][0]
            markObj = get_text_surface(mark, 16, MARK_COLORS[mark], True)
            screen.blit(markObj, (moveX + textObj.get_width() + 1, y + 1))
        rects.append((rect, i))

    return scroll, rects


# the shown position, its evaluation and what the analysis says about the move that led to it
def drawReviewInfo(screen, rect, moveLog, ply, analysis, marks, isCheckmate):
    p.draw.rect(screen, p.Color(STRIP_COLOR), rect)
    p.draw.rect(screen, p.Color(DARK_SQUARE_COLOR), rect, 1)
    if ply == 0:
        first = "Start position"
    else:
        i = ply - 1
        first = "After %d.%s %s" % (i // 2 + 1, "" if i % 2 == 0 else "..", moveLog[i].san or str(moveLog[i]))
    evals = analysis['evals'] if analysis else []
    if isCheckmate:
        first += "   Checkmate"
    elif ply < len(evals):
        first += "   Eval " + formatEval(evals[ply])

    if ply > 0 and ply - 1 in marks:
        mark, loss = marks[ply - 1]
        kind = {"??": "Blunder", "?": "Mistake", "?!": "Inaccuracy"}[mark]
        second = "%s: loses %.1f. Best was %s" % (kind, loss, analysis['bestSan'][ply - 1])
    elif analysis and not analysis['done']:
        second = "Analyzing the game..."
    elif analysis:
        counts = {(color, mark): 0 for color in "wb" for mark, _ in MARK_COLORS.items()}
        for i, (mark, _) in marks.items():
            counts[('w' if i % 2 == 0 else 'b', mark)] += 1
        second = "   ".join("%s ??%d ?%d ?!%d" % (name, counts[(c, "??")], counts[(c, "?")], counts[(c, "?!")])
                             for c, name in (('w', "White"), ('b', "Black")))
    else:
        second = "Step through the moves with the arrow keys"
    screen.blit(get_fitting_text(first, rect.width - 16, 17, "black", True), (rect.x + 8, rect.y + 5))
    screen.blit(get_fitting_text(second, rect.width - 16, 16, "dimgray", False), (rect.x + 8, rect.y + 29))


def drawNavIcon(screen, rect, name):
    cx, cy = rect.center
    white = p.Color('white')
    if name in ('first', 'prev'):
        tip = cx - 5 if name == 'prev' else cx - 3
        p.draw.polygon(screen, white, [(tip, cy), (tip + 11, cy - 8), (tip + 11, cy + 8)])
        if name == 'first':
            p.draw.rect(screen, white, p.Rect(tip - 5, cy - 8, 3, 17))
    else:
        tip = cx + 5 if name == 'next' else cx + 3
        p.draw.polygon(screen, white, [(tip, cy), (tip - 11, cy - 8), (tip - 11, cy + 8)])
        if name == 'last':
            p.draw.rect(screen, white, p.Rect(tip + 3, cy - 8, 3, 17))


# ply -> (mark, pawns lost) for the analysed moves that lost enough against the best move
def moveMarks(analysis, moveLog):
    marks = {}
    evals = analysis['evals']
    for i in range(min(len(moveLog), len(evals) - 1)):
        if analysis['best'][i] == moveLog[i].getCode():
            continue  # the best move can't be a mistake, whatever deeper searches say
        sign = 1 if i % 2 == 0 else -1  # White moves on even plies
        loss = sign * (capEval(evals[i]) - capEval(evals[i + 1]))
        for threshold, mark in MOVE_MARKS:
            if loss >= threshold:
                marks[i] = (mark, loss)
                break
    return marks


def capEval(score):
    return max(-EVAL_CAP, min(EVAL_CAP, score))


# evaluation from White's point of view: "+1.3", or "#3" / "-#3" for a forced mate
def formatEval(score):
    if abs(score) > chessAi.MATE_THRESHOLD:
        moves = max(1, (chessAi.CHECKMATE - abs(score) + 1) // 2)
        return ("#" if score > 0 else "-#") + str(moves)
    return "%+.1f" % score



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
