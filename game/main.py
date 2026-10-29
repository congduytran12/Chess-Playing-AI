'''
    Add or remove bots :

    SET_WHITE_AS_BOT = False
    SET_BLACK_AS_BOT = True
'''

# Responsible for handling user input and displaying the current Gamestate object

import sys
import math
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
import hints
import settings
from account import account, AccountError
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
ANIMATION_FPS = 60  # moving pieces slide at up to this frame rate
ANIMATION_BASE_MS = 90  # a move's slide takes this long plus ANIMATION_MS_PER_SQUARE per square
ANIMATION_MS_PER_SQUARE = 30
AI_MIN_THINK_MS = 400  # the computer's move (even an instant opening book move) waits at least this long
IMAGES = {}
SMALL_IMAGES = {}  # piece icons for the captured pieces row
SMALL_PIECE_SIZE = 22
HELP_IMAGES = {}  # piece icons for the How to play window
HELP_ICON_SIZE = 40
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
STATUS_HEIGHT = 46  # the status message slot above the lower player strip
CONTROL_WEIGHTS = {'settings': 0.45}  # share of a row's width, against 1 for other controls (the gear is an icon)

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
PRESENCE_MS = 20000  # a player who has sent nothing for this long sends a 'ping', to show they're still there
OPPONENT_GONE_SECONDS = 60  # no message from the opponent for this long (server clock): they may have left
ROOM_CODE_CHARACTERS = string.ascii_letters + string.digits + "-_"


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
ARROW_COLOR = HINT_COLOR + (190,)  # hint arrows, and the better move in the analysis
ARROW_LAYER = None  # see-through board-sized surface the arrows are drawn on, made on first use
MOVE_MARKER_COLOR = (20, 60, 20, 90)  # dots and rings showing where the selected piece can go
MOVE_MARKERS = {}  # 'dot' / 'ring' surfaces, made on first use
STRIP_COLOR = (222, 224, 190)
DISABLED_COLOR = (165, 165, 165)
CONFIRM_COLOR = (186, 72, 58)  # the action of a confirmation that can't be taken back (Resign, Leave)
SELECTED_OPTION_COLOR = (82, 112, 54)  # the current choice in an open dropdown
NEUTRAL_COLOR = (118, 118, 118)  # Cancel / Decline

# the board's squares can be recolored in Settings (the side panel keeps the green colors above):
# name -> (light square, dark square)
BOARD_THEMES = {"Green": (LIGHT_SQUARE_COLOR, DARK_SQUARE_COLOR),
                "Brown": ((240, 217, 181), (181, 136, 99)),
                "Gray": ((220, 220, 220), (170, 170, 170))}
BOARD_COLORS = list(BOARD_THEMES["Green"])  # light and dark squares of the chosen theme
# piece styles: name -> image folder
PIECE_SETS = {"Modern": "images1", "Classic": "images"}
PIECES = ['bR', 'bN', 'bB', 'bQ', 'bK', 'bp', 'wR', 'wN', 'wB', 'wQ', 'wK', 'wp']


def setBoardTheme(name):
    BOARD_COLORS[:] = BOARD_THEMES.get(name, BOARD_THEMES["Green"])


# loads the pieces of a style from PIECE_SETS (the saved one when none is given)
def loadImages(pieceSet=None):
    folder = PIECE_SETS.get(pieceSet or settings.get('pieces'), PIECE_SETS["Modern"])
    for piece in PIECES:
        image_path = folder + "/" + piece + ".png"
        original_image = p.image.load(image_path)
        # p.transform.smoothscale is bit slower than p.transform.scale, using this to reduce pixelation and better visual quality for scaling images to larger sizes
        IMAGES[piece] = p.transform.smoothscale(
            original_image, (SQ_SIZE, SQ_SIZE))
        SMALL_IMAGES[piece] = p.transform.smoothscale(
            original_image, (SMALL_PIECE_SIZE, SMALL_PIECE_SIZE))
        HELP_IMAGES[piece] = p.transform.smoothscale(
            original_image, (HELP_ICON_SIZE, HELP_ICON_SIZE))


# the four pieces in a column over the promotion square, with the board dimmed behind them
# color is the side promoting ('w' or 'b'), row and col the promotion square; flip as in drawGameState
# returns 'Q', 'R', 'B' or 'N', or None when the player clicks elsewhere or presses Esc (to pick another move)
async def pawnPromotionPopup(screen, color, row, col, flip=False):
    drawRow = (7 - row) if flip else row
    drawCol = (7 - col) if flip else col
    step = 1 if drawRow == 0 else -1  # the column runs from the promotion square toward the middle
    choices = ["Q", "R", "B", "N"]
    buttons = [p.Rect(drawCol * SQ_SIZE, (drawRow + i * step) * SQ_SIZE, SQ_SIZE, SQ_SIZE) for i in range(4)]

    background = screen.copy()  # the board as it was when the pawn was moved
    shade = p.Surface((BOARD_WIDTH, BOARD_HEIGHT))
    shade.set_alpha(120)
    shade.fill(p.Color(0, 0, 0))
    background.blit(shade, (0, 0))
    clock = p.time.Clock()

    while True:
        for e in p.event.get():
            if e.type == p.QUIT:
                p.quit()
                sys.exit()
            elif e.type == p.KEYDOWN and e.key == p.K_ESCAPE:
                return None
            elif e.type == p.MOUSEBUTTONDOWN and e.button in (1, 2, 3):
                mouse_pos = p.mouse.get_pos()
                for i, button in enumerate(buttons):
                    if button.collidepoint(mouse_pos):
                        return choices[i]
                return None

        screen.blit(background, (0, 0))
        mouse_pos = p.mouse.get_pos()
        for i, button in enumerate(buttons):
            hovered = button.collidepoint(mouse_pos)
            p.draw.rect(screen, p.Color(LAST_MOVE_COLOR) if hovered else p.Color("white"), button)
            p.draw.rect(screen, p.Color(DARK_SQUARE_COLOR), button, 2)
            screen.blit(IMAGES[color + choices[i]], button.topleft)

        p.display.flip()
        clock.tick(MAX_FPS)
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
    rows.append(['save', 'load', 'help'])
    if reviewing:  # after the game: analysis and stepping through the moves
        rows += [['analyze'], ['first', 'prev', 'next', 'last']]
    else:
        rows.append(['resign', 'draw'])
    rows.append(['undo', 'restart', 'account', 'settings'])

    rects = {}
    y = BOARD_HEIGHT - PANEL_PADDING - len(rows) * ROW_HEIGHT - (len(rows) - 1) * ROW_GAP
    for row in rows:
        # controls share the row width, 10px apart; CONTROL_WEIGHTS makes some narrower
        unit = (CONTROL_WIDTH - 10 * (len(row) - 1)) / sum(CONTROL_WEIGHTS.get(name, 1) for name in row)
        x = PANEL_X + PANEL_PADDING
        for i, name in enumerate(row):
            width = round(unit * CONTROL_WEIGHTS.get(name, 1))
            if i == len(row) - 1:
                width = PANEL_X + MOVE_LOG_PANEL_WIDTH - PANEL_PADDING - x  # last one absorbs rounding
            rects[name] = p.Rect(x, y, width, ROW_HEIGHT)
            x += width + 10
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
    # the desktop window's title and icon (before set_mode: some systems ignore an icon set afterwards)
    p.display.set_caption("Chess Playing AI")
    try:
        p.display.set_icon(p.transform.smoothscale(p.image.load("images1/wN.png"), (64, 64)))
    except Exception as e:
        print("Main: could not set the window icon:", e)
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
    setBoardTheme(settings.get('board'))  # the board colors and pieces chosen in Settings last time
    loadImages()
    running = True
    squareSelected = ()  # keep tracks of last click
    # clicking to own piece and location where to move[(6,6),(4,4)]
    playerClicks = []
    gameOver = False  # gameover if checkmate, stalemate, draw, resignation or time out
    playerWhiteHuman = not SET_WHITE_AS_BOT
    playerBlackHuman = not SET_BLACK_AS_BOT
    # the computer's search while it thinks: {'task', 'gs', 'ply', 'started'}; it runs in the background on a
    # copy of the game, so the screen and the clocks keep updating
    aiSearch = None
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
    onlineGameId = ""  # random id of the current game, shared by both players (rating reports are matched by it)
    liveGameId = None  # id of the online game we saw in progress; a game that was already over when we joined isn't saved again
    lastStateSent = 0  # ticks when we last sent our state
    lastStateHeard = 0  # ticks when we last heard a state matching ours
    lastSyncReply = 0  # ticks when we last answered a player who is behind
    savedSession = net.load_session()  # last room and role, offered as Rejoin
    opponentInfo = None  # {'uid', 'name', 'rating'} of a signed-in online opponent
    opponentSeen = None  # ntfy server time of the opponent's latest message, None before they have sent any
    lastMessageSent = 0  # ticks when we last sent anything online

    # player account (see account.py): the account window, and saving finished games to the account
    accountView = None  # 'signin' | 'register' | 'profile' | 'games' | 'leaderboard' while the window is open
    helpPage = None  # page of the How to play window (index into HELP_PAGES) while it's open
    settingsOpen = False  # the Settings window is showing
    accountFields = {'username': "", 'email': "", 'login': "", 'password': ""}  # login: email or username, to sign in
    accountFocus = 'login'  # the form field being typed into
    accountMessage = ""  # error or notice shown in the account window
    accountList = []  # saved games or leaderboard rows shown in the window
    accountRequests = []  # running requests: (task, onDone, onError, shownInWindow)
    gameSaved = False  # the finished game was sent to the account
    savedGameId = None  # its id there, so finishing again after an undo updates it
    gameLoaded = False  # loaded from a file or the account, so not saved again
    ratingReported = False
    asyncio.ensure_future(account.restore())  # stays signed in from last time

    moveUndone = False
    positionHistory = [gs.getPositionKey()]  # one position key per ply, for threefold repetition
    moveLogScroll = 0  # move log lines scrolled back from the latest
    gameResult = None  # (text, PGN result) when the game ended by resignation, agreement or time
    resultCardHidden = False  # the player clicked beside the result card to see the final position
    outcome = None  # (text, PGN result) once the game is over, worked out every frame
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

    # cancels the computer's search; the game changed, so its answer wouldn't fit any more
    def stopAI():
        nonlocal aiSearch
        if aiSearch is not None:
            aiSearch['task'].cancel()
            aiSearch = None

    def resetGame():
        nonlocal gs, validMoves, squareSelected, playerClicks, moveMade, animate, gameOver, moveUndone
        nonlocal positionHistory, gameResult, hintMove, hintState, pendingPrompt, moveLogScroll, resultCardHidden
        nonlocal playerWhiteHuman, playerBlackHuman, timeControl, clocks, clockHistory, lastClockTick
        nonlocal gameSaved, savedGameId, gameLoaded, ratingReported
        clearReview()
        gameSaved = False
        savedGameId = None
        gameLoaded = False
        ratingReported = False
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
        stopAI()
        gameResult = None
        resultCardHidden = False
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

    # the result card's buttons: against the computer the player can also switch sides
    def resultButtons():
        return ['new', 'switch'] if currentModeIndex == 0 else ['new']

    # Restart button / r key: a new game, and in online play leaving the room so a new one can be hosted
    def restartGame():
        nonlocal roomCode, networkConnected, multiplayerRole
        if multiplayerMode:
            net.running = False
            roomCode = ""
            networkConnected = False
            multiplayerRole = None
        resetGame()

    # asks first when that would throw away a game in progress or leave an online room
    def askToRestart():
        nonlocal pendingPrompt
        if multiplayerMode and networkConnected:
            pendingPrompt = {'kind': 'restart', 'text': "Leave this room?", 'yes': "Leave", 'no': "Stay",
                             'confirm': True}
        elif gs.moveLog and not gameOver:
            pendingPrompt = {'kind': 'restart', 'text': "Start a new game?", 'yes': "Restart", 'no': "Cancel",
                             'confirm': True}
        else:
            restartGame()

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
        nonlocal gameResult, hintMove, hintState, clocks, lastClockTick, gameSaved, resultCardHidden
        clearReview()
        stopAI()
        resultCardHidden = False  # when the game ends again, its result shows again
        gameSaved = False  # if the game is finished again, its saved copy is updated
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
        nonlocal lastMessageSent
        lastMessageSent = p.time.get_ticks()
        message.update({'game': onlineGame, 'version': onlineVersion, 'role': multiplayerRole, 'sender': myPlayerId})
        if account.signedIn:  # lets the opponent show our name and report the result for ratings
            message['player'] = {'uid': account.profile['id'], 'name': account.username,
                                 'rating': account.profile['rating']}
        asyncio.ensure_future(net.send(message))

    # the whole game, so a player who missed messages or rejoined can rebuild it
    def sendState(reason):
        nonlocal lastStateSent
        sendOnline({
            'type': 'state',
            'reason': reason,
            'gid': onlineGameId,
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

    def newOnlineGameId():
        return "".join(random.choices(string.ascii_letters + string.digits, k=12))

    def startOnlineGame():  # a new game in the same room, keeping the time control
        nonlocal onlineGame, onlineVersion, onlineGameId, timeControl, clocks, clockHistory
        keptTimeControl = timeControl
        resetGame()
        onlineGame += 1
        onlineVersion = 0
        onlineGameId = newOnlineGameId()
        timeControl = keptTimeControl
        startMs = timeControl[0] * 1000 if timeControl else 0
        clocks = {'w': startMs, 'b': startMs}
        clockHistory = [dict(clocks)]
        sendState('new_game')

    def connectOnline(role):
        nonlocal multiplayerRole, networkConnected, onlineGame, onlineVersion, onlineGameId, savedSession, lastStateHeard
        nonlocal opponentInfo, opponentSeen
        multiplayerRole = role
        opponentInfo = None
        opponentSeen = None
        net.set_topic(roomCode)
        print(f"DEBUG: I am {role.upper()}. Full Network Topic: [{net.topic}]")
        networkConnected = True
        resetGame()
        onlineGame = 0
        onlineVersion = 0
        onlineGameId = newOnlineGameId()  # replaced by the opponent's when we catch up with their game
        lastStateHeard = p.time.get_ticks()
        net.save_session(roomCode, role)
        savedSession = {'room': roomCode, 'role': role}
        # the opponent answers with the current game, so a rejoining player catches up
        sendOnline({'type': 'sync_request'})

    # rebuilds the game from a newer state: undo back to the common moves, then play the rest
    def adoptState(state):
        nonlocal onlineGame, onlineVersion, onlineGameId, timeControl, clocks, gameResult, moveMade, animate
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
        onlineGameId = str(state.get('gid') or "")[:32]

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
                if account.signedIn:
                    return account.username
                return "Player" if forPgn else "You"
            return "Computer (" + LEVEL_OPTIONS[chessAi.LEVEL] + ")"
        if currentModeIndex == 2 and networkConnected:
            # signed-in players are shown by name and rating
            if color == myColor():
                info = {'name': account.username, 'rating': account.profile['rating']} if account.signedIn else None
            else:
                info = opponentInfo
            if info:
                return info['name'] if forPgn else "%s (%d)" % (info['name'], info['rating'])
            if forPgn:
                return "Host" if color == 'w' else "Guest"
            return "You" if color == myColor() else "Opponent"
        return "White" if color == 'w' else "Black"

    # which controls can be clicked right now
    def controlStates():
        inProgress = not gameOver
        online = currentModeIndex == 2
        return {
            'hint': inProgress and humanTurn and not online and hintState is None and hints.remaining() > 0,
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

    def buildPgnText():  # returns (PGN text, result)
        outcome = getOutcome(gs, positionHistory, gameResult)
        result = outcome[1] if outcome else '*'
        headers = [("Event", "Casual game"), ("Site", "Chess-Playing-AI"), ("Date", time.strftime("%Y.%m.%d")),
                   ("Round", "-"), ("White", playerName('w', True)), ("Black", playerName('b', True)),
                   ("Result", result)]
        if timeControl:
            headers.append(("TimeControl", "%d+%d" % timeControl))
        return pgn.buildPgn(gs.moveLog, headers, result), result

    def savePgnFile():
        text, _ = buildPgnText()
        showStatus(pgn.savePgn(text, time.strftime("chess-%Y%m%d-%H%M%S.pgn")))

    def loadPgnText(text):
        nonlocal moveMade, moveUndone, clocks, clockHistory, gameResult, gameLoaded
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
        gameLoaded = True

    # --- account

    def startRequest(coroutine, onDone=None, onError=None, inWindow=True):
        nonlocal accountMessage
        accountRequests.append((asyncio.ensure_future(coroutine), onDone, onError, inWindow))
        if inWindow:
            accountMessage = "Please wait..."

    def accountBusy():
        return any(entry[3] for entry in accountRequests)

    def openAccountView(view):
        nonlocal accountView, accountMessage, accountFocus, accountList
        accountView = view
        accountMessage = ""
        accountList = []
        if view in ('signin', 'register'):
            accountFocus = 'username' if view == 'register' else 'login'
            if view == 'signin' and not accountFields['login']:
                accountFields['login'] = accountFields['email']  # e.g. right after registering
        elif view == 'profile':
            startRequest(account.loadStats())
        elif view == 'games':
            startRequest(account.listGames(), onDone=showAccountList)
        elif view == 'leaderboard':
            startRequest(account.leaderboard(), onDone=showAccountList)

    def showAccountList(rows):
        nonlocal accountList
        accountList = rows

    def submitAccountForm():
        password = accountFields['password']
        if accountView == 'signin':
            startRequest(account.signIn(accountFields['login'].strip(), password), onDone=lambda _: signedIn())
        else:
            startRequest(account.register(accountFields['email'].strip(), password, accountFields['username'].strip()),
                         onDone=registered)

    def signedIn():
        accountFields['password'] = ""
        openAccountView('profile')
        showStatus("Signed in as " + account.username)

    def registered(isSignedIn):
        nonlocal accountMessage
        accountFields['password'] = ""
        if isSignedIn:
            openAccountView('profile')
            showStatus("Welcome, " + account.username)
        else:
            openAccountView('signin')
            accountMessage = "Check your email to confirm the account, then sign in"

    def openSavedGame(row):
        nonlocal accountMessage, accountView
        if currentModeIndex == 2:
            accountMessage = "Leave online play to open a saved game"
            return

        def opened(text):
            nonlocal accountView
            accountView = None
            loadPgnText(text)
        startRequest(account.loadGame(row['id']), onDone=opened)

    def handleAccountClick(location):
        nonlocal accountView, accountFocus
        rects = accountLayout(accountView, len(accountList))
        clicked = None
        for name, rect in rects.items():
            if name != 'box' and rect.collidepoint(location):
                clicked = name
        if clicked is None or (accountBusy() and clicked != 'close'):
            return
        if clicked.startswith('field:'):
            accountFocus = clicked[len('field:'):]
        elif clicked.startswith('row:'):
            if accountView == 'games':
                openSavedGame(accountList[int(clicked[len('row:'):])])
        elif clicked == 'submit':
            submitAccountForm()
        elif clicked == 'switch':
            openAccountView('register' if accountView == 'signin' else 'signin')
        elif clicked in ('games', 'leaderboard'):
            openAccountView(clicked)
        elif clicked == 'back':
            openAccountView('profile')
        elif clicked == 'signOut':
            account.signOut()
            openAccountView('signin')
            showStatus("Signed out")
        elif clicked == 'close':
            accountView = None

    def handleAccountKey(e):
        nonlocal accountView, accountFocus
        if e.key == p.K_ESCAPE:
            accountView = None
            return
        if accountView not in ('signin', 'register') or accountBusy():
            return
        fields = accountFieldNames(accountView)
        if e.key == p.K_TAB:
            accountFocus = fields[(fields.index(accountFocus) + 1) % len(fields)]
        elif e.key in (p.K_RETURN, p.K_KP_ENTER):
            submitAccountForm()
        elif e.key == p.K_BACKSPACE:
            accountFields[accountFocus] = accountFields[accountFocus][:-1]
        elif e.unicode and e.unicode.isprintable() and len(accountFields[accountFocus]) < 100:
            accountFields[accountFocus] += e.unicode

    # a finished game goes to the account; an online game's result is also reported for ratings
    def saveFinishedGame():
        nonlocal ratingReported
        text, result = buildPgnText()
        mode = ['ai', 'local', 'online'][currentModeIndex]
        color = None if mode == 'local' else myColor()
        game = {'mode': mode, 'result': result, 'pgn': text, 'color': color,
                'ai_level': chessAi.LEVEL if mode == 'ai' else None,
                'opponent': playerName('b' if color == 'w' else 'w', True) if color else ""}
        if savedGameId is not None:
            game['id'] = savedGameId

        def saved(gameId):
            nonlocal savedGameId
            savedGameId = gameId
            showStatus("Game saved to your account")
        startRequest(account.saveGame(game), onDone=saved, inWindow=False,
                     onError=lambda message: showStatus("Couldn't save the game: " + message))

        if mode == 'online' and opponentInfo and result != '*' and not ratingReported:
            ratingReported = True
            mine, theirs = account.profile['id'], opponentInfo['uid']
            white, black = (mine, theirs) if color == 'w' else (theirs, mine)
            ratingBefore = account.profile['rating']

            def reported(outcome):
                rated, pending, reason = outcome
                if rated:
                    rating = account.profile['rating']
                    showStatus("Your rating: %d (%+d)" % (rating, rating - ratingBefore), 5000)
                elif pending:
                    showStatus("Result sent; ratings change when your opponent confirms it", 5000)
                elif reason == 'daily limit':
                    showStatus("Not rated: you already played 3 rated games against this player today", 5000)
            startRequest(account.reportOnline(white, black, onlineGameId, " ".join(m.getCode() for m in gs.moveLog),
                                              result),
                         onDone=reported, inWindow=False,
                         onError=lambda message: showStatus("Couldn't report the result: " + message))

    while running:

        if multiplayerMode and networkConnected:
            now = p.time.get_ticks()
            opponentRole = 'client' if multiplayerRole == 'host' else 'host'
            messages = [msg for msg in net.get_messages() if msg.get('sender') != myPlayerId]
            for msg in messages:
                print(f"Main: Received message type='{msg.get('type')}' from {msg.get('role')} sender={msg.get('sender', '???')}")
                if msg.get('role') == opponentRole and msg.get('_time') is not None:
                    opponentSeen = max(opponentSeen or 0, msg['_time'])  # server time of their latest message
                player = msg.get('player')
                if msg.get('role') == opponentRole and isinstance(player, dict) and player.get('uid'):
                    try:
                        opponentInfo = {'uid': str(player['uid'])[:64], 'name': str(player.get('name') or "?")[:20],
                                        'rating': int(player.get('rating') or 0)}
                    except (TypeError, ValueError):
                        pass

            # game states: a replay after joining can deliver many, so only the newest one is used
            newest = None
            for msg in messages:
                if msg.get('type') == 'state' and isinstance(msg.get('game'), int) and isinstance(msg.get('version'), int):
                    if newest is None or (msg['game'], msg['version']) > (newest['game'], newest['version']):
                        newest = msg
            if newest is not None:
                theirs = (newest['game'], newest['version'])
                mine = (onlineGame, onlineVersion)
                sameGame = (str(newest.get('gid') or "")[:32] == onlineGameId
                            and str(newest.get('moves') or "") == " ".join(move.getCode() for move in gs.moveLog)
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
            # a player who has sent nothing for a while (say, thinking about a move) says they're still here,
            # so the opponent can tell them apart from a player who left
            if p.time.get_ticks() - lastMessageSent > PRESENCE_MS:
                sendOnline({'type': 'ping'})

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
                if accountView:  # the account window takes every click while it's open
                    handleAccountClick(location)
                    continue
                if helpPage is not None:  # and so does the How to play window
                    helpPage = helpClick(helpPage, location)
                    continue
                if settingsOpen:  # and the Settings window
                    settingsOpen = settingsClick(location)
                    continue
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
                        elif kind == 'resign' and accepted and not gameOver:
                            gameResult = resignationResult(myColor())
                            if multiplayerMode and networkConnected:
                                publishChange('resign')
                        elif kind == 'restart' and accepted:
                            restartGame()
                        continue

                clicked = None
                for name, rect in layout.items():
                    if rect.collidepoint(location):
                        clicked = name
                inputBoxActive = clicked == 'room'
                if clicked == 'hint' and hints.remaining() == 0:
                    showStatus("You've used today's %d hints. More tomorrow!" % hints.HINTS_PER_DAY)
                    continue
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
                    askToRestart()
                elif clicked == 'hint':
                    hintState = 'requested'
                    showStatus("Looking for a good move...", 10000)
                elif clicked == 'resign':
                    # one click would lose the game, so it asks first
                    pendingPrompt = {'kind': 'resign', 'text': "Resign this game?", 'yes': "Resign", 'no': "Cancel",
                                     'confirm': True}
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
                elif clicked == 'account':
                    openAccountView('profile' if account.signedIn else 'signin')
                elif clicked == 'help':
                    helpPage = 0
                elif clicked == 'settings':
                    settingsOpen = True
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
                        if resultCardHidden:
                            resultCardHidden = False  # another click brings the result card back
                            continue
                        # the result card's buttons start the next game; a click beside them hides the card
                        _, _, cardRects = resultCardLayout(outcome[0], resultButtons())
                        if cardRects['new'].collidepoint(location):
                            if multiplayerMode and networkConnected:
                                startOnlineGame()
                            else:
                                resetGame()
                        elif 'switch' in cardRects and cardRects['switch'].collidepoint(location):
                            sideIndex = 1 if playerWhiteHuman else 0  # "Play as" changes to the other color
                            resetGame()
                        else:
                            resultCardHidden = True
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
                                    choice = await pawnPromotionPopup(screen, candidate.pieceMoved[0], candidate.endRow,
                                                                      candidate.endCol, flip_board)
                                    if choice is None:  # cancelled: the player picks another move
                                        squareSelected = ()
                                        playerClicks = []
                                        break
                                    candidate.promotionChoice = choice
                                playMove(candidate)
                                if multiplayerMode and networkConnected:
                                    print(f"Main: Sending move {candidate.getCode()}")
                                    publishChange('move')
                                moveMade = True
                                animate = True
                                squareSelected = ()
                                playerClicks = []
                                break
                        if not moveMade:  # the second click starts a new selection (none after a cancelled promotion)
                            playerClicks = [squareSelected] if squareSelected else []

            # Key Handler
            elif e.type == p.KEYDOWN:
                if accountView:
                    handleAccountKey(e)
                    continue
                if helpPage is not None:
                    helpPage = helpKey(helpPage, e.key)
                    continue
                if settingsOpen:
                    settingsOpen = e.key != p.K_ESCAPE
                    continue
                if openDropdown and e.key == p.K_ESCAPE:
                    openDropdown = None
                    continue
                if inputBoxActive:
                    if e.key == p.K_BACKSPACE:
                        roomCode = roomCode[:-1]
                    elif e.key == p.K_RETURN:
                        inputBoxActive = False
                    # room codes become part of the ntfy topic name, which allows only these characters
                    elif e.unicode and e.unicode in ROOM_CODE_CHARACTERS and len(roomCode) < 12:
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

                if e.key in (p.K_h, p.K_F1):  # How to play
                    helpPage = 0
                    continue
                if e.key == p.K_z:  # undo when z is pressed
                    if multiplayerMode and networkConnected:
                        sendOnline({'type': 'undo_request'})
                        showStatus("Undo request sent")
                        continue
                    playerUndo()
                if e.key == p.K_r:  # reset board when 'r' is pressed
                    if multiplayerMode and networkConnected:
                        # a local reset would desync the online game (and the host's would win the sync)
                        showStatus("Click the board after the game for a new one, or Restart to leave the room")
                        continue
                    askToRestart()

        # clocks: charge the side to move and check for a flag fall
        chargeClock()
        if clockRunning():
            side = 'w' if gs.whiteToMove else 'b'
            if clocks[side] <= 0:
                clocks[side] = 0
                gameResult = timeoutResult(gs, side)
                pendingPrompt = None
                if multiplayerMode and networkConnected:
                    # both sides usually see the flag fall and send the same result; if the flagged
                    # player had moved in time, their newer move state replaces this one
                    publishChange('timeout')

        # a PGN file the player picked (arrives later in the browser)
        if currentModeIndex != 2:
            loadedText = pgn.takeLoadedPgn()
            if loadedText:
                loadPgnText(loadedText)

        # AI move finder: starts the search in the background, and plays its move once it is done
        aiTurn = (currentModeIndex == 0 and not gameOver and gameResult is None and not humanTurn and not moveUndone
                  and validMoves)
        if aiSearch is not None and (not aiTurn or aiSearch['gs'] is not gs or aiSearch['ply'] != len(gs.moveLog)):
            stopAI()  # the position it was searching is gone
        if aiTurn and aiSearch is None:
            board = copyGame(gs)
            aiSearch = {'task': asyncio.ensure_future(findBestMove(board, board.getValidMoves(),
                                                                   history=list(positionHistory))),
                        'gs': gs, 'ply': len(gs.moveLog), 'started': p.time.get_ticks()}
        elif aiTurn and aiSearch['task'].done() and p.time.get_ticks() - aiSearch['started'] >= AI_MIN_THINK_MS:
            task = aiSearch['task']
            aiSearch = None
            try:
                found = task.result()
            except Exception as e:
                print("Main: AI search failed:", e)
                found = None
            AIMove = gs.findMoveByCode(found.getCode(), validMoves) if found is not None else None
            if AIMove is None:
                AIMove = findRandomMoves(validMoves)
            playMove(AIMove)  # promotes to a queen, which is what the AI always picks
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
                hints.use()
                showStatus("Hint: %s (%d left today)" % (gs.getSan(suggestion, validMoves), hints.remaining()), 4000)

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
        if gameOver and pendingPrompt and pendingPrompt['kind'] in ('draw', 'localDraw', 'resign'):
            pendingPrompt = None  # offers and resigning end with the game; an undo or leaving the room still can

        # account requests that finished since the last frame
        for entry in [entry for entry in accountRequests if entry[0].done()]:
            accountRequests.remove(entry)
            task, onDone, onError, inWindow = entry
            try:
                result = task.result()
            except Exception as e:
                message = str(e) if isinstance(e, AccountError) else "Something went wrong: %s" % e
                if onError:
                    onError(message)
                elif inWindow:
                    accountMessage = message
                else:
                    showStatus(message)
                continue
            if inWindow:
                accountMessage = ""
            if onDone:
                onDone(result)

        # a game finished while signed in is saved to the account; an online game only when we saw it in
        # progress, so joining a room whose game already ended (or rejoining it) doesn't save it again
        if multiplayerMode and networkConnected and not gameOver:
            liveGameId = onlineGameId
        if (gameOver and not gameSaved and not gameLoaded and account.signedIn and gs.moveLog
                and (currentModeIndex != 2 or liveGameId == onlineGameId)):
            gameSaved = True
            saveFinishedGame()

        if not gameOver and reviewPly is not None:
            clearReview()  # the game went on (e.g. an undo from the opponent)
        # arrows: the hint, and after the game the better move instead of an analysed mistake
        marks = moveMarks(analysis, gs.moveLog) if analysis else {}
        arrows = []
        if hintMove is not None and not gameOver:  # a hint is for the game in progress (it may end by resigning)
            arrows.append(((hintMove.startRow, hintMove.startCol), (hintMove.endRow, hintMove.endCol)))
        if gameOver and shownPly() - 1 in marks and analysis['best'][shownPly() - 1]:
            arrows.append(codeSquares(analysis['best'][shownPly() - 1]))
        # the board shows the reviewed position while stepping through a finished game
        shownGs = reviewGs if reviewGs is not None else gs
        if reviewGs is not None:
            drawGameState(screen, reviewGs, [], (), flip_board, arrows)
        else:
            drawGameState(screen, gs, validMoves, squareSelected, flip_board, arrows)

        # side panel
        layout = panelLayout(currentModeIndex, networkConnected, canRejoin, gameOver)
        stripY = min(rect.y for rect in layout.values()) - ROW_GAP - STRIP_HEIGHT
        p.draw.rect(screen, p.Color(LIGHT_SQUARE_COLOR), p.Rect(PANEL_X, 0, MOVE_LOG_PANEL_WIDTH, MOVE_LOG_PANEL_HEIGHT))
        # below the moves: a slot for status messages, and after the game the review info under it
        infoRect = p.Rect(PANEL_X + 10, stripY - 60, MOVE_LOG_PANEL_WIDTH - 20, 54)
        statusRect = p.Rect(PANEL_X + 10, (infoRect.y if gameOver else stripY) - STATUS_HEIGHT - 4,
                            MOVE_LOG_PANEL_WIDTH - 20, STATUS_HEIGHT)
        if gameOver:
            # the shown position, its evaluation and the analysis
            moveLogScroll, moveRects = drawMoveLog(screen, gs, moveLogScroll, STRIP_HEIGHT, statusRect.y - 2,
                                                   shownPly() - 1, marks, reviewScroll)
            drawReviewInfo(screen, infoRect, gs.moveLog, shownPly(), analysis, marks, shownGs.checkmate, outcome[0])
        else:
            moveLogScroll, moveRects = drawMoveLog(screen, gs, moveLogScroll, STRIP_HEIGHT, statusRect.y - 2)
        reviewScroll = False
        taken = capturedPieces(shownGs)
        balance = materialBalance(shownGs.board)
        sideToMove = 'w' if shownGs.whiteToMove else 'b'
        shownClocks = clockHistory[reviewPly] if reviewPly is not None and reviewPly < len(clockHistory) else clocks
        notes = {}  # a note after a player's name
        if aiSearch is not None:
            notes['w' if gs.whiteToMove else 'b'] = "thinking" + "." * (1 + p.time.get_ticks() // 400 % 3)
        if multiplayerMode and networkConnected:
            notes['b' if myColor() == 'w' else 'w'] = presenceStatus(multiplayerRole, opponentSeen, net.server_time,
                                                                     net.last_status)[2]
        for color, y in ((('w' if flip_board else 'b'), 0), (('b' if flip_board else 'w'), stripY)):
            drawPlayerStrip(screen, y, color, playerName(color), taken[color],
                            balance if color == 'w' else -balance,
                            shownClocks[color] if timeControl else None,
                            clockRunning() and sideToMove == color, notes.get(color))

        mouse_pos = p.mouse.get_pos()
        states = controlStates()
        labels = {
            'mode': "Mode: " + MODE_OPTIONS[currentModeIndex],
            'level': "AI: " + LEVEL_OPTIONS[chessAi.LEVEL],
            'side': "Play as: " + SIDE_OPTIONS[sideIndex],
            'clock': "Clock: " + CLOCK_OPTIONS[clockIndex][0],
            'hint': "Hint (%d left)" % hints.remaining(),
            'host': "Host (White)",
            'join': "Join (Black)",
            'save': "Save PGN",
            'help': "How to play",
            'settings': "",  # drawn as a gear
            'load': "Load PGN",
            'resign': "Resign",
            'draw': "Offer Draw",
            'undo': "Undo",
            'restart': "Restart",
            'account': account.username or "Sign in",
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
                # whether the opponent is there (the connection details go to the console)
                presenceText, presenceColor = presenceStatus(multiplayerRole, opponentSeen, net.server_time,
                                                             net.last_status)[:2]
                presenceObj = get_fitting_text(presenceText, rect.width, 15, presenceColor, False)
                screen.blit(presenceObj, (rect.centerx - presenceObj.get_width() / 2, rect.y + 24))
            else:
                arrow = None
                if name in ('mode', 'level', 'side', 'clock'):
                    arrow = 'up' if openDropdown == name else 'down'
                drawButton(screen, rect, labels[name], states.get(name, True), mouse_pos, arrow)
                if name in ('first', 'prev', 'next', 'last'):
                    drawNavIcon(screen, rect, name)
                elif name == 'settings':
                    drawGearIcon(screen, rect)

        if gameOver and reviewPly is None and not resultCardHidden:
            drawEndGameText(screen, outcome[0], resultButtons(), mouse_pos)

        # overlays: open dropdown options and the Accept / Decline prompt
        if openDropdown in layout:
            options = dropdownLabels(openDropdown)
            current = {'mode': currentModeIndex, 'level': chessAi.LEVEL, 'side': sideIndex,
                       'clock': clockIndex}[openDropdown]
            for i, optRect in enumerate(dropdownOptionRects(layout[openDropdown], len(options))):
                drawButton(screen, optRect, options[i], True, mouse_pos,
                           color=SELECTED_OPTION_COLOR if i == current else None)
                if i == current:
                    drawCheckMark(screen, optRect)
        if pendingPrompt:
            panel_rect, acceptBtn, denyBtn = promptRects()
            p.draw.rect(screen, p.Color(STRIP_COLOR), panel_rect)
            p.draw.rect(screen, p.Color(DARK_SQUARE_COLOR), panel_rect, 2)
            textObj = get_fitting_text(pendingPrompt['text'], panel_rect.width - 20, 20, "black")
            screen.blit(textObj, (panel_rect.centerx - textObj.get_width() / 2, panel_rect.y + 12))
            # a confirmation shows its action in red (it can't be taken back); an offer's Accept is green;
            # the way out is a neutral gray
            confirm = pendingPrompt.get('confirm', False)
            drawButton(screen, acceptBtn, pendingPrompt.get('yes', "Accept"), True, mouse_pos,
                       color=CONFIRM_COLOR if confirm else DARK_SQUARE_COLOR)
            drawButton(screen, denyBtn, pendingPrompt.get('no', "Decline"), True, mouse_pos, color=NEUTRAL_COLOR)
        if accountView:
            drawAccountWindow(screen, accountView, accountFields, accountFocus, accountMessage, accountBusy(),
                              account, accountList, mouse_pos)
        if helpPage is not None:
            drawHelpWindow(screen, helpPage, mouse_pos)
        if settingsOpen:
            drawSettingsWindow(screen, mouse_pos)
        if statusText and p.time.get_ticks() < statusUntil:
            drawStatus(screen, statusRect, statusText)

        clock.tick(MAX_FPS)
        await asyncio.sleep(0) # Essential for WASM performance/UI responsiveness
        p.display.flip()
        await asyncio.sleep(0)


# color: the button's own color instead of the panel green; it lightens under the mouse
def drawButton(screen, rect, text, enabled=True, mouse_pos=(-1, -1), arrow=None, color=None):
    if not enabled:
        color = p.Color(DISABLED_COLOR)
    elif rect.collidepoint(mouse_pos):
        color = p.Color(MOVE_HIGHLIGHT_COLOR) if color is None else p.Color(*(min(255, c + 30) for c in color))
    else:
        color = p.Color(color or DARK_SQUARE_COLOR)
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


# name, captured pieces, material lead and clock of one player, and an optional note after the name
def drawPlayerStrip(screen, y, color, name, captured, advantage, clockMs, clockActive, note=None):
    rect = p.Rect(PANEL_X, y, MOVE_LOG_PANEL_WIDTH, STRIP_HEIGHT)
    p.draw.rect(screen, p.Color(STRIP_COLOR), rect)
    p.draw.line(screen, p.Color(DARK_SQUARE_COLOR), (rect.x, rect.bottom - 1), (rect.right, rect.bottom - 1))

    # side marker and name
    p.draw.circle(screen, p.Color('white' if color == 'w' else 'black'), (rect.x + 18, rect.y + 15), 7)
    p.draw.circle(screen, p.Color('black'), (rect.x + 18, rect.y + 15), 7, 1)
    nameObj = get_text_surface(name, 18, "black", True)
    screen.blit(nameObj, (rect.x + 32, rect.y + 15 - nameObj.get_height() / 2))
    if note:  # e.g. "thinking..." while the computer searches
        noteObj = get_text_surface(note, 16, "dimgray", False)
        screen.blit(noteObj, (rect.x + 40 + nameObj.get_width(), rect.y + 15 - noteObj.get_height() / 2))

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


# a short message in its own slot of the side panel (rect), so it never covers the board; up to two lines
def drawStatus(screen, rect, text):
    font = get_font(17, False)
    lines = wrapText(text, font, rect.width - 20)
    if len(lines) > 2:
        font = get_font(14, False)
        lines = wrapText(text, font, rect.width - 20)[:2]
    lineHeight = font.get_linesize()
    s = p.Surface(rect.size, p.SRCALPHA)
    p.draw.rect(s, (40, 40, 40, 225), s.get_rect(), border_radius=8)
    screen.blit(s, rect.topleft)
    y = rect.centery - lineHeight * len(lines) / 2
    for line in lines:
        textObj = font.render(line, True, p.Color("white"))
        screen.blit(textObj, (rect.centerx - textObj.get_width() / 2, y))
        y += lineHeight


# --- account window, drawn over the board

ACCOUNT_BOX = p.Rect(124, 84, 520, 600)
ACCOUNT_LIST_ROWS = 14
ACCOUNT_TITLES = {'signin': "Sign in", 'register': "Create an account", 'games': "My games",
                  'leaderboard': "Leaderboard"}
ACCOUNT_BUTTONS = {'close': "Close", 'back': "Back", 'games': "My games", 'leaderboard': "Leaderboard",
                   'signOut': "Sign out"}


def accountFieldNames(view):
    return ['username', 'email', 'password'] if view == 'register' else ['login', 'password']


# rects of the account window's parts, by name; count is the number of list rows (saved games, leaderboard)
def accountLayout(view, count=0):
    box = ACCOUNT_BOX
    x, width = box.x + 40, box.width - 80
    rects = {'box': box}
    y = box.y + 80
    if view in ('signin', 'register'):
        for name in accountFieldNames(view):
            rects['field:' + name] = p.Rect(x, y + 24, width, 40)
            y += 78
        y += 40  # room for the error message
        rects['submit'] = p.Rect(x, y, width, ROW_HEIGHT)
        rects['switch'] = p.Rect(x, y + ROW_HEIGHT + ROW_GAP, width, ROW_HEIGHT)
        bottom = [['close']]
    elif view == 'profile':
        bottom = [['games', 'leaderboard'], ['signOut', 'close']]
    else:
        for i in range(min(count, ACCOUNT_LIST_ROWS)):
            rects['row:%d' % i] = p.Rect(x, y + 10 + i * 30, width, 28)
        bottom = [['back', 'close']]
    y = box.bottom - 24 - len(bottom) * ROW_HEIGHT - (len(bottom) - 1) * ROW_GAP
    for row in bottom:
        rowWidth = (width - 10 * (len(row) - 1)) // len(row)
        for i, name in enumerate(row):
            rects[name] = p.Rect(x + i * (rowWidth + 10), y, rowWidth, ROW_HEIGHT)
        y += ROW_HEIGHT + ROW_GAP
    return rects


def drawAccountWindow(screen, view, fields, focus, message, busy, account, rows, mouse_pos):
    shade = p.Surface(screen.get_size())
    shade.set_alpha(150)
    shade.fill(p.Color(0, 0, 0))
    screen.blit(shade, (0, 0))
    rects = accountLayout(view, len(rows))
    box = rects['box']
    p.draw.rect(screen, p.Color(LIGHT_SQUARE_COLOR), box)
    p.draw.rect(screen, p.Color(DARK_SQUARE_COLOR), box, 3)
    x, width = box.x + 40, box.width - 80
    title = ACCOUNT_TITLES.get(view) or account.username or "Account"
    titleObj = get_fitting_text(title, width, 32, "black")
    screen.blit(titleObj, (box.centerx - titleObj.get_width() / 2, box.y + 26))

    if view in ('signin', 'register'):
        labels = {'username': "Username (3-20 letters, digits or _)", 'email': "Email", 'login': "Email or username",
                  'password': "Password (at least 8 characters)" if view == 'register' else "Password"}
        for name in accountFieldNames(view):
            rect = rects['field:' + name]
            screen.blit(get_text_surface(labels[name], 17, "dimgray", False), (rect.x, rect.y - 22))
            p.draw.rect(screen, p.Color('white') if focus == name else p.Color(225, 225, 225), rect)
            p.draw.rect(screen, p.Color(MOVE_HIGHLIGHT_COLOR) if focus == name else p.Color('gray'), rect, 2)
            value = "*" * len(fields[name]) if name == 'password' else fields[name]
            if focus == name and (p.time.get_ticks() // 500) % 2 == 0:
                value += "|"  # blinking cursor
            font = get_font(20, False)
            while value and font.size(value)[0] > rect.width - 16:
                value = value[1:]  # long input scrolls: show its end
            textObj = font.render(value, True, p.Color('black'))
            screen.blit(textObj, (rect.x + 8, rect.centery - textObj.get_height() / 2))
        messageY = rects['submit'].y - 32
        buttons = {'submit': "Sign in" if view == 'signin' else "Create account",
                   'switch': "No account yet? Create one" if view == 'signin' else "Already registered? Sign in"}
    elif view == 'profile':
        profile = account.profile or {}
        lines = []
        if profile:
            rated = profile.get('rated_games', 0)
            lines.append(("Rating %d" % profile.get('rating', 0), True))
            lines.append((countGames(rated) + " rated online" if rated else "Play online games to get rated", False))
            lines.append(("", False))
            stats = account.stats or {}
            levelKeys = sorted(key for key in stats if key.startswith('ai'))
            if levelKeys:
                lines.append(("Against the computer", True))
                for key in levelKeys:
                    level = int(key[2:])
                    name = LEVEL_OPTIONS[level] if 0 <= level < len(LEVEL_OPTIONS) else key
                    lines.append(("%s: %s" % (name, formatRecord(stats[key])), False))
            if 'online' in stats:
                lines.append(("Online: " + formatRecord(stats['online']), True))
            if not stats:
                lines.append(("Games you finish while signed in are saved here", False))
        y = box.y + 84
        for text, bold in lines:
            if text:
                screen.blit(get_fitting_text(text, width, 20, "black" if bold else "dimgray", bold), (x, y))
            y += 28
        messageY = rects['games'].y - 40
        buttons = {}
    else:
        for i, row in enumerate(rows[:ACCOUNT_LIST_ROWS]):
            rect = rects['row:%d' % i]
            if view == 'games':
                if rect.collidepoint(mouse_pos):
                    p.draw.rect(screen, p.Color(LAST_MOVE_COLOR), rect)
                left = "%s   %s" % (str(row.get('played_at', ''))[:10], gameRowResult(row))
                right = row.get('opponent') or "Local game"
            else:
                left = "%d. %s" % (i + 1, row['username'])
                right = "%d  (%s)" % (row["rating"], countGames(row["rated_games"]))
            screen.blit(get_fitting_text(left, width // 2, 18, "black", False), (rect.x + 6, rect.y + 3))
            rightObj = get_fitting_text(right, width // 2 - 10, 18, "dimgray", False)
            screen.blit(rightObj, (rect.right - 6 - rightObj.get_width(), rect.y + 3))
        if not rows and not busy:
            empty = "No saved games yet" if view == 'games' else "Nobody is rated yet"
            screen.blit(get_text_surface(empty, 20, "dimgray", False), (x, box.y + 90))
        messageY = rects['back'].y - 40
        buttons = {}

    if message:
        color = "dimgray" if busy else "firebrick"
        screen.blit(get_fitting_text(message, width, 18, color, True), (x, messageY))
    buttons.update(ACCOUNT_BUTTONS)
    for name, rect in rects.items():
        if name in buttons:
            drawButton(screen, rect, buttons[name], not busy or name == 'close', mouse_pos)


def countGames(count):
    return "%d game%s" % (count, "" if count == 1 else "s")


def formatRecord(record):
    return "%d won, %d lost, %d drawn" % (record['won'], record['lost'], record['drawn'])


# a saved game's result from the player's side
def gameRowResult(row):
    result, color = row.get('result'), row.get('color')
    if result == '1/2-1/2':
        return "Draw"
    if result not in ('1-0', '0-1'):
        return "Unfinished"
    if color not in ('w', 'b'):
        return "White won" if result == '1-0' else "Black won"
    return "Won" if (result == '1-0') == (color == 'w') else "Lost"


# --- How to play window, drawn over the board like the account window

# (title, items); an item is (piece icon or None, heading, text)
HELP_PAGES = [
    ("The goal", [
        (None, "Checkmate wins",
         "Attack the opponent's king so that it has no way to escape. You may never leave your own king "
         "under attack."),
        (None, "Taking turns",
         "White moves first, then the players take turns, one move each. Click one of your pieces to see "
         "where it can go (dots, or rings around pieces it can take), then click one of those squares."),
        (None, "Capturing",
         "Move onto an opponent's piece to take it. The pieces each side has taken, and who is ahead in "
         "material, are shown next to the players' names."),
        (None, "Draws",
         "No legal move while not in check (stalemate), the same position three times, 50 moves each without "
         "a capture or pawn move, too few pieces left to checkmate, or a draw both players agree to."),
    ]),
    ("How the pieces move", [
        ('wK', "King", "One square in any direction."),
        ('wQ', "Queen", "Any number of squares in a straight line: along a row, a column or a diagonal."),
        ('wR', "Rook", "Any number of squares along a row or a column."),
        ('wB', "Bishop", "Any number of squares along a diagonal."),
        ('wN', "Knight", "In an L: two squares one way, then one square to the side. It jumps over other pieces."),
        ('wp', "Pawn",
         "One square forward, or two from its starting square. It captures one square diagonally forward."),
    ]),
    ("Special moves", [
        (None, "Check",
         "When your king is attacked, move it, block the attack or take the attacker. The king's square turns "
         "red, and only moves that get out of check are allowed."),
        (None, "Castling",
         "Click the king, then the square two steps toward a rook: the rook jumps to the king's other side. "
         "Neither piece may have moved, the squares between must be empty, and the king can't be in check or "
         "cross an attacked square."),
        (None, "Promotion",
         "A pawn that reaches the far side becomes a queen, rook, bishop or knight. Pick one from the pieces "
         "shown over the square, or click elsewhere to take the move back."),
        (None, "En passant",
         "A pawn that moves two squares can be taken by an enemy pawn beside it, as if it had moved only one, "
         "but only on the very next move."),
    ]),
    ("Game modes", [
        (None, "Local vs AI",
         "Play the computer. Choose its level, from Easy to Impossible, and whether you play White, Black or "
         "a random side."),
        (None, "Local 2-Player", "Two players take turns on the same screen."),
        (None, "Online Multiplayer",
         "Click Host to create a room and send its code to a friend, who types it in the room box and clicks "
         "Join. Rejoin takes you back to your last room."),
        (None, "Clock",
         "Pick a time control before the game. 3+2 means three minutes each, plus two seconds for every "
         "move. Running out of time loses."),
        (None, "Account", "Sign in to keep your finished games, see your record and get an online rating."),
        (None, "Settings (gear button)", "Choose the board colors and the style of the pieces."),
    ]),
    ("Buttons and keys", [
        (None, "Hint", "Shows a good move on the board, up to 5 times a day."),
        (None, "Undo (Z) and Restart (R)",
         "Undo takes back your last move (and the computer's reply). Online, your opponent must accept it, "
         "and Restart leaves the room."),
        (None, "Resign and Offer Draw",
         "Give up the game, or offer a draw. The computer only accepts a draw when it is losing."),
        (None, "Save PGN and Load PGN", "Save the game to a file, or open a saved game to replay it."),
        (None, "After the game",
         "Step through the moves with the arrow keys, or click Analyze game to mark mistakes with ?!, ? and "
         "?? (an arrow shows the better move). Start the next game from the result card."),
        (None, "How to play (H)", "Opens this window. Esc closes it."),
    ]),
]


def helpLayout():
    box = ACCOUNT_BOX
    x, width = box.x + 40, box.width - 80
    buttonWidth = (width - 20) // 3
    y = box.bottom - 24 - ROW_HEIGHT
    return {'box': box,
            'prev': p.Rect(x, y, buttonWidth, ROW_HEIGHT),
            'close': p.Rect(x + buttonWidth + 10, y, buttonWidth, ROW_HEIGHT),
            'next': p.Rect(x + 2 * (buttonWidth + 10), y, buttonWidth, ROW_HEIGHT)}


# returns the page to show after the click, or None to close the window
def helpClick(page, location):
    rects = helpLayout()
    if rects['close'].collidepoint(location):
        return None
    if rects['prev'].collidepoint(location):
        return max(page - 1, 0)
    if rects['next'].collidepoint(location):
        return min(page + 1, len(HELP_PAGES) - 1)
    return page


def helpKey(page, key):
    if key in (p.K_ESCAPE, p.K_h, p.K_F1):
        return None
    if key in (p.K_LEFT, p.K_UP):
        return max(page - 1, 0)
    if key in (p.K_RIGHT, p.K_DOWN):
        return min(page + 1, len(HELP_PAGES) - 1)
    return page


# splits text into lines that fit in maxWidth
def wrapText(text, font, maxWidth):
    lines = []
    line = ""
    for word in text.split():
        candidate = (line + " " + word).strip()
        if line and font.size(candidate)[0] > maxWidth:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    return lines


def drawHelpWindow(screen, page, mouse_pos):
    shade = p.Surface(screen.get_size())
    shade.set_alpha(150)
    shade.fill(p.Color(0, 0, 0))
    screen.blit(shade, (0, 0))
    rects = helpLayout()
    box = rects['box']
    p.draw.rect(screen, p.Color(LIGHT_SQUARE_COLOR), box)
    p.draw.rect(screen, p.Color(DARK_SQUARE_COLOR), box, 3)
    x, width = box.x + 40, box.width - 80

    title, items = HELP_PAGES[page]
    titleObj = get_fitting_text(title, width - 60, 32, "black")
    screen.blit(titleObj, (box.centerx - titleObj.get_width() / 2, box.y + 26))
    pageObj = get_text_surface("%d / %d" % (page + 1, len(HELP_PAGES)), 16, "dimgray", False)
    screen.blit(pageObj, (box.right - 16 - pageObj.get_width(), box.y + 14))

    textFont = get_font(17, False)
    y = box.y + 82
    for icon, heading, text in items:
        top = y
        textX = x
        if icon:
            screen.blit(HELP_IMAGES[icon], (x, y))
            textX = x + HELP_ICON_SIZE + 12
        screen.blit(get_text_surface(heading, 19, "black", True), (textX, y))
        y += 24
        for line in wrapText(text, textFont, x + width - textX):
            screen.blit(textFont.render(line, True, p.Color(60, 60, 60)), (textX, y))
            y += 20
        y = max(y, top + (HELP_ICON_SIZE if icon else 0)) + 12

    buttons = {'prev': ("Back", page > 0), 'close': ("Close", True), 'next': ("Next", page < len(HELP_PAGES) - 1)}
    for name, (label, enabled) in buttons.items():
        drawButton(screen, rects[name], label, enabled, mouse_pos)


# arrows: (start square, end square) pairs drawn over the pieces
def drawGameState(screen, gs, validMoves, squareSelected, flip=False, arrows=()):
    drawSquare(screen, flip)  # draw square on board
    # last move played, and the hint if one is showing
    if gs.moveLog:
        lastMove = gs.moveLog[-1]
        tintSquare(screen, lastMove.startRow, lastMove.startCol, LAST_MOVE_COLOR, 170, flip)
        tintSquare(screen, lastMove.endRow, lastMove.endCol, LAST_MOVE_COLOR, 170, flip)
    highlightSquares(screen, gs, squareSelected, flip)

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
    drawMoveMarkers(screen, gs, validMoves, squareSelected, flip)
    for start, end in arrows:
        drawArrow(screen, start, end, flip)


# ((start row, col), (end row, col)) of a move in coordinate notation, e.g. "g1f3"
def codeSquares(code):
    return ((Move.ranksToRows[code[1]], Move.filesToCols[code[0]]),
            (Move.ranksToRows[code[3]], Move.filesToCols[code[2]]))


# a see-through arrow from the center of one square to another, over the pieces (hints, the analysis's best move)
def drawArrow(screen, start, end, flip=False):
    global ARROW_LAYER
    if ARROW_LAYER is None:
        ARROW_LAYER = p.Surface((BOARD_WIDTH, BOARD_HEIGHT), p.SRCALPHA)
    ARROW_LAYER.fill((0, 0, 0, 0))
    (r1, c1), (r2, c2) = start, end
    if flip:
        r1, c1, r2, c2 = 7 - r1, 7 - c1, 7 - r2, 7 - c2
    x1, y1 = (c1 + 0.5) * SQ_SIZE, (r1 + 0.5) * SQ_SIZE
    x2, y2 = (c2 + 0.5) * SQ_SIZE, (r2 + 0.5) * SQ_SIZE
    length = math.hypot(x2 - x1, y2 - y1)
    ux, uy = (x2 - x1) / length, (y2 - y1) / length  # along the arrow
    nx, ny = -uy, ux  # across it
    shaft, head, headLength = SQ_SIZE * 0.09, SQ_SIZE * 0.24, SQ_SIZE * 0.42  # half widths, and the head's length
    sx, sy = x1 + ux * SQ_SIZE * 0.2, y1 + uy * SQ_SIZE * 0.2  # starts a little off the piece's center
    bx, by = x2 - ux * headLength, y2 - uy * headLength  # where the head begins
    # one polygon, so the shaft and head don't overlap and darken where they meet
    points = [(sx + nx * shaft, sy + ny * shaft), (bx + nx * shaft, by + ny * shaft), (bx + nx * head, by + ny * head),
              (x2, y2), (bx - nx * head, by - ny * head), (bx - nx * shaft, by - ny * shaft),
              (sx - nx * shaft, sy - ny * shaft)]
    p.draw.polygon(ARROW_LAYER, ARROW_COLOR, points)
    screen.blit(ARROW_LAYER, (0, 0))


def tintSquare(screen, row, col, color, alpha, flip=False):
    if flip:
        row, col = 7 - row, 7 - col
    s = p.Surface((SQ_SIZE, SQ_SIZE))
    s.set_alpha(alpha)
    s.fill(p.Color(color))
    screen.blit(s, (col * SQ_SIZE, row * SQ_SIZE))


def drawSquare(screen, flip=False):
    global colors
    colors = [p.Color(BOARD_COLORS[0]), p.Color(BOARD_COLORS[1])]
    for row in range(DIMENSION):
        for col in range(DIMENSION):
            color = colors[((row + col) % 2)]
            p.draw.rect(screen, color, p.Rect(
                col * SQ_SIZE, row * SQ_SIZE, SQ_SIZE, SQ_SIZE))

    # Draw rank and file labels, each in the color of the other kind of square so it stands out
    for row in range(DIMENSION):
        # Draw rank labels (1 to 8 from bottom, or 8 to 1 when flipped)
        rank_num = (row + 1) if flip else (8 - row)
        rank_text = str(rank_num)
        text_color = BOARD_COLORS[1] if row % 2 == 0 else BOARD_COLORS[0]
        text_obj = get_text_surface(rank_text, 15, text_color, True)
        text_loc = p.Rect(0, row * SQ_SIZE, SQ_SIZE, SQ_SIZE).move(4, 2)
        screen.blit(text_obj, text_loc)

    for col in range(DIMENSION):
        # Draw file labels (a-h left to right, or h-a when flipped)
        file_char = chr(ord('h') - col) if flip else chr(ord('a') + col)
        file_text = file_char
        text_color = BOARD_COLORS[1] if (7 + col) % 2 == 0 else BOARD_COLORS[0]
        text_obj = get_text_surface(file_text, 15, text_color, True)
        text_loc = p.Rect(col * SQ_SIZE, 7 * SQ_SIZE, SQ_SIZE, SQ_SIZE).move(SQ_SIZE - text_obj.get_width() - 4, SQ_SIZE - text_obj.get_height() - 2)
        screen.blit(text_obj, text_loc)



# True when squareSelected holds a piece of the side to move (only then are it and its moves highlighted)
def ownPieceSelected(gs, squareSelected):
    if squareSelected == ():
        return False
    row, col = squareSelected
    return gs.board[row][col][0] == ('w' if gs.whiteToMove else 'b')


# tints the selected piece's square; drawn under the pieces
def highlightSquares(screen, gs, squareSelected, flip=False):
    if ownPieceSelected(gs, squareSelected):
        row, col = squareSelected
        tintSquare(screen, row, col, MOVE_HIGHLIGHT_COLOR, 100, flip)


# marks where the selected piece can go: a dot on an empty square, a ring around a piece it can take
# drawn over the pieces, so the rings show around them
def drawMoveMarkers(screen, gs, validMoves, squareSelected, flip=False):
    if not ownPieceSelected(gs, squareSelected):
        return
    if not MOVE_MARKERS:
        for name in ('dot', 'ring'):
            surface = p.Surface((SQ_SIZE, SQ_SIZE), p.SRCALPHA)
            center = (SQ_SIZE // 2, SQ_SIZE // 2)
            if name == 'dot':
                p.draw.circle(surface, MOVE_MARKER_COLOR, center, SQ_SIZE // 6)
            else:
                p.draw.circle(surface, MOVE_MARKER_COLOR, center, SQ_SIZE // 2 - 2, 7)
            MOVE_MARKERS[name] = surface
    row, col = squareSelected
    for move in validMoves:
        if move.startRow == row and move.startCol == col:
            marker = MOVE_MARKERS['ring' if gs.board[move.endRow][move.endCol] != '--' else 'dot']
            end_r = (7 - move.endRow) if flip else move.endRow
            end_c = (7 - move.endCol) if flip else move.endCol
            screen.blit(marker, (end_c * SQ_SIZE, end_r * SQ_SIZE))


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
# result: the game's result text, shown at the final position (the result card may be hidden)
def drawReviewInfo(screen, rect, moveLog, ply, analysis, marks, isCheckmate, result=None):
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
        second = result if result and ply == len(moveLog) else "Step through the moves with the arrow keys"
    screen.blit(get_fitting_text(first, rect.width - 16, 17, "black", True), (rect.x + 8, rect.y + 5))
    screen.blit(get_fitting_text(second, rect.width - 16, 16, "dimgray", False), (rect.x + 8, rect.y + 29))


# --- Settings window: board colors and piece style, drawn over the board like the other windows

PREVIEW_SIZE = 100  # piece previews in the Settings window
PREVIEW_IMAGES = {}  # (folder, piece) -> image, loaded on first use


def settingsLayout():
    box = ACCOUNT_BOX
    x = box.x + 40
    rects = {'box': box}
    for i, name in enumerate(BOARD_THEMES):
        rects['board:' + name] = p.Rect(x + i * 160, box.y + 116, 120, 120)
    for i, name in enumerate(PIECE_SETS):
        rects['pieces:' + name] = p.Rect(x + i * 240, box.y + 330, 2 * PREVIEW_SIZE, PREVIEW_SIZE)
    rects['close'] = p.Rect(x, box.bottom - 24 - ROW_HEIGHT, box.width - 80, ROW_HEIGHT)
    return rects


# applies the choice clicked in the Settings window and remembers it; returns False when the window closes
def settingsClick(location):
    for name, rect in settingsLayout().items():
        if name == 'box' or not rect.collidepoint(location):
            continue
        if name == 'close':
            return False
        kind, choice = name.split(':')
        settings.put(kind, choice)
        if kind == 'board':
            setBoardTheme(choice)
        else:
            loadImages(choice)
    return True


def previewImage(folder, piece):
    if (folder, piece) not in PREVIEW_IMAGES:
        PREVIEW_IMAGES[(folder, piece)] = p.transform.smoothscale(
            p.image.load(folder + "/" + piece + ".png"), (PREVIEW_SIZE, PREVIEW_SIZE))
    return PREVIEW_IMAGES[(folder, piece)]


def drawSettingsWindow(screen, mouse_pos):
    shade = p.Surface(screen.get_size())
    shade.set_alpha(150)
    shade.fill(p.Color(0, 0, 0))
    screen.blit(shade, (0, 0))
    rects = settingsLayout()
    box = rects['box']
    p.draw.rect(screen, p.Color(LIGHT_SQUARE_COLOR), box)
    p.draw.rect(screen, p.Color(DARK_SQUARE_COLOR), box, 3)
    x = box.x + 40
    titleObj = get_text_surface("Settings", 32, "black")
    screen.blit(titleObj, (box.centerx - titleObj.get_width() / 2, box.y + 26))

    chosen = {'board': settings.get('board') if settings.get('board') in BOARD_THEMES else "Green",
              'pieces': settings.get('pieces') if settings.get('pieces') in PIECE_SETS else "Modern"}
    screen.blit(get_text_surface("Board", 20, "black"), (x, box.y + 84))
    screen.blit(get_text_surface("Pieces", 20, "black"), (x, box.y + 298))
    for name, rect in rects.items():
        if ':' not in name:
            continue
        kind, choice = name.split(':')
        if kind == 'board':  # a 2x2 corner of the board in these colors
            half = rect.width // 2
            for r in range(2):
                for c in range(2):
                    p.draw.rect(screen, BOARD_THEMES[choice][(r + c) % 2], (rect.x + c * half, rect.y + r * half, half, half))
        else:  # a white king and a black knight of this style, on the chosen board colors
            folder = PIECE_SETS[choice]
            for i, piece in enumerate(('wK', 'bN')):
                square = p.Rect(rect.x + i * PREVIEW_SIZE, rect.y, PREVIEW_SIZE, PREVIEW_SIZE)
                p.draw.rect(screen, BOARD_COLORS[i], square)
                screen.blit(previewImage(folder, piece), square.topleft)
        if chosen[kind] == choice:
            p.draw.rect(screen, p.Color(MOVE_HIGHLIGHT_COLOR), rect.inflate(10, 10), 4)
        elif rect.collidepoint(mouse_pos):
            p.draw.rect(screen, p.Color("gray"), rect.inflate(10, 10), 2)
        labelObj = get_text_surface(choice, 18, "black" if chosen[kind] == choice else "dimgray", chosen[kind] == choice)
        screen.blit(labelObj, (rect.centerx - labelObj.get_width() / 2, rect.bottom + 10))

    drawButton(screen, rects['close'], "Close", True, mouse_pos)


# a check mark at the left of a button, for the current choice in a dropdown
def drawCheckMark(screen, rect):
    x, y = rect.x + 12, rect.centery
    p.draw.lines(screen, p.Color('white'), False, [(x, y), (x + 6, y + 6), (x + 17, y - 7)], 3)


# a gear: a ring with eight teeth, for the Settings button
def drawGearIcon(screen, rect):
    cx, cy = rect.center
    white = p.Color('white')
    for i in range(8):
        angle = i * math.pi / 4
        p.draw.circle(screen, white, (cx + 9 * math.cos(angle), cy + 9 * math.sin(angle)), 3)
    p.draw.circle(screen, white, (cx, cy), 8, 4)


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
    # how long the animation takes: longer moves a little longer (120 ms for one square, 300 ms across the
    # board); the piece's position comes from the time passed, so the speed doesn't depend on the computer
    duration = ANIMATION_BASE_MS + ANIMATION_MS_PER_SQUARE * max(abs(deltaRow), abs(deltaCol))
    start = p.time.get_ticks()
    done = False
    while not done:
        progress = min(1.0, (p.time.get_ticks() - start) / duration)
        done = progress >= 1.0
        # how much does the row and col move by
        row, col = ((move.startRow + deltaRow*progress, move.startCol +
                    deltaCol*progress))  # how far through the animation
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
        clock.tick(ANIMATION_FPS)
        await asyncio.sleep(0) # Yield for browser interaction


# buttons on the result card, by name; which ones show depends on the mode (see resultButtons in main)
RESULT_BUTTONS = {'new': "New game", 'switch': "Switch sides"}
RESULT_CARD_NOTE = "Click the board to see the final position"


# (title, note, rects) of the result card: rects has the 'card' and one rect per button name
def resultCardLayout(text, buttons):
    titleObj = get_fitting_text(text, BOARD_WIDTH - 120, 42, "white")
    noteObj = get_text_surface(RESULT_CARD_NOTE, 17, (205, 205, 205), False)
    buttonWidth, gap = 170, 16
    rowWidth = len(buttons) * buttonWidth + (len(buttons) - 1) * gap
    width = max(titleObj.get_width(), noteObj.get_width(), rowWidth) + 60
    height = 18 + titleObj.get_height() + 4 + noteObj.get_height() + 16 + ROW_HEIGHT + 22
    card = p.Rect(0, 0, width, height)
    card.center = (BOARD_WIDTH // 2, BOARD_HEIGHT // 2)
    rects = {'card': card}
    x = card.centerx - rowWidth // 2
    for i, name in enumerate(buttons):
        rects[name] = p.Rect(x + i * (buttonWidth + gap), card.bottom - 22 - ROW_HEIGHT, buttonWidth, ROW_HEIGHT)
    return titleObj, noteObj, rects


# what the online status line says: (text, color, note for the opponent's name or None)
# role: ours; opponentSeen: server time of the opponent's latest message (None before any); serverTime: the latest
# server time of any message in the room, ours included (we ping when quiet, so it keeps up); networkStatus: net.last_status
def presenceStatus(role, opponentSeen, serverTime, networkStatus):
    if "HEALTHY" not in networkStatus and "READY" not in networkStatus:
        return "Connecting to the server...", "darkorange", None
    if opponentSeen is None:
        if role == 'host':
            return "Waiting for your opponent: share the room code", "dimgray", "not here yet"
        return "Waiting for the host to answer...", "dimgray", "not here yet"
    silent = serverTime - opponentSeen
    if silent <= OPPONENT_GONE_SECONDS:
        return "Opponent connected", "darkgreen", None
    return "Opponent silent for %d min: they may have left" % max(1, silent // 60), "firebrick", "may have left"


# the result on a dark card in the middle of the board, so it reads over any position, with buttons for what's next
def drawEndGameText(screen, text, buttons, mouse_pos):
    titleObj, noteObj, rects = resultCardLayout(text, buttons)
    card = rects['card']
    shade = p.Surface(card.size, p.SRCALPHA)
    p.draw.rect(shade, (30, 30, 30, 215), shade.get_rect(), border_radius=14)
    screen.blit(shade, card.topleft)
    screen.blit(titleObj, (card.centerx - titleObj.get_width() / 2, card.y + 18))
    screen.blit(noteObj, (card.centerx - noteObj.get_width() / 2, card.y + 22 + titleObj.get_height()))
    for name in buttons:
        drawButton(screen, rects[name], RESULT_BUTTONS[name], True, mouse_pos)


# a separate GameState with the same moves, for searching in the background while gs stays on screen
def copyGame(gs):
    board = GameState()
    if board.playerWantsToPlayAsBlack:
        board.board = board.board1
    for move in gs.moveLog:
        board.makeMove(move)
    return board


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
