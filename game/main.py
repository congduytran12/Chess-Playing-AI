'''
    Add or remove bots :

    SET_WHITE_AS_BOT = False
    SET_BLACK_AS_BOT = True
'''

# Responsible for handling user input and displaying the current Gamestate object

import os
import re
import sys
import json
import math
import base64
import ctypes

# Fix Pygame resolution blurriness on Windows by telling the OS this app is high DPI aware
# (Windows then doesn't stretch the window; openWindow scales the game to the screen itself)
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
import browser
from textfield import TextField
from account import account, AccountError
import random
import string
import time
from urllib.parse import parse_qsl

# Explicitly seed random to fix deterministic room codes in WASM environments (Vercel)
random.seed(int(time.time() * 1000))

# Initialize the mixer
try:
    p.mixer.init()
except p.error as e:  # no sound device: the game plays silently
    print("Main: no sound -", e)
# the game's sounds by name (play them with playSound); a file that can't be loaded is left out
SOUND_FILES = {'move': "move-sound.ogg", 'capture': "capture.ogg", 'promote': "promote.ogg", 'check': "check.ogg",
               'game-start': "game-start.ogg", 'game-end': "game-end.ogg", 'low-time': "low-time.ogg",
               'notify': "notify.ogg"}
SOUNDS = {}
for _name, _file in SOUND_FILES.items():
    try:
        SOUNDS[_name] = p.mixer.Sound("sounds/" + _file)
    except Exception as e:
        print("Main: could not load sound %s -" % _file, e)

BOARD_WIDTH = BOARD_HEIGHT = 768
MOVE_LOG_PANEL_WIDTH = 375
MOVE_LOG_PANEL_HEIGHT = BOARD_HEIGHT
DIMENSION = 8
SQ_SIZE = BOARD_HEIGHT // DIMENSION
MAX_FPS = 30
ANIMATION_FPS = 60  # moving pieces slide at up to this frame rate
ANIMATION_BASE_MS = 90  # a move's slide takes this long plus ANIMATION_MS_PER_SQUARE per square
ANIMATION_MS_PER_SQUARE = 30
ANIMATION_SPEEDS = {'off': 0, 'fast': 0.5, 'normal': 1.0, 'slow': 1.7}  # Settings > Animation scales the slide's time
AI_MIN_THINK_MS = 400  # the computer's move (even an instant opening book move) waits at least this long
IMAGES = {}
SMALL_IMAGES = {}  # piece icons for the captured pieces row
SMALL_PIECE_SIZE = 22
CAPTURED_ICONS = {}  # (piece, halo color) -> a captured piece's icon with its halo (capturedIcon)
HELP_IMAGES = {}  # piece icons for the How to play window
HELP_ICON_SIZE = 40
DIAGRAM_IMAGES = {}  # pieces for the How to play window's board diagrams (HELP_DIAGRAM_SQ)
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
CONTROL_WEIGHTS = {'menu': 0.45}  # share of a row's width, against 1 for other controls (the menu is an icon)
INFO_HEIGHT = 54  # the review info box after the game

# --- layouts: how the canvas is arranged. 'landscape' (desktop always, and a browser window wider than tall): the
# board on the left and the side panel on the right, WINDOW_SIZE. 'portrait' (a browser window taller than wide, see
# layoutFor): PORTRAIT_WIDTH wide and as tall as the window's shape asks (within PORTRAIT_HEIGHTS); from the top the
# opponent's strip, the board, the player's strip, the status slot, the move list (after the game also the review
# info) and the controls, everything in the panel larger by the layout's scale so it reads and taps on a phone.
# Code placing the board or the panel reads the live LAYOUT (setLayout replaces it); the constants above keep the
# landscape values, which Layout('landscape') reproduces exactly. The board is drawn on a subsurface at LAYOUT.board,
# in its own (0, 0) coordinates; boardSquare and toBoard take canvas points to it. The windows (account, How to play,
# Settings) keep their own layout in a board-sized frame, drawn scaled up in portrait (windowTransform, drawWindow).
PORTRAIT_WIDTH = BOARD_WIDTH
PORTRAIT_HEIGHTS = (1400, 1700)  # the portrait canvas's height, from the window's shape, within these
PORTRAIT_SCALES = (1.0, 1.4)  # the portrait panel's scale: the largest (in steps of 0.05) at which the review fits
PORTRAIT_MIN_LIST_ROWS = 2  # rows of the move list the review must leave in portrait
LAYOUT = None  # the live Layout; made at the end of the module (it reads constants from all over it), see setLayout


class Layout:
    """The geometry of one arrangement of the canvas; scale enlarges the panel (1 in landscape)."""

    def __init__(self, kind='landscape', height=None, scale=1.0):
        self.kind = kind
        k = self.scale = scale
        self.stripHeight = round(STRIP_HEIGHT * k)
        if kind == 'portrait':
            self.size = (PORTRAIT_WIDTH, height)
            self.board = p.Rect(0, self.stripHeight, BOARD_WIDTH, BOARD_HEIGHT)
            self.panel = p.Rect(0, 0, PORTRAIT_WIDTH, height)  # everything around the board
            self.panelFill = [p.Rect(0, 0, PORTRAIT_WIDTH, self.board.top),
                              p.Rect(0, self.board.bottom, PORTRAIT_WIDTH, height - self.board.bottom)]
        else:
            self.size = (BOARD_WIDTH + MOVE_LOG_PANEL_WIDTH, BOARD_HEIGHT)
            self.board = p.Rect(0, 0, BOARD_WIDTH, BOARD_HEIGHT)
            self.panel = p.Rect(BOARD_WIDTH, 0, MOVE_LOG_PANEL_WIDTH, MOVE_LOG_PANEL_HEIGHT)
            self.panelFill = [self.panel]
        # the rows of controls (panelLayout): their left edge and width, and the bottom of the last row
        pad = round(PANEL_PADDING * k)
        self.controlsX, self.controlsWidth, self.controlsBottom = self.panel.x + pad, self.panel.width - 2 * pad, \
            self.panel.bottom - pad
        self.rowHeight = round(ROW_HEIGHT * k)
        self.rowGap = round(ROW_GAP * k)
        self.controlGap = round(10 * k)  # between the controls of a row
        self.graphHeight = 2 * self.rowHeight + self.rowGap
        self.labelSize = round(BUTTON_LABEL_SIZE * k)  # the largest panel button label, and the smallest
        self.labelMin = round(BUTTON_LABEL_MIN * k)
        self.statusHeight = round(STATUS_HEIGHT * k)
        self.infoHeight = round(INFO_HEIGHT * k)
        self.menuWidth = round(MENU_WIDTH * k)
        self.banner = p.Rect(0, 0, BOARD_WIDTH, round(36 * k))  # Looking back, across the top of the board
        # the move list: the landscape one scaled, in the middle of the panel
        listX = self.panel.x + (self.panel.width - round(MOVE_LOG_PANEL_WIDTH * k)) // 2
        self.moveRow = round(MOVE_ROW_HEIGHT * k)
        self.moveText = round(MOVE_TEXT_SIZE * k)
        self.movePadding = round(MOVE_LIST_PADDING * k)
        self.moveNumberRight = listX + round(48 * k)
        self.moveColumns = (listX + round(56 * k), listX + round(186 * k))
        self.moveCell = round(MOVE_CELL_WIDTH * k)
        self.scrollbarX = self.panel.right - round(14 * k)


# a panel size scaled by the layout's scale (font sizes and offsets inside the panel's parts)
def scaled(n):
    return round(n * LAYOUT.scale)


# switches the live layout; portrait takes the largest scale at which the busiest panel (a reviewed game against the
# computer with its graph) still leaves PORTRAIT_MIN_LIST_ROWS rows of moves
def setLayout(kind='landscape', height=None):
    global LAYOUT
    if kind != 'portrait':
        LAYOUT = Layout()
        return LAYOUT
    height = height or PORTRAIT_HEIGHTS[0]
    scale = PORTRAIT_SCALES[1]
    while True:
        LAYOUT = Layout('portrait', height, scale)
        rects = panelLayout(0, False, reviewing=True, graph=True)
        listTop, listBottom = panelAreas(min(rect.y for rect in rects.values()), True)['list']
        if scale <= PORTRAIT_SCALES[0] or listBottom - listTop >= LAYOUT.movePadding + PORTRAIT_MIN_LIST_ROWS * LAYOUT.moveRow:
            return LAYOUT
        scale = round(scale - 0.05, 2)


# (kind, height) of the layout for a browser window of viewport (width, height) CSS px; None (desktop): landscape
def layoutFor(viewport):
    if not viewport or viewport[0] <= 0 or viewport[1] <= viewport[0]:
        return 'landscape', None
    height = round(PORTRAIT_WIDTH * viewport[1] / viewport[0])
    return 'portrait', max(PORTRAIT_HEIGHTS[0], min(PORTRAIT_HEIGHTS[1], height))


# the parts of the panel around the controls (controlsTop: the first row's y), by name: 'topStrip' and 'bottomStrip'
# (the player strips), 'status' (the status slot), 'info' (the review info, after the game) and 'list' (the move
# list's top and bottom y). Landscape: the strips at the top and above the controls, the moves between them;
# portrait: the strips above and below the board, then the status slot, the moves, the info and the controls
def panelAreas(controlsTop, gameOver):
    layout, panel = LAYOUT, LAYOUT.panel
    if layout.kind == 'portrait':
        top = p.Rect(panel.x, 0, panel.width, layout.stripHeight)
        bottom = p.Rect(panel.x, layout.board.bottom, panel.width, layout.stripHeight)
        inset = scaled(10)
        status = p.Rect(panel.x + inset, bottom.bottom + scaled(6), panel.width - 2 * inset, layout.statusHeight)
        info = p.Rect(panel.x + inset, controlsTop - layout.rowGap - layout.infoHeight, panel.width - 2 * inset,
                      layout.infoHeight)
        listSpan = (status.bottom + scaled(4), (info.y if gameOver else controlsTop) - scaled(6))
    else:
        stripY = controlsTop - ROW_GAP - STRIP_HEIGHT
        top = p.Rect(panel.x, 0, panel.width, STRIP_HEIGHT)
        bottom = p.Rect(panel.x, stripY, panel.width, STRIP_HEIGHT)
        info = p.Rect(panel.x + 10, stripY - 60, panel.width - 20, INFO_HEIGHT)
        status = p.Rect(panel.x + 10, (info.y if gameOver else stripY) - STATUS_HEIGHT - 4, panel.width - 20,
                        STATUS_HEIGHT)
        listSpan = (STRIP_HEIGHT, status.y - 2)
    return {'topStrip': top, 'bottomStrip': bottom, 'status': status, 'info': info, 'list': listSpan}


# a canvas point in the board's own coordinates (the board subsurface's), and whether it is on the board
def toBoard(pos):
    return (pos[0] - LAYOUT.board.x, pos[1] - LAYOUT.board.y)


def onBoard(pos):
    return LAYOUT.board.collidepoint(pos)

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
ROOM_CODE_LENGTH = 12
# quick chat in an online room: canned messages sent by their index, so nothing typed ever goes out
QUICK_CHAT = ["Hello!", "Good luck!", "Good game!", "Thanks!", "Well played!", "Oops", "One moment, please"]
CHAT_INTERVAL_MS = 3000  # at most one chat message per this many ms (Chat is disabled in between)
CHAT_FRESH_SECONDS = 30  # a received chat older than this (server clock) is history replayed on joining: not shown
# online: our own sync_request coming back marks when we joined (ntfy's clock); without it after this long, the
# room's latest time stands in for it
JOIN_ECHO_MS = 10000
CHAT_BUBBLE_MS = 5000  # a chat message's bubble shows this long by its sender's name
CHAT_FADE_MS = 400  # and fades out over its last this many ms


def get_text_surface(text, size, color, bold=True, sans=False):
    """
    Returns a cached text surface or renders a new one if not found.
    Reduces the number of font.render calls to once per dynamic change.
    """
    key = (text, size, color, bold, sans)
    if key not in UI_CACHE:
        UI_CACHE[key] = get_font(size, bold, sans).render(text, True, p.Color(color))
    return UI_CACHE[key]


# the font ships with the game: browsers have no system fonts, and SysFont there falls back
# to an already-bold sans font that turns smudgy when bolded again
# sans: pygame's bundled default font (already bold, so bold is ignored), for button labels
# also used directly for text that changes every frame (clocks), which would otherwise fill the surface cache
def get_font(size, bold=True, sans=False):
    key = (size, bold and not sans, sans)
    if key not in FONT_CACHE:
        FONT_CACHE[key] = p.font.Font(None, size) if sans else p.font.Font(FONT_BOLD if bold else FONT_REGULAR, size)
    return FONT_CACHE[key]


# largest text surface (up to size) that fits in maxWidth
def get_fitting_text(text, maxWidth, size, color, bold=True, sans=False):
    surface = get_text_surface(text, size, color, bold, sans)
    while surface.get_width() > maxWidth and size > 12:
        size -= 2
        surface = get_text_surface(text, size, color, bold, sans)
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
DRAG_THRESHOLD = 6  # px the pointer moves with the button held before a press on a piece becomes a drag
DRAG_TARGET_COLOR = (30, 30, 30, 110)  # outline of the square under a dragged piece
# the player's own marks and arrows (right button); see-through like ARROW_COLOR, and readable on every board theme
ANNOTATION_COLORS = {'green': (21, 120, 27, 200), 'red': (200, 32, 32, 200), 'blue': (0, 72, 186, 200)}
# the window's focus events (pygame 2.0.1+; without them the window counts as always focused)
WINDOW_FOCUS_LOST = getattr(p, 'WINDOWFOCUSLOST', -1)
WINDOW_FOCUS_GAINED = getattr(p, 'WINDOWFOCUSGAINED', -1)
KING_FLASH_MS = 600  # a refused move (it would leave the king in check) makes the king's square pulse this long
KING_FLASH_COLOR = (220, 20, 20)
# why a move the piece could make is refused (see refusalReason)
PREMOVE_COLOR = (132, 76, 196)  # the chosen premove's squares: a soft purple that reads on every board theme
PREMOVE_ALPHA = 150
PREMOVE_DROPPED = "Premove canceled: no longer legal"
LOOK_BACK_BANNER = p.Rect(0, 0, BOARD_WIDTH, 36)  # across the top of the board while looking back during a game
REFUSED_IN_CHECK = "You're in check: move the king, block, or capture"
REFUSED_EXPOSES_KING = "That would leave your king in check"
STRIP_COLOR = (222, 224, 190)
DISABLED_COLOR = (165, 165, 165)
CONFIRM_COLOR = (186, 72, 58)  # the action of a confirmation that can't be taken back (Resign, Leave)
SELECTED_OPTION_COLOR = (82, 112, 54)  # the current choice in an open dropdown
NEUTRAL_COLOR = (118, 118, 118)  # Cancel / Decline

# colors of the side panel and the windows, light or dark (Settings); the board keeps BOARD_COLORS.
# Drawing code reads the live dict UI, which setUiTheme() refills. Besides the shared keys:
# textBody (help paragraphs), hoverOutline (a hovered swatch), clockActive / clockIdle / clockText /
# clockTextIdle / clockLow (the clock boxes), blunder / mistake / inaccuracy (analysis marks),
# segment / segmentText (an unselected choice of a Settings switch), accentText (text on the accent color) and
# bannerBg / bannerText (the see-through Looking back bar over the board), scrollTrack / scrollThumb (the move list's
# scrollbar) and graphWhite / graphBlack / graphEdge / graphMiddle (the evaluation graph: White's and Black's areas,
# the line between them and the middle line), recordWon / recordDrawn / recordLost (the profile's bars of results),
# bubble / bubbleText / bubbleBorder (a quick chat message's speech bubble by a player strip) and capturedHalo (the
# thin outline that keeps Black's captured pieces readable on a player strip, see capturedIcon)
PALETTES = {
    'light': {
        'panel': LIGHT_SQUARE_COLOR, 'strip': STRIP_COLOR, 'stripLine': DARK_SQUARE_COLOR,
        'text': (0, 0, 0), 'textDim': (105, 105, 105), 'textBody': (60, 60, 60),
        'button': DARK_SQUARE_COLOR, 'buttonHover': MOVE_HIGHLIGHT_COLOR, 'buttonPressed': (62, 88, 128),
        'buttonDisabled': DISABLED_COLOR, 'buttonText': (255, 255, 255), 'buttonTextDisabled': (240, 240, 240),
        'window': LIGHT_SQUARE_COLOR, 'windowBorder': DARK_SQUARE_COLOR, 'shade': (0, 0, 0, 150),
        'field': (225, 225, 225), 'fieldFocus': (255, 255, 255), 'fieldBorder': (190, 190, 190),
        'fieldBorderFocus': MOVE_HIGHLIGHT_COLOR, 'fieldText': (0, 0, 0),
        'accent': MOVE_HIGHLIGHT_COLOR, 'selectedOption': SELECTED_OPTION_COLOR, 'confirm': CONFIRM_COLOR,
        'neutral': NEUTRAL_COLOR, 'statusBg': (40, 40, 40, 225), 'statusText': (255, 255, 255),
        'error': (178, 34, 34), 'success': (0, 100, 0), 'warning': (230, 120, 0),
        'infoBox': STRIP_COLOR, 'infoBoxBorder': DARK_SQUARE_COLOR, 'logHighlight': LAST_MOVE_COLOR,
        'tooltipBg': (40, 40, 40), 'tooltipText': (255, 255, 255), 'hoverOutline': (128, 128, 128),
        'clockActive': (255, 255, 255), 'clockIdle': (200, 200, 200), 'clockText': (0, 0, 0),
        'clockTextIdle': (0, 0, 0), 'clockLow': (220, 0, 0),
        'blunder': (200, 30, 30), 'mistake': (225, 110, 0), 'inaccuracy': (185, 150, 0),
        'segment': (222, 222, 214), 'segmentText': (45, 45, 45), 'accentText': (255, 255, 255),
        'bannerBg': MOVE_HIGHLIGHT_COLOR + (205,), 'bannerText': (255, 255, 255),
        'scrollTrack': (219, 221, 190), 'scrollThumb': (150, 160, 124),
        'graphWhite': (250, 250, 244), 'graphBlack': (98, 102, 90), 'graphEdge': (150, 152, 140),
        'graphMiddle': (160, 162, 150),
        'recordWon': (92, 150, 62), 'recordDrawn': (168, 170, 158), 'recordLost': (196, 82, 66),
        'bubble': (255, 255, 255), 'bubbleText': (28, 30, 26), 'bubbleBorder': (150, 160, 124),
        'capturedHalo': (246, 247, 232),
    },
    'dark': {
        'panel': (38, 40, 36), 'strip': (50, 53, 47), 'stripLine': (78, 104, 54),
        'text': (232, 232, 225), 'textDim': (160, 164, 155), 'textBody': (208, 210, 201),
        'button': (86, 118, 58), 'buttonHover': MOVE_HIGHLIGHT_COLOR, 'buttonPressed': (62, 88, 128),
        'buttonDisabled': (74, 77, 71), 'buttonText': (242, 242, 236), 'buttonTextDisabled': (146, 149, 142),
        'window': (46, 48, 44), 'windowBorder': (86, 118, 58), 'shade': (0, 0, 0, 170),
        'field': (62, 64, 60), 'fieldFocus': (74, 77, 71), 'fieldBorder': (96, 99, 92),
        'fieldBorderFocus': (112, 148, 204), 'fieldText': (235, 235, 228),
        'accent': (112, 148, 204), 'selectedOption': (62, 88, 42), 'confirm': (168, 66, 54),
        'neutral': (96, 98, 94), 'statusBg': (222, 224, 214, 238), 'statusText': (28, 30, 26),
        'error': (240, 112, 100), 'success': (126, 200, 112), 'warning': (240, 170, 72),
        'infoBox': (50, 53, 47), 'infoBoxBorder': (86, 118, 58), 'logHighlight': (84, 96, 50),
        'tooltipBg': (222, 224, 214), 'tooltipText': (28, 30, 26), 'hoverOutline': (130, 134, 126),
        'clockActive': (222, 224, 214), 'clockIdle': (66, 69, 63), 'clockText': (20, 20, 18),
        'clockTextIdle': (200, 202, 195), 'clockLow': (200, 30, 30),
        'blunder': (240, 96, 86), 'mistake': (245, 152, 64), 'inaccuracy': (222, 196, 76),
        'segment': (64, 67, 61), 'segmentText': (222, 224, 214), 'accentText': (18, 22, 30),
        'bannerBg': (112, 148, 204, 210), 'bannerText': (18, 22, 30),
        'scrollTrack': (54, 57, 51), 'scrollThumb': (112, 118, 104),
        'graphWhite': (214, 216, 206), 'graphBlack': (24, 25, 22), 'graphEdge': (130, 133, 124),
        'graphMiddle': (110, 113, 104),
        'recordWon': (112, 176, 88), 'recordDrawn': (128, 131, 122), 'recordLost': (212, 98, 84),
        'bubble': (74, 78, 70), 'bubbleText': (240, 240, 233), 'bubbleBorder': (120, 126, 112),
        'capturedHalo': (185, 188, 178),
    },
}
UI = dict(PALETTES['light'])
MARK_KINDS = {"??": 'blunder', "?": 'mistake', "?!": 'inaccuracy'}  # analysis mark -> its palette color
BUTTON_RADIUS = 8  # rounded corners of buttons, dropdown options and the status slot
WINDOW_RADIUS = 12  # and of the account, help and settings windows
BUTTON_LABEL_SIZE = 28  # largest button label (sans font)
# a panel row shrinks its labels together down to this size; a label that still doesn't fit (a long name) shrinks alone
BUTTON_LABEL_MIN = 20
MOUSE_HELD = [False]  # the left mouse button is down (from the events), for the pressed look of buttons


def setUiTheme(name):
    UI.clear()
    UI.update(PALETTES.get(name, PALETTES['light']))


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


# Settings > Sound and Volume: every sound plays at the chosen volume, or not at all
def soundVolume():  # 0 to 1
    try:
        volume = max(0, min(100, int(settings.get('volume')))) if settings.get('sound') else 0
    except (TypeError, ValueError):
        volume = settings.DEFAULTS['volume']
    return volume / 100


def applySoundSettings():
    volume = soundVolume()
    for sound in SOUNDS.values():
        sound.set_volume(volume)


# every sound goes through here: nothing plays while Sound is off, and a sound problem never stops the game
# returns whether it played
def playSound(name):
    try:
        sound = SOUNDS.get(name)
        volume = soundVolume()
        if sound is None or volume <= 0:
            return False
        sound.set_volume(volume)
        sound.play()
        return True
    except Exception as e:
        print("Main: could not play %s -" % name, e)
        return False


# the sound of a move: check matters most, then a promotion, then a capture (move.san ends in + or # for check)
def moveSoundName(move):
    if (move.san or "").endswith(('+', '#')):
        return 'check'
    if move.isPawnPromotion:
        return 'promote'
    if move.isCapture:
        return 'capture'
    return 'move'


LOW_TIME_MS = 10000  # a player's clock below this plays 'low-time' once per game


# the sides whose clock just went low: on this device's players' clocks, each once per game
def lowTimeSides(clocks, humanColors, warned):
    return [color for color in 'wb' if color in humanColors and color not in warned and 0 < clocks[color] < LOW_TIME_MS]


GAME_TITLE = "Chess Playing AI"
YOUR_MOVE_TITLE = "Your move · Chess Playing AI"  # while the player is away and it's their turn


# whether the opponent's move just gave the turn to the player (vs computer or online, not two players on one
# screen): there are more moves than last frame, and now it's the player's turn
def turnArrived(modeIndex, humanTurn, movesBefore, movesNow, gameOver):
    return modeIndex in (0, 2) and humanTurn and movesNow > movesBefore and not gameOver


# how long a move's slide takes (ms): longer moves a little longer, scaled by Settings > Animation (0 = no slide)
def animationDuration(move, speed=None):
    scale = ANIMATION_SPEEDS.get(speed or settings.get('animation'), 1.0)
    squares = max(abs(move.endRow - move.startRow), abs(move.endCol - move.startCol))
    return (ANIMATION_BASE_MS + ANIMATION_MS_PER_SQUARE * squares) * scale


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
        DIAGRAM_IMAGES[piece] = p.transform.smoothscale(original_image, (HELP_DIAGRAM_SQ, HELP_DIAGRAM_SQ))
    CAPTURED_ICONS.clear()


# the four pieces in a column over the promotion square, with the board dimmed behind them; screen is the board's
# surface (main's boardSurface), so the pointer is taken to the board's coordinates
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
                mouse_pos = toBoard(pointerPos())
                for i, button in enumerate(buttons):
                    if button.collidepoint(mouse_pos):
                        return choices[i]
                return None

        screen.blit(background, (0, 0))
        mouse_pos = toBoard(pointerPos())
        setCursor('hand' if any(button.collidepoint(mouse_pos) for button in buttons) else 'arrow')
        for i, button in enumerate(buttons):
            hovered = button.collidepoint(mouse_pos)
            p.draw.rect(screen, p.Color(LAST_MOVE_COLOR) if hovered else p.Color("white"), button)
            p.draw.rect(screen, p.Color(DARK_SQUARE_COLOR), button, 2)
            screen.blit(IMAGES[color + choices[i]], button.topleft)

        p.display.flip()
        clock.tick(MAX_FPS)
        await asyncio.sleep(0) # Yield for browser UI


# names of the panel controls, row by row from the top; which controls exist depends on the mode
# graph: after the game, once an analysis exists, its evaluation graph replaces the Analyze game button
# guest: online in a room as the guest, who has no invite link to copy (only the host invites)
def panelRows(modeIndex, connected, canRejoin=False, reviewing=False, graph=False, guest=False):
    if modeIndex == 0:  # Local vs AI
        rows = [['mode'], ['level', 'side'], ['clock', 'hint']]
    elif modeIndex == 1:  # Local 2-Player
        rows = [['mode'], ['clock', 'hint']]
    elif not connected:  # Online, choosing a room
        rows = [['mode'], ['room', 'clock'], ['host', 'join']]
        if canRejoin:
            rows.append(['rejoin'])
    else:  # Online, in a room: Copy link (host) and the quick chat under the room's line
        rows = [['mode'], ['roomInfo'], ['chat'] if guest else ['invite', 'chat']]
    if reviewing:  # after the game: analysis and stepping through the moves
        rows += [['graph' if graph else 'analyze'], ['first', 'prev', 'next', 'last']]
    elif modeIndex != 2 or connected:  # online without a room there is no game to resign or draw yet
        rows.append(['resign', 'draw'])
    rows.append(['undo', 'restart', 'account', 'menu'])  # the menu holds the rarer actions (MENU_ITEMS)
    return rows


# rects of the panel controls, by name (the graph is a taller row, GRAPH_HEIGHT)
def panelLayout(modeIndex, connected, canRejoin=False, reviewing=False, graph=False, guest=False):
    rows = panelRows(modeIndex, connected, canRejoin, reviewing, graph, guest)
    rects = {}
    layout = LAYOUT
    heights = [layout.graphHeight if row == ['graph'] else layout.rowHeight for row in rows]
    y = layout.controlsBottom - sum(heights) - (len(rows) - 1) * layout.rowGap
    gap = layout.controlGap
    for row, height in zip(rows, heights):
        # controls share the row width, 10px apart (scaled); CONTROL_WEIGHTS makes some narrower
        unit = (layout.controlsWidth - gap * (len(row) - 1)) / sum(CONTROL_WEIGHTS.get(name, 1) for name in row)
        x = layout.controlsX
        for i, name in enumerate(row):
            width = round(unit * CONTROL_WEIGHTS.get(name, 1))
            if i == len(row) - 1:
                width = layout.controlsX + layout.controlsWidth - x  # last one absorbs rounding
            rects[name] = p.Rect(x, y, width, height)
            x += width + gap
        y += height + layout.rowGap
    return rects


DROPDOWNS = ('mode', 'level', 'side', 'clock')  # panel controls that open a list of options


# room a button leaves for its label (a dropdown also shows its arrow)
def buttonTextWidth(rect, arrow=False):
    return rect.width - (36 if arrow else 12)


LABEL_FIT_CACHE = {}  # (text, width, largest, smallest) -> largest label size that fits


# the panel's label sizes run from LAYOUT.labelSize down to LAYOUT.labelMin (BUTTON_LABEL_SIZE and BUTTON_LABEL_MIN
# in landscape)
def labelFitSize(text, width):
    key = (text, width, LAYOUT.labelSize, LAYOUT.labelMin)
    if key not in LABEL_FIT_CACHE:
        size = LAYOUT.labelSize
        while size > LAYOUT.labelMin and get_font(size, True, True).size(text)[0] > width:
            size -= 1
        LABEL_FIT_CACHE[key] = size
    return LABEL_FIT_CACHE[key]


# one label size per row of buttons, the largest at which every label in the row fits, so a row reads evenly
# rows: lists of names (panelRows), rects and labels by name; icon buttons (empty labels) don't count
def evenLabelSizes(rows, rects, labels):
    sizes = {}
    for row in rows:
        names = [name for name in row if name in rects and labels.get(name)]
        size = min([labelFitSize(labels[name], buttonTextWidth(rects[name], name in DROPDOWNS)) for name in names]
                   or [LAYOUT.labelSize])
        for name in row:
            sizes[name] = size
    return sizes


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
    height = LAYOUT.rowHeight
    return [p.Rect(rect.x, rect.y - (count - i) * height, rect.width, height) for i in range(count)]


# the menu (the three-line button at the bottom right): its items in order, top to bottom
MENU_ITEMS = [('save', "Save game (PGN)"), ('load', "Load game (PGN)"), ('flip', "Flip board (F)"),
              ('settings', "Settings"), ('help', "How to play (H)")]
MENU_WIDTH = 230
MENU_GAP = 4  # between the items
MENU_PADDING = 6  # between the items and the menu's frame, and between the frame and its button


# a list that opens upwards from its button like a dropdown, its frame right-aligned with it (the menu's button is
# narrow): the rects of the items named in names, top to bottom
def popupItemRects(buttonRect, names):
    count, width, height = len(names), LAYOUT.menuWidth, LAYOUT.rowHeight
    x = buttonRect.right - MENU_PADDING - width
    bottom = buttonRect.y - 2 * MENU_PADDING
    return {name: p.Rect(x, bottom - (count - i) * height - (count - 1 - i) * MENU_GAP, width, height)
            for i, name in enumerate(names)}


# the frame drawn around such a list's items
def popupBoxRect(rects):
    rects = list(rects.values())
    return rects[0].unionall(rects[1:]).inflate(2 * MENU_PADDING, 2 * MENU_PADDING)


def menuItemRects(menuRect):
    return popupItemRects(menuRect, [name for name, _ in MENU_ITEMS])


def menuBoxRect(menuRect):
    return popupBoxRect(menuItemRects(menuRect))


# the quick chat's messages open from the Chat button the same way, keyed by their index in QUICK_CHAT
def chatItemRects(chatRect):
    return popupItemRects(chatRect, list(range(len(QUICK_CHAT))))


# Accept / Decline prompt for undo requests and draw offers, drawn over the move log (in portrait just under the
# status slot, over the first moves, so a message shown meanwhile doesn't cover its question)
def promptRects():
    layout = LAYOUT
    top = (layout.board.bottom + layout.stripHeight + scaled(6) + layout.statusHeight + scaled(6)
           if layout.kind == 'portrait' else 150)
    panel = p.Rect(layout.controlsX, top, layout.controlsWidth, scaled(100))
    accept = p.Rect(panel.x + scaled(10), panel.y + scaled(48), panel.width // 2 - scaled(15), layout.rowHeight)
    decline = p.Rect(panel.centerx + scaled(5), panel.y + scaled(48), panel.width // 2 - scaled(15), layout.rowHeight)
    return panel, accept, decline


# --- the desktop window: resizable, and scaled so it fits any screen (the game always draws at WINDOW_SIZE; SCALED
# stretches it to the window, and pygame maps the mouse back to game pixels)

WINDOW_SIZE = (BOARD_WIDTH + MOVE_LOG_PANEL_WIDTH, BOARD_HEIGHT)
WINDOW_MIN_SCALE = 0.5  # the window can be made this small (of WINDOW_SIZE), and never starts smaller
FRAME_GUESS = (16, 90)  # off Windows: room left for the window's frame and title bar and the desktop's bars


# the window's starting size (inside its frame) for a usable desktop area and the frame's extra width and height:
# the largest whole scale that fits, as pygame's SCALED picks (crisp), or when even 1x doesn't fit, as large as fits
def startingWindowSize(size, usable, frame):
    fit = min((usable[0] - frame[0]) / size[0], (usable[1] - frame[1]) / size[1])
    scale = max(1, math.floor(fit)) if fit >= 1 else max(WINDOW_MIN_SCALE, fit)
    return (round(size[0] * scale), round(size[1] * scale))


# the desktop's usable area (without the taskbar), the frame's extra (width, height) and where the window's
# inside sits in its frame (x, y), or None for that offset when unknown; None when nothing is known
def desktopArea():
    if sys.platform == 'win32':
        try:
            user32 = ctypes.windll.user32
            work = (ctypes.c_long * 4)()
            if user32.SystemParametersInfoW(0x30, 0, work, 0):  # SPI_GETWORKAREA, in pixels (the process is DPI aware)
                side = user32.GetSystemMetrics(32) + user32.GetSystemMetrics(92)  # SM_CXSIZEFRAME + SM_CXPADDEDBORDER
                caption = user32.GetSystemMetrics(4)  # SM_CYCAPTION
                return (p.Rect(work[0], work[1], work[2] - work[0], work[3] - work[1]), (2 * side, caption + 2 * side),
                        (side, side + caption))
        except Exception as e:
            print("Main: could not read the desktop's work area -", e)
    try:
        width, height = p.display.get_desktop_sizes()[0]
        return p.Rect(0, 0, width, height), FRAME_GUESS, None
    except Exception:
        return None


# the SDL2.dll pygame loaded (so it is the same SDL, with the same windows and mouse), or None (off Windows)
SDL_LIBRARY = []


def sdlLibrary():
    if not SDL_LIBRARY:
        sdl = None
        try:
            path = os.path.join(os.path.dirname(p.__file__), 'SDL2.dll')
            if os.path.exists(path):
                sdl = ctypes.CDLL(path)
        except Exception as e:
            print("Main: could not load SDL2.dll -", e)
        SDL_LIBRARY.append(sdl)
    return SDL_LIBRARY[0]


# pygame makes a SCALED window no smaller than the game; SDL itself allows it (through the SDL2.dll pygame loaded,
# so it is the same SDL). Returns whether it worked
def setWindowMinimumSize(window, size):
    try:
        sdl = sdlLibrary()
        if sdl is None:
            return False
        sdl.SDL_GetWindowFromID.restype = ctypes.c_void_p
        sdl.SDL_GetWindowFromID.argtypes = [ctypes.c_uint32]
        sdl.SDL_SetWindowMinimumSize.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        handle = sdl.SDL_GetWindowFromID(window.id)
        if not handle:
            return False
        sdl.SDL_SetWindowMinimumSize(handle, int(size[0]), int(size[1]))
        return True
    except Exception as e:
        print("Main: could not set the window's minimum size -", e)
        return False


# the desktop window's pygame Window, kept for as long as the display exists: pygame gives SDL only a borrowed
# pointer to it, and puts that pointer in every window event (freed, the first event crashes the game)
DESKTOP_WINDOW = []


# where the scaled game sits in a window of window size (centered, as large as fits: the rest is black bars)
def pictureRect(window, size):
    scale = min(window[0] / size[0], window[1] / size[1])
    width, height = round(size[0] * scale), round(size[1] * scale)
    return p.Rect((window[0] - width) // 2, (window[1] - height) // 2, width, height)


# the pointer in game pixels, or (-1, -1) in the black bars of a scaled desktop window that isn't the game's shape:
# pygame pulls a point there onto the picture's edge (the board's a-file, or the panel's edge)
def pointerPos():
    pos = p.mouse.get_pos()
    sdl = sdlLibrary() if DESKTOP_WINDOW else None
    if sdl is None:
        return pos
    try:
        x, y = ctypes.c_int(), ctypes.c_int()
        sdl.SDL_GetMouseState(ctypes.byref(x), ctypes.byref(y))  # in the window's own pixels, not clamped
        if not pictureRect(p.display.get_window_size(), p.display.get_surface().get_size()).collidepoint(x.value,
                                                                                                         y.value):
            return (-1, -1)
    except Exception:
        pass
    return pos


# the game's window: in the browser (the page scales the canvas) and under the headless tests' dummy driver as
# before; on desktop resizable and scaled, starting at a size that fits the screen with its frame
def openWindow(size=WINDOW_SIZE):
    if sys.platform == 'emscripten' or p.display.get_driver() == 'dummy':
        return p.display.set_mode(size)
    try:
        from pygame._sdl2.video import Window, WINDOWPOS_CENTERED
    except Exception:  # can't resize it afterwards: pygame's own SCALED size (whole multiples that fit the desktop)
        Window = None
    area = desktopArea() if Window else None
    target = startingWindowSize(size, area[0].size, area[1]) if area else size
    if Window:
        # pygame reads this hint by its macro's name: any scale, not only whole multiples, so the window can be
        # smaller than the game; the real hint smooths a scale that isn't whole and keeps whole ones crisp
        os.environ['SDL_HINT_RENDER_SCALE_QUALITY'] = '1'
        # (SDL reads it once, here: a window that starts at 1x and is maximized later is smoothed too)
        os.environ['SDL_RENDER_SCALE_QUALITY'] = ('nearest' if target[0] % size[0] == 0 and target[0] >= 2 * size[0]
                                                  else 'linear')
    try:
        # hidden until it has its size: with the hint, pygame first makes it as large as the desktop
        screen = p.display.set_mode(size, p.SCALED | p.RESIZABLE | (p.HIDDEN if Window else 0))
    except p.error as e:
        print("Main: no scaled window -", e)
        return p.display.set_mode(size)
    if not Window:
        return screen
    window = None
    try:
        window = Window.from_display_module()
        DESKTOP_WINDOW[:] = [window]
        setWindowMinimumSize(window, (round(size[0] * WINDOW_MIN_SCALE), round(size[1] * WINDOW_MIN_SCALE)))
        window.size = target
        if area and area[2]:  # centered in the work area, frame included
            usable, frame, inside = area
            window.position = (usable.x + (usable.width - target[0] - frame[0]) // 2 + inside[0],
                               usable.y + max(0, (usable.height - target[1] - frame[1]) // 2) + inside[1])
        else:
            window.position = WINDOWPOS_CENTERED
    except Exception as e:
        print("Main: could not size the window -", e)
    finally:
        try:
            window = window or Window.from_display_module()
            DESKTOP_WINDOW[:] = [window]
            window.show()
        except Exception as e:
            print("Main: could not show the window -", e)
    return screen


# browser: the page fits the canvas to the window using the canvas's aspect ratio, and may have done so while the
# canvas was still its 1x1 placeholder (stretching the game into a square), or before the layout changed its shape
def refitCanvas():
    if sys.platform == 'emscripten':
        try:
            import platform
            platform.window.window_resize()
        except Exception as e:
            print("Main: could not refit canvas:", e)


LAYOUT_CHECK_MS = 500  # browser: how often the game checks whether the window turned (portrait <-> landscape)


async def main():
    # initialize py game
    p.init()
    print("Main: v13.0 Loaded (Clocks, Hints, PGN)")
    # the desktop window's title and icon (before set_mode: some systems ignore an icon set afterwards)
    p.display.set_caption(GAME_TITLE)
    try:
        p.display.set_icon(p.transform.smoothscale(p.image.load("images1/wN.png"), (64, 64)))
    except Exception as e:
        print("Main: could not set the window icon:", e)
    # the layout follows the browser window's shape (portrait on an upright phone); desktop is always landscape
    setLayout(*layoutFor(browser.viewportSize()))
    screen = openWindow(LAYOUT.size)
    refitCanvas()
    boardSurface = screen.subsurface(LAYOUT.board)  # the board draws here in its own (0, 0) coordinates
    lastLayoutCheck = p.time.get_ticks()  # the window's shape is looked at again every LAYOUT_CHECK_MS

    clock = p.time.Clock()
    setUiTheme(settings.get('uiTheme'))  # the panel theme, board colors and pieces chosen in Settings last time
    setBoardTheme(settings.get('board'))
    applySoundSettings()
    screen.fill(p.Color(UI['panel']))
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
    # the computer's search while it thinks: {'task', 'gs', 'ply', 'started'}; it runs in the background on a
    # copy of the game, so the screen and the clocks keep updating
    aiSearch = None
    openDropdown = None  # name of the dropdown whose options are showing
    menuOpen = False  # the menu's items are showing
    boardFlipped = False  # the player turned the board around (F); flips whatever the automatic orientation is
    # dragging a piece: {'square', 'pressPos', 'active'}; armed by pressing on an own piece, active once the
    # pointer moved DRAG_THRESHOLD px with the button held (until then the press is an ordinary click)
    drag = None
    # the player's marks and arrows (right button): square -> color name, (start, end) -> color name
    boardRings = {}
    boardArrows = {}
    rightPressed = None  # (square, color name) where the right button went down on the board
    kingFlash = None  # (king's square, ticks) after a refused move, while the square pulses
    # the player's move chosen during the opponent's turn, played when their turn comes: (start, end) squares
    premove = None
    premoveCache = {'key': None, 'moves': []}  # the premove candidates of the current position (premoveMoves)

    currentModeIndex = 0 # 0: Local vs AI, 1: Local 2-Player, 2: Online Multiplayer
    sideIndex = 0  # vs AI: play as White, Black or Random
    clockIndex = 0  # index into CLOCK_OPTIONS
    multiplayerMode = False
    multiplayerRole = None
    roomCode = ""
    inputBoxActive = False
    # the room box's editing; roomCode stays the room's code, and the box follows it when it changes elsewhere
    roomField = TextField(maxLength=ROOM_CODE_LENGTH, allowed=ROOM_CODE_CHARACTERS, transform=str.upper,
                          onPaste=pasteRoomCode)
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
    chatOpen = False  # the quick chat's messages are showing (opened from the Chat button like the menu)
    lastChatSent = None  # ticks when we last sent a chat message (CHAT_INTERVAL_MS apart)
    chatBubbles = {}  # color -> (text, ticks): the chat message shown by that player's strip, for CHAT_BUBBLE_MS
    copyPending = None  # (ticks, room code) while the browser hasn't said whether the invite link was copied
    invitedRoom = None  # the friend's room from an invite link: Host makes a room of its own instead

    # player account (see account.py): the account window, and saving finished games to the account
    # 'signin' | 'register' | 'forgot' | 'newPassword' | 'profile' | 'games' | 'leaderboard' while the window is open
    accountView = None
    helpPage = None  # page of the How to play window (index into HELP_PAGES) while it's open
    settingsTab = None  # the Settings window's open tab ('board' or 'game'), None while it's closed
    lastSettingsTab = 'board'  # it opens on the tab it was closed on
    # tooltips: what the pointer is over (an id from pointerTarget), since when, and whether a click hid its tooltip
    hoverId = None
    hoverSince = 0
    tooltipHidden = False
    # the account forms' fields (login: email or username, to sign in); the forgot view uses email, newPassword password
    accountFields = {'username': TextField(maxLength=20, allowed=USERNAME_CHARACTERS), 'email': TextField(),
                     'login': TextField(), 'password': TextField(password=True)}
    accountFocus = 'login'  # the form field being typed into
    accountShowPassword = False  # the password field's Show / Hide
    accountMessage = ""  # error or notice shown in the account window
    accountTone = 'error'  # how it reads: 'error' or 'success'
    accountList = []  # saved games or leaderboard rows shown in the window
    accountScroll = 0  # the first saved game in view
    # pressing on the saved games: {'pos', 'scroll', 'active'} as listPress; accountThumb: dragging their scrollbar
    accountPress = None
    accountThumb = None
    # {'token', 'refresh', 'email'?} from a password reset link the page was opened with (browser)
    resetLink = None
    accountRequests = []  # running requests: (task, onDone, onError, shownInWindow)
    gameSaved = False  # the finished game was sent to the account
    savedGameId = None  # its id there, so finishing again after an undo updates it
    gameLoaded = False  # loaded from a file or the account, so not saved again
    ratingReported = False
    asyncio.ensure_future(account.restore())  # stays signed in from last time

    moveUndone = False
    positionHistory = [gs.getPositionKey()]  # one position key per ply, for threefold repetition
    moveLogScroll = 0  # move list rows scrolled back from the newest (0: new moves stay in view)
    gameResult = None  # (text, PGN result) when the game ended by resignation, agreement or time
    resultCardHidden = False  # the player clicked beside the result card to see the final position
    outcome = None  # (text, PGN result) once the game is over, worked out every frame
    hintMove = None  # suggested move shown on the board
    hintState = None  # 'requested' -> 'searching' -> None
    statusText = ""  # short message shown at the bottom of the board
    statusUntil = 0
    # after the game: stepping through the moves, and the AI's analysis of them
    # looking back, during the game or after it: the board shows an earlier position, read-only
    reviewPly = None  # number of moves shown on the board, None for the live (or final) position
    reviewGs = None  # the position at reviewPly
    wasGameOver = False  # the game was over last frame (a game that just ended leaves any looking back)
    reviewScroll = False  # scroll the move log to the shown move on the next draw
    analysis = None  # {'evals', 'best', 'bestSan', 'done', 'task'}, filled in while the analysis runs
    moveList = moveListLayout(0, STRIP_HEIGHT, STRIP_HEIGHT + 100)  # the move list as last drawn (moveListLayout)
    # pressing on the move list: {'pos', 'scroll' (at the press), 'active'}; it scrolls the list once the pointer
    # moved DRAG_THRESHOLD px with the button held, else the release selects the move under the press
    listPress = None
    thumbGrab = None  # dragging the scrollbar's thumb: the pointer's y within the thumb
    graphHeld = False  # the button went down on the evaluation graph: dragging shows the move under the pointer

    timeControl = None  # (starting seconds, increment seconds) of the current game, None for no clock
    clocks = {'w': 0, 'b': 0}  # milliseconds left
    clockHistory = [dict(clocks)]  # clocks after each ply, so an undo can restore them
    lastClockTick = p.time.get_ticks()

    # sounds and alerts of the game as a whole
    endSoundPlayed = False  # 'game-end' plays once per game
    lowTimeWarned = set()  # the colors whose low clock was already heard this game
    caughtUp = False  # online: the first state adopted after connecting is catching up, not a game starting
    # online: this connection's id (on its sync_request), ntfy's time when that came back (None until then: what
    # arrives before it is the room's history), and the ticks when we connected
    joinId, joinedAt, connectedAt = None, None, 0
    windowFocused = True  # desktop: the window has the keyboard focus (WINDOWFOCUSLOST / WINDOWFOCUSGAINED)
    yourMoveAlert = False  # the title says "Your move" (the player was away when their turn came)
    movesSeen = 0  # moves in the game last frame, to notice the opponent's move

    def showStatus(text, duration=3000):
        nonlocal statusText, statusUntil
        statusText = text
        statusUntil = p.time.get_ticks() + duration

    # the marks and arrows belong to the position they were drawn on
    def clearAnnotations():
        nonlocal rightPressed
        boardRings.clear()
        boardArrows.clear()
        rightPressed = None

    # the dragged piece goes back to its square; deselect: also drop the selection (Esc, right button)
    def cancelDrag(deselect=False):
        nonlocal drag, squareSelected, playerClicks
        if drag is not None and deselect:
            squareSelected = ()
            playerClicks = []
        drag = None

    # leaves the review of a finished game and stops its analysis; the game is about to change
    def clearReview():
        nonlocal reviewPly, reviewGs, analysis
        if analysis is not None and analysis['task'] is not None:
            analysis['task'].cancel()
        reviewPly = None
        reviewGs = None
        analysis = None

    # shows the position after the first ply moves (the live or final position leaves the review)
    # works during the game too (looking back): the game goes on underneath, and any new move returns to it
    def reviewTo(ply):
        nonlocal reviewPly, reviewGs, reviewScroll, moveLogScroll, squareSelected, playerClicks
        ply = max(0, min(ply, len(gs.moveLog)))
        reviewScroll = True
        clearAnnotations()  # another position is shown
        squareSelected = ()  # nothing stays picked up while another position is shown
        playerClicks = []
        if ply == len(gs.moveLog):
            reviewPly = None
            reviewGs = None
            moveLogScroll = 0  # back to the latest moves
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

    # startSound: the player started this game (New game, Switch sides, Restart, a mode change, a room...), so it
    # plays 'game-start'; not online without a room, where there is no game
    def resetGame(startSound=False):
        nonlocal gs, validMoves, squareSelected, playerClicks, moveMade, animate, gameOver, moveUndone
        nonlocal positionHistory, gameResult, hintMove, hintState, pendingPrompt, moveLogScroll, resultCardHidden
        nonlocal playerWhiteHuman, playerBlackHuman, timeControl, clocks, clockHistory, lastClockTick
        nonlocal gameSaved, savedGameId, gameLoaded, ratingReported, boardFlipped, drag, kingFlash, premove
        nonlocal endSoundPlayed, lowTimeWarned
        clearReview()
        clearAnnotations()
        endSoundPlayed = False
        lowTimeWarned = set()
        drag = None
        kingFlash = None
        premove = None
        boardFlipped = False  # each game starts the usual way round
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
        if startSound and not (currentModeIndex == 2 and not networkConnected):
            playSound('game-start')

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
        resetGame(startSound=True)

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
    # a piece the player is dragging stays in hand (picked up for a premove, it can be dropped as a move once the
    # opponent has moved); the frame's canDrag check lets go of it if it was captured
    def playMove(move, sound=True):
        nonlocal validMoves, hintMove, moveLogScroll, kingFlash
        lookedBack = reviewPly is not None
        clearReview()  # also returns from looking back
        clearAnnotations()
        kingFlash = None
        chargeClock()
        mover = move.pieceMoved[0]
        validMoves = gs.makeMoveWithSan(move, validMoves)
        if timeControl is not None:
            clocks[mover] += timeControl[1] * 1000
        del clockHistory[len(gs.moveLog):]
        clockHistory.append(dict(clocks))
        updatePositionHistory(gs, positionHistory)
        hintMove = None
        if lookedBack or moveLogScroll <= 0:
            moveLogScroll = 0  # the newest moves stay in view (and the list returns there after looking back)
        elif len(gs.moveLog) % 2 == 1:
            moveLogScroll += 1  # a new row: the rows the player scrolled back to stay where they are
        if sound:
            playSound(moveSoundName(move))

    # undo plies and restore everything tied to them
    def takeBack(plies):
        nonlocal moveMade, animate, gameOver, moveUndone, squareSelected, playerClicks
        nonlocal gameResult, hintMove, hintState, clocks, lastClockTick, gameSaved, resultCardHidden, drag, kingFlash
        nonlocal premove
        clearReview()
        clearAnnotations()
        drag = None
        kingFlash = None
        premove = None  # it was chosen for a position that's gone
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

    # a quick chat message (an index into QUICK_CHAT), shown by our own strip too
    def sendChat(index):
        nonlocal lastChatSent
        lastChatSent = p.time.get_ticks()
        sendOnline({'type': 'chat', 'id': index})
        chatBubbles[myColor()] = (QUICK_CHAT[index], lastChatSent)

    # Copy link: the host's invite link goes on the clipboard (on desktop it points at the public site)
    def copyInviteLink():
        nonlocal copyPending
        copyPending = None
        copied = browser.copyText(inviteUrl(browser.siteUrl(), roomCode))
        if copied is None:  # the browser answers later (copyResult, polled each frame)
            copyPending = (p.time.get_ticks(), roomCode)
        else:
            showCopyResult(copied, roomCode)

    def showCopyResult(copied, code):
        if copied:
            showStatus("Invite link copied: send it to your friend")
        else:
            showStatus("Couldn't copy the link: share the room code %s" % code, 6000)

    def newOnlineGameId():
        return "".join(random.choices(string.ascii_letters + string.digits, k=12))

    def startOnlineGame():  # a new game in the same room, keeping the time control
        nonlocal onlineGame, onlineVersion, onlineGameId, timeControl, clocks, clockHistory
        keptTimeControl = timeControl
        resetGame(startSound=True)
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
        nonlocal opponentInfo, opponentSeen, caughtUp, chatOpen, joinId, joinedAt, connectedAt
        multiplayerRole = role
        opponentInfo = None
        opponentSeen = None
        caughtUp = False
        chatOpen = False
        chatBubbles.clear()  # they belonged to the last room
        net.set_topic(roomCode)
        print(f"DEBUG: I am {role.upper()}. Full Network Topic: [{net.topic}]")
        networkConnected = True
        resetGame(startSound=True)
        onlineGame = 0
        onlineVersion = 0
        onlineGameId = newOnlineGameId()  # replaced by the opponent's when we catch up with their game
        lastStateHeard = p.time.get_ticks()
        net.save_session(roomCode, role)
        savedSession = {'room': roomCode, 'role': role}
        # the opponent answers with the current game, so a rejoining player catches up; it comes back to us after
        # the room's history (joinedAt)
        joinId, joinedAt, connectedAt = newOnlineGameId(), None, p.time.get_ticks()
        sendOnline({'type': 'sync_request', 'join': joinId})

    # rebuilds the game from a newer state: undo back to the common moves, then play the rest
    def adoptState(state):
        nonlocal onlineGame, onlineVersion, onlineGameId, timeControl, clocks, gameResult, moveMade, animate
        nonlocal lastClockTick, pendingPrompt, squareSelected, playerClicks, caughtUp
        codes = str(state.get('moves') or "").split()
        newGame = state['game'] != onlineGame
        if newGame:
            # the opponent started the next game; catching up after joining isn't a start (joining already was one)
            resetGame(startSound=not codes and caughtUp)
        caughtUp = True
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
            'undo': not online or networkConnected,
            'save': len(gs.moveLog) > 0,
            'load': not online,
            'join': bool(roomCode),
            'chat': chatReady(p.time.get_ticks(), lastChatSent),
            'analyze': analysis is None and len(gs.moveLog) > 0,
            'first': shownPly() > 0,
            'prev': shownPly() > 0,
            'next': shownPly() < len(gs.moveLog),
            'last': shownPly() < len(gs.moveLog),
        }

    def shownPly():  # number of moves of the position on the board
        return len(gs.moveLog) if reviewPly is None else reviewPly

    def reasonDisabled(name):
        return disabledReason(name, gameOver=gameOver, online=currentModeIndex == 2, connected=networkConnected,
                              humanTurn=humanTurn, hintsLeft=hints.remaining(), hintBusy=hintState is not None,
                              prompt=pendingPrompt is not None,
                              analysis=None if analysis is None else 'done' if analysis['done'] else 'running',
                              moves=len(gs.moveLog), atStart=shownPly() == 0, atEnd=shownPly() == len(gs.moveLog),
                              roomCode=roomCode, chatWait=not chatReady(p.time.get_ticks(), lastChatSent))

    # what the pointer is over, topmost first: (id, tooltip text or None, clickable)
    # the id restarts the tooltip's delay when it changes; clickable gives the hand cursor
    def pointerTarget(pos, layout, states):
        if drag is not None and drag['active']:  # a hand holds the dragged piece, wherever it is
            return 'drag', None, True
        if thumbGrab is not None or (listPress is not None and listPress['active']):
            return 'scrolling', None, True  # and the scrolled list
        pos = windowPos(pos)  # in an open window's own coordinates
        if accountView:  # an open window takes all the pointing
            if accountThumb is not None or (accountPress is not None and accountPress['active']):
                return 'scrolling', None, True
            busy = accountBusy()
            for name, rect in reversed(list(accountRects().items())):  # later rects lie on top (Show on its field)
                if name not in ACCOUNT_AREAS and rect.collidepoint(pos):
                    if name.startswith('field:'):
                        return 'account:' + name, None, 'ibeam' if not busy else False
                    if name.startswith('row:') and accountView != 'games':
                        return None, None, False  # the leaderboard's rows only show
                    return 'account:' + name, None, not busy or name == 'close'
            if accountView == 'games' and scrollbarPart(accountListGeometry(), pos):
                return 'account:scrollbar', None, True
            return None, None, False
        if helpPage is not None:
            rects = helpLayout()
            for name, enabled in (('prev', helpPage > 0), ('close', True), ('next', helpPage < len(HELP_PAGES) - 1)):
                if rects[name].collidepoint(pos):
                    return 'help:' + name, None, enabled
            return None, None, False
        if settingsTab:
            return settingsPointer(settingsTab, pos)
        if openDropdown in layout:  # and so does an open dropdown (a click elsewhere only closes it)
            for i, optRect in enumerate(dropdownOptionRects(layout[openDropdown], len(dropdownLabels(openDropdown)))):
                if optRect.collidepoint(pos):
                    return 'option:%d' % i, None, True
            return None, None, False
        if menuOpen and 'menu' in layout:  # like a dropdown; disabled items say why
            for name, rect in menuItemRects(layout['menu']).items():
                if rect.collidepoint(pos):
                    if states.get(name, True):
                        return 'menu:' + name, tooltipText(name), True
                    return 'menu:' + name, reasonDisabled(name), False
            return ('menu', None, True) if layout['menu'].collidepoint(pos) else (None, None, False)
        if chatOpen and 'chat' in layout:  # and the quick chat's list
            for index, rect in chatItemRects(layout['chat']).items():
                if rect.collidepoint(pos):
                    return 'chat:%d' % index, None, True
            return ('chat', None, True) if layout['chat'].collidepoint(pos) else (None, None, False)
        if pendingPrompt:
            promptBox, acceptRect, declineRect = promptRects()
            for name, rect in (('yes', acceptRect), ('no', declineRect)):
                if rect.collidepoint(pos):
                    return 'prompt:' + name, None, True
            if promptBox.collidepoint(pos):  # nothing under the prompt can be clicked
                return None, None, False
        if gameOver and reviewPly is None and not resultCardHidden:
            rects = resultCardLayout(outcome[0], resultButtons())[2]
            for name in resultButtons():
                if rects[name].collidepoint(pos):
                    return 'result:' + name, None, True
        for name, rect in layout.items():
            if rect.collidepoint(pos):
                if name == 'roomInfo':
                    return None, None, False
                if name == 'room':  # a text field: the I-beam, and its tooltip
                    return name, tooltipText(name), 'ibeam'
                if states.get(name, True):
                    return name, tooltipText(name, multiplayerMode and networkConnected, account.signedIn), True
                return name, reasonDisabled(name), False
        if not onBoard(pos):  # the moves in the log show their position, during the game too
            if scrollbarPart(moveList, pos):
                return 'scrollbar', None, True
            ply = moveListPly(moveList, pos)
            if ply is not None:
                return 'ply:%d' % ply, None, True
        if onBoard(pos) and not gameOver and reviewPly is not None:
            return 'lookBack', None, True  # looking back: a click returns to the game
        if onBoard(pos) and not gameOver and reviewPly is None and (currentModeIndex != 2 or networkConnected):
            row, col = boardSquare(pos, flip_board)
            if humanTurn:
                # the player's own pieces that can move, and where the selected one can go
                movable = any(move.startRow == row and move.startCol == col for move in validMoves)
                target = ownPieceSelected(gs, squareSelected) and any(
                    (move.startRow, move.startCol) == squareSelected and move.endRow == row and move.endCol == col
                    for move in validMoves)
            elif premoveTurn():  # the same for a premove, and the premoved piece (a click cancels it)
                moves = premoveCandidates()
                movable = (any(move.startRow == row and move.startCol == col for move in moves)
                           or (premove is not None and premove[0] == (row, col)))
                target = squareSelected != () and any(
                    (move.startRow, move.startCol) == squareSelected and move.endRow == row and move.endCol == col
                    for move in moves)
            else:
                movable = target = False
            if movable or target:
                return 'square:%d%d' % (row, col), None, True
        return None, None, False

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
        nonlocal moveMade, moveUndone, clocks, clockHistory, gameResult, gameLoaded, endSoundPlayed
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
        endSoundPlayed = getOutcome(gs, positionHistory, gameResult) is not None  # a finished game ends quietly

    # what a menu item does once it's chosen
    def menuAction(name):
        nonlocal helpPage, settingsTab, boardFlipped
        if name == 'save':
            savePgnFile()
        elif name == 'load':
            message = pgn.requestPgnLoad()
            if message:
                showStatus(message)
        elif name == 'flip':
            boardFlipped = not boardFlipped
        elif name == 'settings':
            settingsTab = lastSettingsTab
        elif name == 'help':
            helpPage = 0

    # --- moving with the mouse: two clicks or a drag, and the right button's marks and arrows

    # the player's move from start to end (the second click, or where a dragged piece was dropped), with the
    # promotion piece asked first; slide: animate it (a dropped piece is already there)
    # returns 'played', 'cancelled' (the promotion picker was closed), 'refused' (it would leave the king in
    # check: says so and flashes the king) or None (the piece can't go there at all)
    # promotion: the piece a promotion becomes without asking (a premove promotes to a queen)
    async def tryMove(start, end, slide=True, promotion=None):
        nonlocal squareSelected, playerClicks, moveMade, animate, kingFlash
        move = Move(start, end, gs.board)
        for candidate in validMoves:
            if move == candidate:
                if candidate.isPawnPromotion:
                    choice = promotion or await pawnPromotionPopup(boardSurface, candidate.pieceMoved[0],
                                                                   candidate.endRow, candidate.endCol, flip_board)
                    if choice is None:  # cancelled: the player picks another move
                        squareSelected = ()
                        playerClicks = []
                        return 'cancelled'
                    candidate.promotionChoice = choice
                playMove(candidate)
                if multiplayerMode and networkConnected:
                    print(f"Main: Sending move {candidate.getCode()}")
                    publishChange('move')
                moveMade = True
                animate = slide
                squareSelected = ()
                playerClicks = []
                return 'played'
        reason = refusalReason(gs, start, end)
        if reason:
            showStatus(reason)
            kingFlash = (gs.whiteKinglocation if gs.whiteToMove else gs.blackKinglocation, p.time.get_ticks())
            return 'refused'
        return None

    # a press on square can pick its piece up: the player's own piece in the live position, on their turn or
    # (for a premove) while the opponent is to move
    def canDrag(square):
        if gameOver or reviewPly is not None or (currentModeIndex == 2 and not networkConnected):
            return False
        color = gs.board[square[0]][square[1]][0]
        if humanTurn:
            return color == ('w' if gs.whiteToMove else 'b')
        return bool(premoveTurn()) and color == myColor()

    # the dragged piece let go at pos: a legal move is played there (no slide), or during the opponent's turn
    # chosen as the premove; otherwise it goes back, still selected
    async def dropPiece(pos):
        nonlocal drag, squareSelected, playerClicks
        start = drag['square']
        drag = None
        if onBoard(pos):
            end = boardSquare(pos, flip_board)
            if end != start:
                if not humanTurn:
                    if premoveTurn() and setPremove(start, end):
                        return
                elif await tryMove(start, end, slide=False) in ('played', 'cancelled'):
                    return
        squareSelected = start
        playerClicks = [start]

    # --- premoves: while the opponent is to move, the player picks their next move; it's played when their turn comes

    # premoves can be chosen now: switched on, the opponent (the computer, or online the other player) to move
    def premoveTurn():
        return bool(settings.get('premoves') and not humanTurn and not gameOver and gameResult is None
                    and reviewPly is None and (currentModeIndex == 0 or (currentModeIndex == 2 and networkConnected)))

    # the moves a premove can be (premoveMoves), worked out once per position
    def premoveCandidates():
        key = (id(gs), len(gs.moveLog), gs.getPositionKey())
        if premoveCache['key'] != key:
            premoveCache['key'] = key
            premoveCache['moves'] = premoveMoves(gs)
        return premoveCache['moves']

    # makes start -> end the premove (replacing any other) when the piece could go there; returns whether it did
    def setPremove(start, end):
        nonlocal premove, squareSelected, playerClicks
        if not any((move.startRow, move.startCol) == start and (move.endRow, move.endCol) == end
                   for move in premoveCandidates()):
            return False
        premove = (start, end)
        squareSelected = ()
        playerClicks = []
        return True

    # a left click on square during the opponent's turn; returns 'set', 'cancelled', 'selected' or None
    def choosePremove(square):
        nonlocal squareSelected, playerClicks
        if premove is not None and premove[0] == square:  # the premoved piece again: cancels it
            cancelPremove()
            return 'cancelled'
        if squareSelected != () and squareSelected != square and setPremove(squareSelected, square):
            return 'set'
        if square != squareSelected and gs.board[square[0]][square[1]][0] == myColor():
            squareSelected = square
            playerClicks = [square]
            return 'selected'
        squareSelected = ()
        playerClicks = []
        return None

    # a premove, or a piece picked up for one, that Esc or the right button would cancel
    def premovePending():
        return premove is not None or (premoveTurn() and squareSelected != ())

    def cancelPremove():
        nonlocal premove, squareSelected, playerClicks
        premove = None
        if not humanTurn:
            squareSelected = ()
            playerClicks = []

    # the right button went down at location; returns True when it was taken (the rest of the click is skipped)
    # it first cancels a drag in progress, then a premove (then draws nothing); on the board it starts a mark or arrow
    def rightPress(location):
        nonlocal rightPressed
        rightPressed = None
        if drag is not None:
            cancelDrag(deselect=drag['active'])
            return True
        if onBoard(location) and premovePending():  # cancels the premove instead of drawing
            cancelPremove()
            return True
        if onBoard(location) and not (gameOver and reviewPly is None and not resultCardHidden):
            rightPressed = (boardSquare(location, flip_board), annotationColor(p.key.get_mods()))
            return True
        return False  # e.g. over the result card: a click like any other

    # released on the square it went down on: a ring there; on another square: an arrow between them
    def rightRelease(location):
        nonlocal rightPressed
        if rightPressed is None:
            return
        start, color = rightPressed
        rightPressed = None
        if not onBoard(location):
            return
        end = boardSquare(location, flip_board)
        if end == start:
            toggleAnnotation(boardRings, start, color)
        else:
            toggleAnnotation(boardArrows, (start, end), color)

    # --- account

    def startRequest(coroutine, onDone=None, onError=None, inWindow=True):
        nonlocal accountMessage
        accountRequests.append((asyncio.ensure_future(coroutine), onDone, onError, inWindow))
        if inWindow:
            accountMessage = "Please wait..."

    def accountBusy():
        return any(entry[3] for entry in accountRequests)

    def setAccountMessage(text, tone='error'):
        nonlocal accountMessage, accountTone
        accountMessage, accountTone = text, tone

    def openAccountView(view):
        nonlocal accountView, accountFocus, accountList, accountScroll, accountShowPassword, accountPress, accountThumb
        accountView = view
        setAccountMessage("")
        accountList = []
        accountScroll = 0
        accountPress = accountThumb = None
        accountShowPassword = False
        if view in ACCOUNT_FORMS:
            accountFocus = accountFieldNames(view)[0]
            if view == 'signin' and not accountFields['login'].value:
                accountFields['login'].setValue(accountFields['email'].value)  # e.g. right after registering
            if view == 'forgot' and not accountFields['email'].value and validEmail(accountFields['login'].value):
                accountFields['email'].setValue(accountFields['login'].value.strip())  # the email they signed in with
        elif view == 'profile':
            startRequest(account.loadStats())
        elif view == 'games':
            startRequest(account.listGames(), onDone=showAccountList)
        elif view == 'leaderboard':
            startRequest(account.leaderboard(), onDone=showAccountList)

    def showAccountList(rows):
        nonlocal accountList
        accountList = rows

    def accountListGeometry():
        return accountListLayout(accountView, len(accountList), accountScroll)

    # the window's layout as drawn (the profile's height follows its rows of results)
    def accountRects():
        return accountLayout(accountView, accountRowCount(accountView, account, accountList), accountScroll)

    # the open window's box, in the board-sized frame the windows are laid out in; None while none is open
    def windowBox():
        if accountView:
            return accountRects()['box']
        if helpPage is not None:
            return helpLayout()['box']
        if settingsTab:
            return SETTINGS_BOX
        return None

    # a canvas point in the open window's own coordinates (portrait shows the windows scaled up); else unchanged
    def windowPos(pos):
        box = windowBox()
        return pos if box is None else toWindow(pos, box)

    # the text field keys and pastes go to, if any: the focused account field, or the room box
    def focusedField():
        if accountView in ACCOUNT_FORMS:
            return None if accountBusy() else accountFields[accountFocus]
        if accountView or helpPage is not None or settingsTab:
            return None
        if inputBoxActive and currentModeIndex == 2 and not networkConnected:
            return roomField
        return None

    def submitAccountForm():
        password = accountFields['password'].value
        if accountView == 'signin':
            startRequest(account.signIn(accountFields['login'].value.strip(), password), onDone=lambda _: signedIn())
        elif accountView == 'register':
            startRequest(account.register(accountFields['email'].value.strip(), password,
                                          accountFields['username'].value.strip()), onDone=registered)
        elif accountView == 'forgot':
            email = accountFields['email'].value.strip()
            if not validEmail(email):
                setAccountMessage("That doesn't look like an email address")
                return
            startRequest(account.recover(email, browser.siteUrl()),
                         onDone=lambda _: setAccountMessage(RESET_LINK_SENT, 'success'))
        elif accountView == 'newPassword':
            if len(password.strip()) < MIN_PASSWORD_LENGTH:
                setAccountMessage("Passwords need at least %d characters" % MIN_PASSWORD_LENGTH)
            elif resetLink is None:
                setAccountMessage("This reset link has expired, ask for a new one")
            else:
                startRequest(account.setPassword(resetLink['token'], password, resetLink['refresh']),
                             onDone=lambda _: passwordSaved())

    def signedIn():
        accountFields['password'].setValue("")
        openAccountView('profile')
        showStatus("Signed in as " + account.username)

    def registered(isSignedIn):
        accountFields['password'].setValue("")
        if isSignedIn:
            openAccountView('profile')
            showStatus("Welcome, " + account.username)
        else:
            openAccountView('signin')
            setAccountMessage("Check your email to confirm the account, then sign in", 'success')

    # the new password from a reset link is saved: the link's sign-in is kept
    def passwordSaved():
        nonlocal resetLink
        resetLink = None
        accountFields['password'].setValue("")
        if account.signedIn:
            openAccountView('profile')
            showStatus("Password changed. Signed in as " + account.username)
        else:
            openAccountView('signin')
            setAccountMessage("Password changed. Sign in with the new password", 'success')

    def openSavedGame(row):
        nonlocal accountView
        if currentModeIndex == 2:
            setAccountMessage("Leave online play to open a saved game")
            return

        def opened(text):
            nonlocal accountView
            accountView = None
            loadPgnText(text)
        startRequest(account.loadGame(row['id']), onDone=opened)

    def handleAccountClick(location):
        nonlocal accountView, accountFocus, accountShowPassword, accountScroll, accountPress, accountThumb
        rects = accountRects()
        clicked = None
        for name, rect in rects.items():
            if name not in ACCOUNT_AREAS and rect.collidepoint(location):
                clicked = name
        if accountBusy() and clicked != 'close':
            return
        if accountView == 'games' and 'list' in rects and rects['list'].collidepoint(location):
            # the saved games: the scrollbar, or a press that opens a game when let go (a drag scrolls)
            listLayout = accountListGeometry()
            part = scrollbarPart(listLayout, location)
            if part == 'thumb':
                accountThumb = location[1] - listLayout['thumb'].y
            elif part:
                accountScroll = listLayout['scroll'] + (-1 if part == 'before' else 1) * listLayout['visible']
            else:
                accountPress = {'pos': location, 'scroll': listLayout['scroll'], 'active': False}
            return
        if clicked is None:
            return
        if clicked.startswith('field:'):
            accountFocus = clicked[len('field:'):]
            placeCaret(accountFields[accountFocus], rects[clicked], location[0], accountShowPassword)
        elif clicked == 'toggle:password':
            accountShowPassword = not accountShowPassword
        elif clicked == 'submit':
            submitAccountForm()
        elif clicked == 'switch':
            openAccountView({'signin': 'register', 'register': 'signin', 'forgot': 'signin',
                             'newPassword': 'forgot'}[accountView])
        elif clicked in ('games', 'leaderboard', 'forgot'):
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
        nonlocal accountView, accountFocus, accountScroll
        if e.key == p.K_ESCAPE:
            accountView = None
            return
        if accountView == 'games':  # the keys scroll the saved games
            steps = {p.K_UP: -1, p.K_DOWN: 1, p.K_PAGEUP: -ACCOUNT_LIST_ROWS['games'],
                     p.K_PAGEDOWN: ACCOUNT_LIST_ROWS['games'], p.K_HOME: -len(accountList), p.K_END: len(accountList)}
            if e.key in steps:
                accountScroll = accountListGeometry()['scroll'] + steps[e.key]
            return
        if accountView not in ACCOUNT_FORMS or accountBusy():
            return
        fields = accountFieldNames(accountView)
        if e.key == p.K_TAB:  # Shift+Tab goes back
            step = -1 if getattr(e, 'mod', 0) & p.KMOD_SHIFT else 1
            accountFocus = fields[(fields.index(accountFocus) + step) % len(fields)]
            accountFields[accountFocus].end()
        elif e.key in (p.K_RETURN, p.K_KP_ENTER):
            submitAccountForm()
        else:
            before = accountFields[accountFocus].value
            accountFields[accountFocus].handleKey(e, browser.clipboardText)
            if accountFields[accountFocus].value != before and accountTone == 'error':
                setAccountMessage("")  # the error was about what they're now changing

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

    # the page was opened from a password reset email (browser): Supabase put a sign-in for it after the #. The
    # link leaves the address bar at once (kept in resetLink), so its tokens can't be copied or shown from there;
    # so does a new account's confirmation link (it signs in the same way)
    hashText = browser.locationHash()
    linkInfo = resetLinkFromHash(hashText)
    if linkInfo or hashHasSignIn(hashText):
        browser.clearLocationHash()
    if linkInfo and 'token' in linkInfo:
        resetLink = linkInfo
        openAccountView('newPassword')
    elif linkInfo:  # an expired or used link
        openAccountView('signin')
        setAccountMessage(linkInfo['error'])

    # the page was opened from an invite link (browser): online setup with the room filled in, and a Join prompt;
    # the link's ?room= leaves the address bar, so a reload doesn't ask again
    invited = browser.queryParam('room')
    if invited is not None:
        browser.removeQueryParam('room')
        invitedCode = roomCodeFromText(invited)
        if invitedCode:
            currentModeIndex = 2
            multiplayerMode = True
            resetGame()
            roomCode = invitedRoom = invitedCode
            pendingPrompt = {'kind': 'joinInvite', 'text': "Join room %s as Black?" % invitedCode, 'yes': "Join",
                             'no': "Cancel", 'room': invitedCode}

    # the first visit opens How to play, but not over a password reset (skipped until a later visit) or an invite
    # link's Join prompt (it waits until that is answered); closing it in any way marks it seen
    firstVisitHelp = not settings.get('seenHelp') and not linkInfo
    helpWasOpen = False

    while running:
        if helpPage is not None:  # opened by hand while the first visit's waited: it doesn't open again
            firstVisitHelp = False
        if firstVisitHelp and not (pendingPrompt and pendingPrompt['kind'] == 'joinInvite') and not accountView:
            firstVisitHelp = False
            helpPage = 0
        if helpWasOpen and helpPage is None:
            settings.put('seenHelp', True)
        helpWasOpen = helpPage is not None

        # browser: the window turned (portrait <-> landscape), so the game lays itself out again for its new shape;
        # the game goes on, and only what was held or open on the old layout lets go (a turn within portrait keeps
        # the canvas: the page fits it to the window)
        if p.time.get_ticks() - lastLayoutCheck >= LAYOUT_CHECK_MS:
            lastLayoutCheck = p.time.get_ticks()
            kind, height = layoutFor(browser.viewportSize())
            if kind != LAYOUT.kind:
                setLayout(kind, height)
                screen = openWindow(LAYOUT.size)
                refitCanvas()
                boardSurface = screen.subsurface(LAYOUT.board)
                drag = listPress = thumbGrab = accountPress = accountThumb = openDropdown = rightPressed = None
                graphHeld = menuOpen = chatOpen = False

        if multiplayerMode and networkConnected:
            now = p.time.get_ticks()
            opponentRole = 'client' if multiplayerRole == 'host' else 'host'
            incoming = net.get_messages()
            if joinedAt is None:  # our sync_request came back: everything before it was the room's history
                for msg in incoming:
                    if (msg.get('sender') == myPlayerId and msg.get('join') == joinId
                            and isinstance(msg.get('_time'), (int, float))):
                        joinedAt = msg['_time']
                if joinedAt is None and now - connectedAt > JOIN_ECHO_MS:
                    joinedAt = net.server_time
            messages = [msg for msg in incoming if msg.get('sender') != myPlayerId]
            for msg in messages:
                print(f"Main: Received message type='{msg.get('type')}' from {msg.get('role')} sender={msg.get('sender', '???')}")
                if msg.get('role') == opponentRole and msg.get('_time') is not None:
                    opponentSeen = max(opponentSeen or 0, msg['_time'])  # server time of their latest message
                if msg.get('role') == opponentRole:
                    opponentInfo = onlinePlayerInfo(msg.get('player')) or opponentInfo

            # game states: a replay after joining can deliver many, so only the newest one is used
            newest = None
            for msg in messages:
                if (msg.get('type') == 'state' and isinstance(msg.get('game'), int)
                        and isinstance(msg.get('version'), int) and wellFormedState(msg)):
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
                if mtype == 'chat':  # any time in the room, but only fresh ones from the opponent
                    index = incomingChat(msg, opponentRole, net.server_time, joinedAt)
                    if index is not None:
                        chatBubbles['b' if multiplayerRole == 'host' else 'w'] = (QUICK_CHAT[index], now)
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
            # the room's history has been heard: a state adopted from now on is the game going on (a new game
            # the opponent starts plays its sound)
            if joinedAt is not None:
                caughtUp = True

        humanTurn = (gs.whiteToMove and playerWhiteHuman) or (
            not gs.whiteToMove and playerBlackHuman)
        if multiplayerMode and networkConnected:
            humanTurn = (gs.whiteToMove and multiplayerRole == 'host') or (not gs.whiteToMove and multiplayerRole == 'client')
        # Black at the bottom for the online guest, and when playing Black against the AI
        flip_board = (multiplayerMode and networkConnected and multiplayerRole == 'client') or \
            (currentModeIndex == 0 and playerBlackHuman and not playerWhiteHuman)
        flip_board = flip_board != boardFlipped  # Flip board (F) turns it around from there
        canRejoin = currentModeIndex == 2 and not networkConnected and savedSession is not None
        guest = currentModeIndex == 2 and networkConnected and multiplayerRole == 'client'  # no Copy link

        # "Your move": the opponent moved while the player is away (a hidden tab, or another window in front);
        # the title says so until they're back or the turn passes
        away = browser.pageHidden() if browser.inBrowser() else not windowFocused
        playable = humanTurn and not (currentModeIndex == 2 and not networkConnected)
        # a premove answers for the player later in this frame; if it is dropped, the next frame calls them
        premoveDue = premove is not None and playable
        if (not premoveDue and turnArrived(currentModeIndex, playable, movesSeen, len(gs.moveLog), gameOver)
                and away and not yourMoveAlert):
            yourMoveAlert = True
            browser.setTitle(YOUR_MOVE_TITLE)
            playSound('notify')
        elif yourMoveAlert and (not away or not humanTurn or gameOver):
            yourMoveAlert = False
            browser.setTitle(GAME_TITLE)
        if not premoveDue:
            movesSeen = len(gs.moveLog)

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

        # a drag ends when the position can't be played any more (the game ended, a window opened, ...)
        if drag is not None and (not canDrag(drag['square']) or menuOpen or chatOpen or openDropdown or accountView
                                 or helpPage is not None or settingsTab):
            drag = None
        # and an open dropdown, the menu or the chat list closes when a window opens (H or F1 opens How to play)
        if accountView or helpPage is not None or settingsTab:
            openDropdown, menuOpen, chatOpen = None, False, False
        if kingFlash is not None and p.time.get_ticks() - kingFlash[1] > KING_FLASH_MS:
            kingFlash = None

        if roomField.value != roomCode:  # the room changed elsewhere (Host, Rejoin, another mode)
            roomField.setValue(roomCode)
        if copyPending is not None:  # the browser's answer to Copy link (no answer in time counts as a failure)
            copied = browser.copyResult()
            if copied is not None or p.time.get_ticks() - copyPending[0] > COPY_WAIT_MS:
                showCopyResult(bool(copied), copyPending[1])
                copyPending = None
        # in the browser a paste (Ctrl+V) arrives as the page's paste event; desktop reads the clipboard in handleKey
        pasted = browser.takePastedText()
        if pasted and focusedField() is not None:
            focusedField().paste(pasted)
            roomCode = roomField.value

        clickedNow = False  # a click in this frame
        for e in p.event.get():
            if e.type in (p.MOUSEBUTTONDOWN, p.MOUSEBUTTONUP) and e.button == 1:
                MOUSE_HELD[0] = e.type == p.MOUSEBUTTONDOWN  # buttons look pressed while it's held
            if e.type == p.MOUSEBUTTONDOWN:
                tooltipHidden = clickedNow = True  # a click hides the tooltip until the pointer moves to something else
            if e.type == p.QUIT:
                running = False
            elif e.type == WINDOW_FOCUS_LOST:
                windowFocused = False
            elif e.type == WINDOW_FOCUS_GAINED:
                windowFocused = True
            # Mouse Handler
            elif e.type == p.MOUSEWHEEL:
                if accountView:  # the window's list scrolls (wheel up: newer games, at the top)
                    if accountView == 'games':
                        accountScroll = accountListGeometry()['scroll'] - e.y * ACCOUNT_LIST_WHEEL
                elif not onBoard(pointerPos()):
                    moveLogScroll += e.y  # wheel up scrolls back through older moves
            elif e.type == p.MOUSEMOTION:
                pos = p.mouse.get_pos()
                if not getattr(e, 'buttons', (1,))[0]:  # let go where we didn't hear it (outside the window)
                    listPress, thumbGrab, graphHeld = None, None, False
                    accountPress = accountThumb = None
                if accountThumb is not None:  # the saved games, like the move list below (in the window's coordinates)
                    accountScroll = firstRowForThumb(accountListGeometry(), windowPos(pos)[1] - accountThumb)
                elif accountPress is not None:
                    dy = windowPos(pos)[1] - accountPress['pos'][1]
                    if (not accountPress['active']
                            and math.hypot(windowPos(pos)[0] - accountPress['pos'][0], dy) > DRAG_THRESHOLD):
                        accountPress['active'] = True
                    if accountPress['active']:  # the list moves with the pointer: up shows older games
                        accountScroll = accountPress['scroll'] - round(dy / ACCOUNT_ROW_HEIGHT)
                if thumbGrab is not None:
                    moveLogScroll = scrollForThumb(moveList, pos[1] - thumbGrab)
                elif listPress is not None:
                    dy = pos[1] - listPress['pos'][1]
                    if not listPress['active'] and math.hypot(pos[0] - listPress['pos'][0], dy) > DRAG_THRESHOLD:
                        listPress['active'] = True  # a drag: it scrolls, and the release selects nothing
                    if listPress['active']:
                        moveLogScroll = scrollForListDrag(listPress['scroll'], dy)
                elif graphHeld:
                    graphRect = panelLayout(currentModeIndex, networkConnected, canRejoin, gameOver,
                                            analysis is not None, guest).get('graph')
                    if graphRect is not None and graphPly(graphRect, len(gs.moveLog), pos[0]) != shownPly():
                        reviewTo(graphPly(graphRect, len(gs.moveLog), pos[0]))
                if drag is not None and not getattr(e, 'buttons', (1,))[0]:
                    # the button was let go where we didn't hear it (outside the window): the piece goes back
                    if drag['active']:
                        squareSelected, playerClicks = drag['square'], [drag['square']]
                    drag = None
                elif drag is not None and not drag['active']:
                    if math.hypot(pos[0] - drag['pressPos'][0], pos[1] - drag['pressPos'][1]) > DRAG_THRESHOLD:
                        drag['active'] = True
                        squareSelected = drag['square']  # picked up again if the press had deselected it
                        playerClicks = [squareSelected]
            elif e.type == p.MOUSEBUTTONUP:
                if e.button == 1 and (accountPress is not None or accountThumb is not None):
                    # a tap on a saved game opens it; a drag only scrolled
                    if accountPress is not None and not accountPress['active'] and accountView == 'games':
                        for rect, index in accountListGeometry()['cells']:
                            if rect.collidepoint(accountPress['pos']) and not accountBusy():
                                openSavedGame(accountList[index])
                    accountPress = accountThumb = None
                if e.button == 1:
                    if listPress is not None and not listPress['active']:
                        # a tap on a move shows the position after it (during the game: looking back)
                        ply = moveListPly(moveList, listPress['pos'])
                        if ply is not None:
                            reviewTo(ply + 1)
                    listPress, thumbGrab, graphHeld = None, None, False
                if e.button == 1 and drag is not None:
                    if drag['active']:
                        await dropPiece(pointerPos())
                    else:
                        drag = None  # a plain click: the press already did everything
                elif e.button == 3:
                    rightRelease(pointerPos())
            elif e.type == p.MOUSEBUTTONDOWN:
                if e.button in (4, 5):  # wheel also fires button events; handled by MOUSEWHEEL
                    continue
                location = pointerPos()
                # the right button: a drag is cancelled, then a premove (rightPress), marks and arrows on the board;
                # elsewhere a click as before
                if e.button == 3 and drag is not None:
                    rightPress(location)
                    continue
                if accountView:  # the account window takes every click while it's open
                    if e.button == 1:
                        handleAccountClick(windowPos(location))
                    continue
                if helpPage is not None:  # and so does the How to play window
                    helpPage = helpClick(helpPage, windowPos(location))
                    continue
                if settingsTab:  # and the Settings window
                    settingsTab = settingsClick(windowPos(location), settingsTab)
                    lastSettingsTab = settingsTab or lastSettingsTab
                    continue
                layout = panelLayout(currentModeIndex, networkConnected, canRejoin, gameOver, analysis is not None, guest)

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
                            resetGame(startSound=True)
                    elif name == 'clock':
                        if chosen != clockIndex:
                            clockIndex = chosen
                            resetGame(startSound=True)
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
                        resetGame(startSound=True)
                    continue

                # an open menu takes the click too: run an item or close it
                if menuOpen:
                    menuOpen = False
                    chosen = None
                    for name, rect in menuItemRects(layout['menu']).items():
                        if rect.collidepoint(location):
                            chosen = name
                    if chosen is None:
                        continue
                    if not controlStates().get(chosen, True):
                        reason = reasonDisabled(chosen)
                        if reason:
                            showStatus(reason)
                        menuOpen = True  # stays open, so another item can be picked
                        continue
                    menuAction(chosen)
                    continue

                # and so does the quick chat's list: send a message or close it
                if chatOpen:
                    chatOpen = False
                    if 'chat' not in layout:
                        continue
                    for index, rect in chatItemRects(layout['chat']).items():
                        if rect.collidepoint(location) and chatReady(p.time.get_ticks(), lastChatSent):
                            sendChat(index)
                    continue

                if e.button == 3 and rightPress(location):
                    continue

                if pendingPrompt:
                    promptBox, acceptRect, declineRect = promptRects()
                    if acceptRect.collidepoint(location) or declineRect.collidepoint(location):
                        accepted = acceptRect.collidepoint(location)
                        prompt, kind = pendingPrompt, pendingPrompt['kind']
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
                        elif kind == 'joinInvite' and accepted:  # opened from an invite link
                            roomCode = prompt['room']
                            connectOnline('client')
                            await asyncio.sleep(0)  # yield so poll task can start
                        continue
                    if promptBox.collidepoint(location):  # the rest of its box hides the moves under it
                        continue

                clicked = None
                for name, rect in layout.items():
                    if rect.collidepoint(location):
                        clicked = name
                inputBoxActive = clicked == 'room'
                if inputBoxActive:
                    placeCaret(roomField, layout['room'], location[0], size=scaled(FIELD_TEXT_SIZE))
                if clicked is not None and not controlStates().get(clicked, True):
                    reason = reasonDisabled(clicked)  # the same reason as its tooltip, for touch screens too
                    if reason:
                        showStatus(reason)
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
                elif clicked == 'menu':
                    menuOpen = True
                elif clicked == 'chat':
                    chatOpen = True
                elif clicked == 'invite':
                    copyInviteLink()
                elif clicked == 'host':
                    print("DEBUG: Host button clicked.")
                    # a new room, unless one was typed in (the invite's room has its host: the friend)
                    if not roomCode or roomCode == invitedRoom:
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
                elif clicked == 'graph':  # shows the position at that point; dragging keeps following
                    graphHeld = e.button == 1
                    reviewTo(graphPly(layout['graph'], len(gs.moveLog), location[0]))
                elif clicked == 'first':
                    reviewTo(0)
                elif clicked == 'prev':
                    reviewTo(shownPly() - 1)
                elif clicked == 'next':
                    reviewTo(shownPly() + 1)
                elif clicked == 'last':
                    reviewTo(len(gs.moveLog))
                elif clicked is None and not onBoard(location):
                    # the move list: the scrollbar, or a press that selects a move on release (or scrolls if dragged)
                    if e.button != 1:
                        continue
                    part = scrollbarPart(moveList, location)
                    if part == 'thumb':
                        thumbGrab = location[1] - moveList['thumb'].y
                    elif part:
                        moveLogScroll = scrollForPage(moveList, part)
                    elif moveList['area'].collidepoint(location):
                        listPress = {'pos': location, 'scroll': moveList['scroll'], 'active': False}

                elif clicked is None:  # board click
                    if e.button == 1:
                        clearAnnotations()  # a left click on the board wipes the marks and arrows
                    if currentModeIndex == 2 and not networkConnected:  # no game until there is a room
                        showStatus("Host or join a room to start a game")
                        continue
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
                                resetGame(startSound=True)
                        elif 'switch' in cardRects and cardRects['switch'].collidepoint(location):
                            sideIndex = 1 if playerWhiteHuman else 0  # "Play as" changes to the other color
                            resetGame(startSound=True)
                        else:
                            resultCardHidden = True
                        continue
                    if reviewPly is not None:  # looking back during the game: a click returns to it, nothing more
                        reviewTo(len(gs.moveLog))
                        continue
                    row, col = boardSquare(location, flip_board)
                    drag = None  # a new press; it may pick a piece up again below
                    if premoveTurn():  # the opponent is to move: the click chooses the premove
                        chosen = choosePremove((row, col))
                        if e.button == 1 and chosen != 'set' and canDrag((row, col)):
                            drag = {'square': (row, col), 'pressPos': location, 'active': False}
                        continue
                    # if user clicked on same square twice
                    if squareSelected == (row, col):
                        squareSelected = ()  # deselect
                        playerClicks = []  # clear player clicks
                    else:
                        squareSelected = (row, col)
                        # append player both clicks (place and destination)
                        playerClicks.append(squareSelected)
                    result = None
                    # after second click (at destination)
                    if len(playerClicks) == 2:
                        if not humanTurn:
                            print("Main: Wait for opponent turn.")
                            squareSelected = ()
                            playerClicks = []
                            continue
                        start = playerClicks[0]
                        result = await tryMove(start, playerClicks[1])
                        if result == 'refused':  # the piece stays selected, to try another square
                            squareSelected = start
                            playerClicks = [start]
                        elif result is None:  # the second click starts a new selection
                            playerClicks = [squareSelected]
                    # pressing on an own piece arms a drag: it starts once the pointer moves with the button held
                    if e.button == 1 and result is None and canDrag((row, col)):
                        drag = {'square': (row, col), 'pressPos': location, 'active': False}

            # Key Handler
            elif e.type == p.KEYDOWN:
                if accountView:
                    handleAccountKey(e)
                    continue
                if helpPage is not None:
                    helpPage = helpKey(helpPage, e.key)
                    continue
                if settingsTab:
                    settingsTab = settingsKey(settingsTab, e.key)
                    lastSettingsTab = settingsTab or lastSettingsTab
                    continue
                if openDropdown and e.key == p.K_ESCAPE:
                    openDropdown = None
                    continue
                if drag is not None and e.key == p.K_ESCAPE:  # Esc puts a dragged piece back
                    cancelDrag(deselect=drag['active'])
                    continue
                if menuOpen or chatOpen:  # any key closes the menu or the chat list; Esc does nothing else
                    menuOpen = chatOpen = False
                    if e.key == p.K_ESCAPE:
                        continue
                if e.key == p.K_ESCAPE and premovePending():
                    cancelPremove()
                    continue
                if focusedField() is roomField:
                    if e.key in (p.K_RETURN, p.K_KP_ENTER, p.K_ESCAPE):
                        inputBoxActive = False
                    else:  # room codes become part of the ntfy topic name, which allows only ROOM_CODE_CHARACTERS
                        roomField.handleKey(e, browser.clipboardText)
                        roomCode = roomField.value
                    continue

                # the arrow keys step through the moves: during the game to look back (End returns), and after it
                if e.key in (p.K_LEFT, p.K_RIGHT, p.K_HOME, p.K_END, p.K_UP, p.K_DOWN):
                    if e.key in (p.K_LEFT, p.K_UP):
                        reviewTo(shownPly() - 1)
                    elif e.key in (p.K_RIGHT, p.K_DOWN):
                        reviewTo(shownPly() + 1)
                    elif e.key == p.K_HOME:
                        reviewTo(0)
                    else:
                        reviewTo(len(gs.moveLog))
                    continue

                if e.key in (p.K_h, p.K_F1):  # How to play (it closes an open dropdown, as a click would)
                    helpPage, openDropdown = 0, None
                    continue
                if e.key == p.K_f:  # Flip board, as in the menu
                    menuAction('flip')
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
            # a warning tick when a clock of a player on this device goes under 10 s
            if currentModeIndex == 2:
                humanColors = myColor()
            else:
                humanColors = ('w' if playerWhiteHuman else '') + ('b' if playerBlackHuman else '')
            for color in lowTimeSides(clocks, humanColors, lowTimeWarned):
                lowTimeWarned.add(color)
                playSound('low-time')

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

        # the premove: once the opponent's move is in (and shown), it's played if it's still legal, else dropped
        if premove is not None and humanTurn and not moveMade and not (currentModeIndex == 2 and not networkConnected):
            chosen, premove = premove, None
            if settings.get('premoves') and getOutcome(gs, positionHistory, gameResult) is None:
                if reviewPly is not None:
                    reviewTo(len(gs.moveLog))  # back to the game first
                if resolvePremove(chosen, validMoves) is not None:
                    await tryMove(chosen[0], chosen[1], promotion='Q')
                else:
                    showStatus(PREMOVE_DROPPED)

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
                await animateMove(gs.moveLog[-1], boardSurface, gs.board, clock, flip_board)
            validMoves = gs.getValidMoves()
            moveMade = False
            animate = False
            moveUndone = False

        outcome = getOutcome(gs, positionHistory, gameResult)
        gameOver = outcome is not None
        if gameOver and pendingPrompt and pendingPrompt['kind'] in ('draw', 'localDraw', 'resign'):
            pendingPrompt = None  # offers and resigning end with the game; an undo or leaving the room still can
        if gameOver or not settings.get('premoves'):
            premove = None
        if gameOver and not wasGameOver and reviewPly is not None:
            reviewTo(len(gs.moveLog))  # the game ended while looking back (e.g. on time): show the result
        # the end of the game is heard once; not for a finished game that was loaded, or an online game that was
        # already over when we joined
        if gameOver and not endSoundPlayed:
            endSoundPlayed = True
            if currentModeIndex != 2 or liveGameId == onlineGameId:
                playSound('game-end')
        wasGameOver = gameOver

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
                    setAccountMessage(message)
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

        # arrows: the hint, and after the game the better move instead of an analysed mistake
        marks = moveMarks(analysis, gs.moveLog) if analysis else {}
        arrows = []
        # a hint is for the game in progress (it may end by resigning), in the live position
        if hintMove is not None and not gameOver and reviewPly is None:
            arrows.append(((hintMove.startRow, hintMove.startCol), (hintMove.endRow, hintMove.endCol)))
        if gameOver and shownPly() - 1 in marks and analysis['best'][shownPly() - 1]:
            arrows.append(codeSquares(analysis['best'][shownPly() - 1]))
        # and the player's own (right button), in their colors
        arrows += [(start, end, ANNOTATION_COLORS[color]) for (start, end), color in boardArrows.items()]
        rings = [(square, ANNOTATION_COLORS[color]) for square, color in boardRings.items()]
        # the board shows the reviewed position while looking back (during the game, or after it)
        shownGs = reviewGs if reviewGs is not None else gs
        dragging = drag is not None and drag['active']
        lookingBack = reviewGs is not None and not gameOver
        if reviewGs is not None:
            drawGameState(boardSurface, reviewGs, [], (), flip_board, arrows, rings=rings)
            if lookingBack:
                drawLookBackBanner(boardSurface, lookBackText(gs.moveLog, reviewPly))
        else:
            # the premove's squares, or the piece picked up for one and where it could go
            premoveShown = {'squares': list(premove) if premove else [], 'moves': []}
            if premoveTurn() and squareSelected != ():
                premoveShown['squares'].append(squareSelected)
                premoveShown['moves'] = [move for move in premoveCandidates()
                                         if (move.startRow, move.startCol) == squareSelected]
            drawGameState(boardSurface, gs, validMoves, squareSelected, flip_board, arrows,
                          hidden=drag['square'] if dragging else None, rings=rings,
                          flash=(kingFlash[0], p.time.get_ticks() - kingFlash[1]) if kingFlash else None,
                          premove=premoveShown if premoveShown['squares'] else None)

        # side panel (in portrait everything around the board)
        layout = panelLayout(currentModeIndex, networkConnected, canRejoin, gameOver, analysis is not None, guest)
        for rect in LAYOUT.panelFill:
            p.draw.rect(screen, p.Color(UI['panel']), rect)
        # the player strips, a slot for status messages, and after the game the review info (see panelAreas)
        areas = panelAreas(min(rect.y for rect in layout.values()), gameOver)
        infoRect, statusRect = areas['info'], areas['status']
        stripY = areas['bottomStrip'].y
        # the move list; after the game and while looking back the shown move is highlighted (and kept in view)
        highlighted = shownPly() - 1 if gameOver or lookingBack else None
        moveList = moveListLayout(len(gs.moveLog), areas['list'][0], areas['list'][1], moveLogScroll,
                                  highlighted if reviewScroll else None)
        moveLogScroll = moveList['scroll']
        figurines = settingValue('figurines')
        drawMoveList(screen, moveList, gs.moveLog, highlighted, marks, thumbGrab is not None, figurines)
        reviewScroll = False
        if gameOver:  # the shown position, its evaluation and the analysis, and the evaluation graph
            drawReviewInfo(screen, infoRect, gs.moveLog, shownPly(), analysis, marks, shownGs.checkmate, outcome[0],
                           figurines)
            if 'graph' in layout:
                drawEvalGraph(screen, layout['graph'], analysis['evals'], len(gs.moveLog), marks, shownPly(),
                              analysis['done'])
        taken = capturedPieces(shownGs)
        balance = materialBalance(shownGs.board)
        # during the game the clocks keep running while looking back; after it they show the reviewed move's times
        sideToMove = 'w' if (shownGs if gameOver else gs).whiteToMove else 'b'
        shownClocks = (clockHistory[reviewPly] if gameOver and reviewPly is not None and reviewPly < len(clockHistory)
                       else clocks)
        notes = {}  # a note after a player's name
        if aiSearch is not None:
            notes['w' if gs.whiteToMove else 'b'] = "thinking" + "." * (1 + p.time.get_ticks() // 400 % 3)
        if multiplayerMode and networkConnected:
            notes['b' if myColor() == 'w' else 'w'] = presenceStatus(multiplayerRole, opponentSeen, net.server_time,
                                                                     net.last_status)[2]
        stripSpans = {}  # color -> the strip's free span after the name (portrait's chat bubbles go there)
        for color, y in ((('w' if flip_board else 'b'), areas['topStrip'].y), (('b' if flip_board else 'w'), stripY)):
            stripSpans[color] = drawPlayerStrip(screen, y, color, playerName(color), taken[color],
                                                balance if color == 'w' else -balance,
                                                shownClocks[color] if timeControl else None,
                                                clockRunning() and sideToMove == color, notes.get(color))

        mouse_pos = pointerPos()
        states = controlStates()
        labels = {
            'mode': "Mode: " + MODE_OPTIONS[currentModeIndex],
            'level': "AI: " + LEVEL_OPTIONS[chessAi.LEVEL],
            'side': "Play as: " + SIDE_OPTIONS[sideIndex],
            'clock': "Clock: " + CLOCK_OPTIONS[clockIndex][0],
            'hint': "Hint (%d left)" % hints.remaining(),
            'host': "Host (White)",
            'join': "Join (Black)",
            'menu': "",  # drawn as three lines
            'resign': "Resign",
            'draw': "Offer Draw",
            'undo': "Undo",
            'restart': "Restart",
            'account': account.username or "Sign in",
            'invite': "Copy link",
            'chat': "Chat",
            'first': "", 'prev': "", 'next': "", 'last': "",  # drawn as arrow icons
        }
        labels['analyze'] = "Analyze game"  # once the analysis starts its graph takes the button's place
        if savedSession:
            labels['rejoin'] = "Rejoin %s as %s" % (savedSession['room'], "White" if savedSession['role'] == 'host' else "Black")
        labelSizes = evenLabelSizes(panelRows(currentModeIndex, networkConnected, canRejoin, gameOver,
                                              analysis is not None, guest), layout, labels)
        # under an open menu, dropdown or window the panel's buttons don't light up: the click goes to the overlay
        chatOpen = chatOpen and 'chat' in layout  # the list goes with its button (leaving the room)
        overlayOpen = menuOpen or chatOpen or openDropdown or accountView or helpPage is not None or settingsTab
        panelMouse = (-1, -1) if overlayOpen or dragging else mouse_pos  # nor under a dragged piece
        for name, rect in layout.items():
            if name == 'room':
                drawTextField(screen, rect, roomField, inputBoxActive and not overlayOpen, placeholder="Type Room ID",
                              radius=BUTTON_RADIUS, size=scaled(FIELD_TEXT_SIZE))
            elif name == 'graph':
                pass  # drawn with the review info above
            elif name == 'roomInfo':
                textObj = get_text_surface(f"Room: {roomCode}", scaled(20), UI['text'], True)
                textLoc = rect.move(rect.width / 2 - textObj.get_width() / 2, 0)
                screen.blit(textObj, textLoc)
                # Connection Indicator (Traffic Light System)
                if "HEALTHY" in net.last_status or "READY" in net.last_status:
                    dot_color = p.Color('green')
                elif "CONNECTING" in net.last_status or "INITIALIZING" in net.last_status or "RETRYING" in net.last_status:
                    dot_color = p.Color('orange')
                else:
                    dot_color = p.Color('red')
                p.draw.circle(screen, dot_color, (textLoc.x + textObj.get_width() + scaled(15),
                                                  textLoc.y + textObj.get_height() / 2), scaled(6))
                # whether the opponent is there (the connection details go to the console)
                presenceText, presenceColor = presenceStatus(multiplayerRole, opponentSeen, net.server_time,
                                                             net.last_status)[:2]
                presenceObj = get_fitting_text(presenceText, rect.width, scaled(15), UI[presenceColor], False)
                screen.blit(presenceObj, (rect.centerx - presenceObj.get_width() / 2, rect.y + scaled(24)))
            else:
                arrow = None
                if name in DROPDOWNS:
                    arrow = 'up' if openDropdown == name else 'down'
                opened = (name == 'menu' and menuOpen) or (name == 'chat' and chatOpen)
                drawButton(screen, rect, labels[name], states.get(name, True), panelMouse, arrow, size=labelSizes[name],
                           color=UI['buttonPressed'] if opened else None)
                if name in ('first', 'prev', 'next', 'last'):
                    drawNavIcon(screen, rect, name)
                elif name == 'menu':
                    drawMenuIcon(screen, rect)

        # quick chat messages by their senders' strips (only in a room; they fade after CHAT_BUBBLE_MS)
        for color, (text, since) in list(chatBubbles.items()):
            if not (multiplayerMode and networkConnected) or p.time.get_ticks() - since >= CHAT_BUBBLE_MS:
                del chatBubbles[color]
                continue
            atTop = color == ('w' if flip_board else 'b')
            statusShown = statusText and p.time.get_ticks() < statusUntil
            # landscape: over the move list, the lower strip's bubble rising over the status slot and the review
            # info above it; portrait: inside the strip, after the name, so neither covers the board
            if LAYOUT.kind == 'portrait':
                drawChatBubble(screen, text, areas['topStrip'].y if atTop else stripY, atTop,
                               p.time.get_ticks() - since, span=stripSpans[color])
            else:
                drawChatBubble(screen, text, areas['topStrip'].y if atTop else stripY, atTop,
                               p.time.get_ticks() - since, 0 if atTop else chatBubbleLift(areas, statusShown, gameOver))

        # the dragged piece follows the pointer, over the board and the panel but under the overlays (in a desktop
        # window's black bars it stays at the picture's edge)
        if dragging:
            drawDraggedPiece(screen, gs.board[drag['square'][0]][drag['square'][1]], p.mouse.get_pos())

        if gameOver and reviewPly is None and not resultCardHidden:
            drawEndGameText(screen, outcome[0], resultButtons(), mouse_pos)

        # overlays: the status message, the Accept / Decline prompt, windows and open dropdown options or menu (on
        # top); a window covers the status slot (in portrait it lies across the middle of a window)
        if statusText and p.time.get_ticks() < statusUntil:
            drawStatus(screen, statusRect, statusText)
        if pendingPrompt:
            panel_rect, acceptBtn, denyBtn = promptRects()
            p.draw.rect(screen, p.Color(UI['strip']), panel_rect, border_radius=WINDOW_RADIUS)
            p.draw.rect(screen, p.Color(UI['windowBorder']), panel_rect, 2, border_radius=WINDOW_RADIUS)
            textObj = get_fitting_text(pendingPrompt['text'], panel_rect.width - 20, scaled(20), UI['text'])
            screen.blit(textObj, (panel_rect.centerx - textObj.get_width() / 2, panel_rect.y + scaled(12)))
            # a confirmation shows its action in red (it can't be taken back); an offer's Accept is green;
            # the way out is a neutral gray
            confirm = pendingPrompt.get('confirm', False)
            drawButton(screen, acceptBtn, pendingPrompt.get('yes', "Accept"), True, mouse_pos,
                       color=UI['confirm'] if confirm else UI['button'], size=LAYOUT.labelSize)
            drawButton(screen, denyBtn, pendingPrompt.get('no', "Decline"), True, mouse_pos, color=UI['neutral'],
                       size=LAYOUT.labelSize)
        # the windows draw in their own coordinates (scaled up in portrait: drawWindow)
        windowMouse = windowPos(mouse_pos)
        if accountView:
            if accountView in ('games', 'leaderboard'):
                accountScroll = accountListGeometry()['scroll']  # the wheel and drags may go past either end
            scrolling = accountThumb is not None or (accountPress is not None and accountPress['active'])
            drawWindow(screen, windowBox(), lambda surface: drawAccountWindow(
                surface, accountView, accountFields, accountFocus, accountMessage, accountBusy(), account, accountList,
                (-1, -1) if scrolling else windowMouse, accountTone, accountScroll, accountShowPassword,
                accountThumb is not None, (resetLink or {}).get('email')))
        if helpPage is not None:
            drawWindow(screen, windowBox(), lambda surface: drawHelpWindow(surface, helpPage, windowMouse))
        if settingsTab:
            drawWindow(screen, windowBox(), lambda surface: drawSettingsWindow(surface, windowMouse, settingsTab))
        if openDropdown in layout:
            options = dropdownLabels(openDropdown)
            current = {'mode': currentModeIndex, 'level': chessAi.LEVEL, 'side': sideIndex,
                       'clock': clockIndex}[openDropdown]
            for i, optRect in enumerate(dropdownOptionRects(layout[openDropdown], len(options))):
                drawButton(screen, optRect, options[i], True, mouse_pos,
                           color=UI['selectedOption'] if i == current else None, size=LAYOUT.labelSize)
                if i == current:
                    drawCheckMark(screen, optRect)
        if menuOpen:
            drawMenu(screen, layout['menu'], states, mouse_pos)
        if chatOpen:
            drawChatList(screen, layout['chat'], mouse_pos)

        # the pointer: a hand over anything clickable, and the tooltip of the control it rests on
        target, tip, clickable = pointerTarget(mouse_pos, layout, states)
        if target != hoverId:
            # a tap arrives and clicks in the same frame: what it clicked keeps its tooltip hidden too
            hoverId, hoverSince, tooltipHidden = target, p.time.get_ticks(), clickedNow
        setCursor('ibeam' if clickable == 'ibeam' else 'hand' if clickable else 'arrow')
        if tip and not tooltipHidden and p.time.get_ticks() - hoverSince >= TOOLTIP_DELAY_MS:
            drawTooltip(screen, tip, mouse_pos)

        clock.tick(MAX_FPS)
        await asyncio.sleep(0) # Essential for WASM performance/UI responsiveness
        p.display.flip()
        await asyncio.sleep(0)


# a color made lighter (amount > 0) or darker (amount < 0)
def shadeColor(color, amount):
    return tuple(max(0, min(255, c + amount)) for c in color[:3])


# color: the button's own color instead of the theme's; it lightens under the mouse and darkens while pressed
# size: the label size (evenLabelSizes); the label still shrinks if it doesn't fit
# textColor: the label's color on a button of its own color (a light one needs dark text)
def drawButton(screen, rect, text, enabled=True, mouse_pos=(-1, -1), arrow=None, color=None, size=None,
               textColor=None):
    hovered = enabled and rect.collidepoint(mouse_pos)
    pressed = hovered and MOUSE_HELD[0]
    if not enabled:
        fill = UI['buttonDisabled']
    elif color is None:
        fill = UI['buttonPressed'] if pressed else UI['buttonHover'] if hovered else UI['button']
    else:
        fill = shadeColor(color, -25) if pressed else shadeColor(color, 30) if hovered else color
    p.draw.rect(screen, p.Color(*fill[:3]), rect, border_radius=BUTTON_RADIUS)
    p.draw.rect(screen, p.Color(*shadeColor(fill, -28)), rect, 1, border_radius=BUTTON_RADIUS)  # a soft edge
    textColor = UI['buttonTextDisabled'] if not enabled else textColor or UI['buttonText']
    drop = 1 if pressed else 0  # the label sinks a little while pressed

    # leave room on the right for the dropdown arrow
    textObj = get_fitting_text(text, buttonTextWidth(rect, arrow), size or BUTTON_LABEL_SIZE, textColor, sans=True)
    textX = rect.x + (rect.width - (24 if arrow else 0)) / 2 - textObj.get_width() / 2
    screen.blit(textObj, (textX, rect.centery - textObj.get_height() / 2 + 1 + drop))

    if arrow:
        center_x = rect.right - 20
        center_y = rect.centery + drop
        arrowColor = p.Color(textColor)
        if arrow == 'up':
            p.draw.polygon(screen, arrowColor, [(center_x - 6, center_y + 4), (center_x + 6, center_y + 4), (center_x, center_y - 4)])
        else:
            p.draw.polygon(screen, arrowColor, [(center_x - 6, center_y - 4), (center_x + 6, center_y - 4), (center_x, center_y + 4)])


# name, captured pieces, material lead and clock of one player, and an optional note after the name
# y: the strip's top (panelAreas); it spans the panel's width, and its insides grow with the layout's scale
# returns the strip's free span (left, right): from the end of the name (and note) to the clock or the strip's end
def drawPlayerStrip(screen, y, color, name, captured, advantage, clockMs, clockActive, note=None):
    rect = p.Rect(LAYOUT.panel.x, y, LAYOUT.panel.width, LAYOUT.stripHeight)
    p.draw.rect(screen, p.Color(UI['strip']), rect)
    p.draw.line(screen, p.Color(UI['stripLine']), (rect.x, rect.bottom - 1), (rect.right, rect.bottom - 1))

    # side marker and name
    marker, nameY = (rect.x + scaled(18), rect.y + scaled(15)), rect.y + scaled(15)
    p.draw.circle(screen, p.Color('white' if color == 'w' else 'black'), marker, scaled(7))
    p.draw.circle(screen, p.Color(UI['text']), marker, scaled(7), 1)
    nameObj = get_text_surface(name, scaled(18), UI['text'], True)
    screen.blit(nameObj, (rect.x + scaled(32), nameY - nameObj.get_height() / 2))
    nameEnd = rect.x + scaled(32) + nameObj.get_width()
    if note:  # e.g. "thinking..." while the computer searches
        noteObj = get_text_surface(note, scaled(16), UI['textDim'], False)
        screen.blit(noteObj, (rect.x + scaled(40) + nameObj.get_width(), nameY - noteObj.get_height() / 2))
        nameEnd = rect.x + scaled(40) + nameObj.get_width() + noteObj.get_width()

    # captured pieces, grouped by type, then the material lead
    x = rect.x + scaled(10)
    previous = None
    for piece in captured:
        if previous is not None:
            x += 10 if piece == previous else 18
        screen.blit(capturedIcon(piece), (x - 1, rect.y + scaled(26)))
        previous = piece
    if advantage > 0:
        leadObj = get_text_surface("+" + str(advantage), scaled(16), UI['textDim'], True)
        screen.blit(leadObj, (x + (SMALL_PIECE_SIZE + 4 if captured else 0),
                              rect.y + scaled(26) + 12 - leadObj.get_height() / 2))

    if clockMs is not None:
        clockRect = p.Rect(rect.right - scaled(12) - scaled(96), rect.y + scaled(8), scaled(96), scaled(36))
        p.draw.rect(screen, p.Color(UI['clockActive'] if clockActive else UI['clockIdle']), clockRect, border_radius=6)
        if clockActive and clockMs < 20000:
            textColor = p.Color(UI['clockLow'])
        else:
            textColor = p.Color(UI['clockText'] if clockActive else UI['clockTextIdle'])
        textObj = get_font(scaled(24), True).render(formatClock(clockMs), True, textColor)
        screen.blit(textObj, (clockRect.centerx - textObj.get_width() / 2, clockRect.centery - textObj.get_height() / 2))
        return nameEnd, clockRect.x
    return nameEnd, rect.right - scaled(10)


# a captured piece's icon for the player strips, 2 px larger than SMALL_IMAGES': Black's pieces get a thin halo in
# UI['capturedHalo'], or they would vanish into the dark theme's strip (White's have their own dark outline)
def capturedIcon(piece):
    halo = UI['capturedHalo']
    key = (piece, halo)
    if key not in CAPTURED_ICONS:
        icon = SMALL_IMAGES[piece]
        surface = p.Surface((SMALL_PIECE_SIZE + 2, SMALL_PIECE_SIZE + 2), p.SRCALPHA)
        if piece[0] == 'b':
            shape = p.mask.from_surface(icon, 100).to_surface(setcolor=halo, unsetcolor=(0, 0, 0, 0))
            for dx, dy in ((-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1)):
                surface.blit(shape, (1 + dx, 1 + dy))
        surface.blit(icon, (1, 1))
        CAPTURED_ICONS[key] = surface
    return CAPTURED_ICONS[key]


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
    font = get_font(scaled(17), False)
    lines = wrapText(text, font, rect.width - 20)
    if len(lines) > 2:
        font = get_font(scaled(14), False)
        lines = wrapText(text, font, rect.width - 20)[:2]
    lineHeight = font.get_linesize()
    s = p.Surface(rect.size, p.SRCALPHA)
    p.draw.rect(s, UI['statusBg'], s.get_rect(), border_radius=BUTTON_RADIUS)
    screen.blit(s, rect.topleft)
    y = rect.centery - lineHeight * len(lines) / 2
    for line in lines:
        textObj = font.render(line, True, p.Color(UI['statusText']))
        screen.blit(textObj, (rect.centerx - textObj.get_width() / 2, y))
        y += lineHeight


# dims everything behind a window; a window drawn on its own see-through layer (drawWindow, in portrait) has nothing
# behind it there: the layer's owner dims the canvas instead
def drawShade(screen):
    if screen.get_flags() & p.SRCALPHA:
        return
    shade = p.Surface(screen.get_size())
    shade.set_alpha(UI['shade'][3])
    shade.fill(p.Color(*UI['shade'][:3]))
    screen.blit(shade, (0, 0))


# the rounded box of the account, help and settings windows
def drawWindowBox(screen, box):
    p.draw.rect(screen, p.Color(UI['window']), box, border_radius=WINDOW_RADIUS)
    p.draw.rect(screen, p.Color(UI['windowBorder']), box, 3, border_radius=WINDOW_RADIUS)


# --- the windows are laid out in a frame the board's size (as they sit over the board in landscape); portrait
# shows them scaled up to the canvas's width, so their text reads on a phone

WINDOW_MARGIN = 14  # portrait: between a scaled-up window and the canvas's edges


# how a window with this box (in the frame) is shown: (scale, (x, y) of the frame's origin on the canvas)
def windowTransform(box):
    if LAYOUT.kind != 'portrait':
        return 1, (0, 0)
    width, height = LAYOUT.size
    scale = min((width - 2 * WINDOW_MARGIN) / box.width, (height - 2 * WINDOW_MARGIN) / box.height)
    return scale, (width / 2 - box.centerx * scale, height / 2 - box.centery * scale)


# a canvas point in the frame of the window with this box (clicks and the pointer)
def toWindow(pos, box):
    scale, (x, y) = windowTransform(box)
    return (math.floor((pos[0] - x) / scale), math.floor((pos[1] - y) / scale))


# where a rect of the window's frame shows on the canvas (to point at a window's controls from outside, e.g. tests)
def fromWindow(rect, box):
    scale, (x, y) = windowTransform(box)
    left, top = math.ceil(x + rect.x * scale), math.ceil(y + rect.y * scale)
    return p.Rect(left, top, math.floor(x + rect.right * scale) - left, math.floor(y + rect.bottom * scale) - top)


# draws a window: draw(surface) draws it as laid out. Landscape straight onto the screen; portrait on a see-through
# frame, then the box scaled up onto the dimmed canvas
def drawWindow(screen, box, draw):
    scale, (x, y) = windowTransform(box)
    if scale == 1 and (x, y) == (0, 0):
        draw(screen)
        return
    drawShade(screen)
    frame = p.Surface((BOARD_WIDTH, BOARD_HEIGHT), p.SRCALPHA)
    draw(frame)
    area = box.inflate(4, 4).clip(frame.get_rect())
    image = p.transform.smoothscale(frame.subsurface(area), (round(area.width * scale), round(area.height * scale)))
    screen.blit(image, (round(x + area.x * scale), round(y + area.y * scale)))


# --- text fields (the account form and the room code box); the editing itself is textfield.TextField

FIELD_TEXT_SIZE = 20
FIELD_PADDING = 8  # between a field's edge and its text
PASSWORD_TOGGLE_WIDTH = 50  # the Show / Hide switch at the right end of a password field
MIN_PASSWORD_LENGTH = 8  # as the account server (api/account.py) requires
EMAIL_PATTERN = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
USERNAME_CHARACTERS = string.ascii_letters + string.digits + "_"
CARET_STEADY_MS = 600  # the caret stays lit this long after typing or moving it, then blinks


# size: the text's size (the panel's room box grows with the layout's scale; the windows' fields keep theirs)
def fieldFont(size=FIELD_TEXT_SIZE):
    return get_font(size, False)


def passwordToggleRect(rect):
    return p.Rect(rect.right - PASSWORD_TOGGLE_WIDTH - 5, rect.y + 5, PASSWORD_TOGGLE_WIDTH, rect.height - 10)


# where a field's text goes (left of the Show / Hide switch of a password field)
def fieldTextArea(rect, field):
    right = passwordToggleRect(rect).x - 4 if field.password else rect.right - FIELD_PADDING
    return p.Rect(rect.x + FIELD_PADDING, rect.y, right - rect.x - FIELD_PADDING, rect.height)


# a click at x in the field's rect puts the caret at the nearest character boundary
def placeCaret(field, rect, x, showPassword=False, size=FIELD_TEXT_SIZE):
    field.setCaretFromX(fieldFont(size), x - fieldTextArea(rect, field).x, field.scroll, showPassword)


def validEmail(text):
    return bool(EMAIL_PATTERN.match(text.strip()))


# the room code in pasted text: an invite link's ?room=..., or the text itself (only the room code's characters)
def roomCodeFromText(text):
    text = str(text or "").strip()
    found = re.search(r'[?&#]room=([^&#\s]*)', text)
    if found:
        text = found.group(1)
    elif re.search(r'[a-z]+://|www\.', text, re.IGNORECASE):
        return ""  # some other link: there's no code in it
    return "".join(ch for ch in text.upper() if ch in ROOM_CODE_CHARACTERS)[:ROOM_CODE_LENGTH]


# pasting into the room box: a link replaces what's there with its room code, other text goes in at the caret
def pasteRoomCode(field, text):
    code = roomCodeFromText(text)
    if re.search(r'[?&#]room=', str(text or "")):
        field.setValue(code)
    else:
        field.insert(code)


# what a password reset link put after the # of the page's address: {'token', 'refresh'} for choosing a new
# password (and 'email', the account it is for, when the token names it), {'error'} for a link that expired or
# was used, None for anything else. Anyone can make such an address, so its error text is never shown
def resetLinkFromHash(hashText):
    values = dict(parse_qsl(str(hashText or "").lstrip('#'), keep_blank_values=True))
    if values.get('type') == 'recovery' and values.get('access_token'):
        link = {'token': values['access_token'], 'refresh': values.get('refresh_token') or None}
        email = tokenEmail(values['access_token'])
        if email:
            link['email'] = email
        return link
    if values.get('error_code') or values.get('error_description'):
        if values.get('error_code') == 'otp_expired':
            return {'error': "That email link has expired or was already used. Ask for a new one"}
        return {'error': "That email link didn't work. Ask for a new one"}
    return None


# whether the # of the page's address carries a sign-in (an email link's tokens: reset, confirmation, ...)
def hashHasSignIn(hashText):
    values = dict(parse_qsl(str(hashText or "").lstrip('#'), keep_blank_values=True))
    return bool(values.get('access_token') or values.get('refresh_token'))


# the email an access token (a JWT) was given for, or None; only read to show it, never trusted for anything
def tokenEmail(token):
    try:
        payload = str(token).split('.')[1]
        email = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4))).get('email')
    except Exception:
        return None
    return email if isinstance(email, str) and 0 < len(email) <= 254 and email.isprintable() else None


def drawTextField(screen, rect, field, focused, mouse_pos=(-1, -1), showPassword=False, placeholder="",
                  radius=6, size=FIELD_TEXT_SIZE):
    p.draw.rect(screen, p.Color(UI['fieldFocus'] if focused else UI['field']), rect, border_radius=radius)
    p.draw.rect(screen, p.Color(UI['fieldBorderFocus'] if focused else UI['fieldBorder']), rect, 2,
                border_radius=radius)
    area = fieldTextArea(rect, field)
    font = fieldFont(size)
    shown = field.shown(showPassword)
    scroll = field.scrollFor(font, area.width, showPassword)
    oldClip = screen.get_clip()
    screen.set_clip(area.inflate(2, 0).clip(oldClip))  # long text scrolls under the field's edges
    if shown:
        textObj = font.render(shown, True, p.Color(UI['fieldText']))
        screen.blit(textObj, (area.x - scroll, area.centery - textObj.get_height() / 2))
    elif placeholder:
        textObj = get_text_surface(placeholder, size, UI['textDim'], False)
        screen.blit(textObj, (area.x, area.centery - textObj.get_height() / 2))
    ticks = p.time.get_ticks()
    if focused and (ticks - field.edited < CARET_STEADY_MS or (ticks // 530) % 2 == 0):
        x = area.x + field.caretX(font, showPassword) - scroll
        half = round(11 * size / FIELD_TEXT_SIZE)
        p.draw.line(screen, p.Color(UI['fieldText']), (x, area.centery - half), (x, area.centery + half - 1), 2)
    screen.set_clip(oldClip)
    if field.password:
        toggle = passwordToggleRect(rect)
        if toggle.collidepoint(mouse_pos):
            p.draw.rect(screen, p.Color(UI['segment']), toggle, border_radius=4)
        label = get_text_surface("Hide" if showPassword else "Show", 20, UI['accent'], sans=True)
        screen.blit(label, (toggle.centerx - label.get_width() / 2, toggle.centery - label.get_height() / 2 + 1))


# --- a scrollbar beside a list of rows (the move list, the saved games): the track and the thumb, whose size shows the
# share of rows in view; first is the first row shown. None, None when every row fits

def scrollbarRects(x, top, height, rows, visible, first):
    if rows <= visible:
        return None, None
    track = p.Rect(x, top, SCROLLBAR_WIDTH, height)
    thumbHeight = max(SCROLLBAR_MIN_THUMB, round(track.height * visible / rows))
    thumbY = track.y + round((track.height - thumbHeight) * first / (rows - visible))
    return track, p.Rect(track.x, thumbY, SCROLLBAR_WIDTH, thumbHeight)


# the first row shown with the thumb's top at thumbTop (dragging the thumb); layout has 'track', 'thumb', 'rows', 'visible'
def firstRowForThumb(layout, thumbTop):
    track, thumb = layout['track'], layout['thumb']
    if track is None:
        return 0
    span = layout['rows'] - layout['visible']
    room = max(1, track.height - thumb.height)
    return round(min(max(thumbTop - track.y, 0), room) / room * span)


def drawScrollbar(screen, layout, held=False):
    if layout['track'] is not None:
        radius = SCROLLBAR_WIDTH // 2
        p.draw.rect(screen, p.Color(UI['scrollTrack']), layout['track'], border_radius=radius)
        p.draw.rect(screen, p.Color(UI['accent'] if held else UI['scrollThumb']), layout['thumb'], border_radius=radius)


# --- account window, drawn over the board, its box fitted to each view's content

ACCOUNT_BOX = p.Rect(124, 84, 520, 600)  # the How to play window's box (the account window's own is accountLayout's)
ACCOUNT_WIDTH = 520
ACCOUNT_ROW_HEIGHT = 30  # a row of the saved games or the leaderboard
ACCOUNT_LIST_ROWS = {'games': 12, 'leaderboard': 10}  # rows in view; the saved games scroll (the server sends 50)
ACCOUNT_LIST_WHEEL = 2  # rows per wheel notch
ACCOUNT_STAT_ROW = 34  # a mode's row of results in the profile
ACCOUNT_FORMS = ('signin', 'register', 'forgot', 'newPassword')
ACCOUNT_TITLES = {'signin': "Sign in", 'register': "Create an account", 'games': "My games",
                  'leaderboard': "Leaderboard", 'forgot': "Reset your password", 'newPassword': "Choose a new password"}
# a line or two under the title of a form that needs saying what it does
ACCOUNT_INTROS = {'forgot': "Enter your account's email, and we'll send you a link to choose a new password.",
                  'newPassword': "Type a new password for your account. You'll stay signed in on this device."}
# the newPassword view names the account the reset link is for, so nobody sets a password on another's unawares
NEW_PASSWORD_FOR = "Type a new password for %s."
NEW_PASSWORD_STAY = "You'll stay signed in on this device."
ACCOUNT_INTRO_HEIGHT = 52
ACCOUNT_SUBMITS = {'signin': "Sign in", 'register': "Create account", 'forgot': "Send reset link",
                   'newPassword': "Save password"}
ACCOUNT_SWITCHES = {'signin': "No account yet? Create one", 'register': "Already registered? Sign in",
                    'forgot': "Back to sign in", 'newPassword': "Ask for a new link"}
ACCOUNT_BUTTONS = {'close': "Close", 'back': "Back", 'games': "My games", 'leaderboard': "Leaderboard",
                   'signOut': "Sign out"}
ACCOUNT_AREAS = ('box', 'list')  # layout rects that aren't controls
RESET_LINK_SENT = "If that email has an account, a reset link is on its way. Check your inbox."


def accountFieldNames(view):
    return {'register': ['username', 'email', 'password'], 'signin': ['login', 'password'], 'forgot': ['email'],
            'newPassword': ['password']}.get(view, [])


# the profile's rows of results: each computer level played, then online
def profileStatKeys(stats):
    levels = sorted((key for key in stats if key.startswith('ai') and key[2:].isdigit()), key=lambda key: int(key[2:]))
    return levels + (['online'] if 'online' in stats else [])


# the count accountLayout needs: the profile's rows of results, or the list's rows
def accountRowCount(view, account, rows):
    return len(profileStatKeys(account.stats or {})) if view == 'profile' else len(rows)


# rects of the account window's parts, by name. count: rows of the list (saved games, leaderboard) or of the
# profile's results; scroll: the first saved game shown. 'list' is the list's area (rows are 'row:<index>')
def accountLayout(view, count=0, scroll=0):
    x, width = 40, ACCOUNT_WIDTH - 80
    rects = {}
    y = 80 + (ACCOUNT_INTRO_HEIGHT if view in ACCOUNT_INTROS else 0)
    if view in ACCOUNT_FORMS:
        for name in accountFieldNames(view):
            rects['field:' + name] = p.Rect(x, y + 24, width, 40)
            if name == 'password':
                rects['toggle:password'] = passwordToggleRect(rects['field:' + name])
            y += 78
        y += 40  # room for the error message
        rects['submit'] = p.Rect(x, y, width, ROW_HEIGHT)
        y += ROW_HEIGHT + ROW_GAP
        if view in ACCOUNT_SWITCHES:
            rects['switch'] = p.Rect(x, y, width, ROW_HEIGHT)
            y += ROW_HEIGHT + ROW_GAP
        if view == 'signin':
            rects['forgot'] = p.Rect(x + width // 2 - 90, y, 180, 28)
            y += 28 + ROW_GAP
        bottom = [['close']]
    elif view == 'profile':
        y += 36 + 28 + 16  # the rating, the rated games and a gap
        y += 34 + max(count, 1) * ACCOUNT_STAT_ROW  # results: a heading with the legend, then a row per mode
        y += 40  # the message
        bottom = [['games', 'leaderboard'], ['signOut', 'close']]
    else:
        rows = ACCOUNT_LIST_ROWS.get(view, 10)
        rects['list'] = p.Rect(x, y, width, rows * ACCOUNT_ROW_HEIGHT)
        y += rects['list'].height + 40  # and the message under it
        bottom = [['back', 'close']]
    for row in bottom:
        rowWidth = (width - 10 * (len(row) - 1)) // len(row)
        for i, name in enumerate(row):
            rects[name] = p.Rect(x + i * (rowWidth + 10), y, rowWidth, ROW_HEIGHT)
        y += ROW_HEIGHT + ROW_GAP
    height = y - ROW_GAP + 24
    box = p.Rect((BOARD_WIDTH - ACCOUNT_WIDTH) // 2, (BOARD_HEIGHT - height) // 2, ACCOUNT_WIDTH, height)
    rects = {name: rect.move(box.topleft) for name, rect in rects.items()}
    rects['box'] = box
    if 'list' in rects:
        for rect, index in accountListCells(rects['list'], count, scroll):
            rects['row:%d' % index] = rect
    return rects


# the saved games or leaderboard in view, like moveListLayout: {'scroll' (clamped first row), 'first', 'visible',
# 'rows', 'area', 'cells' [(rect, index)], 'track', 'thumb'}
def accountListLayout(view, count, scroll=0):
    area = accountLayout(view, count)['list']
    visible = area.height // ACCOUNT_ROW_HEIGHT
    first = min(max(scroll, 0), max(0, count - visible))
    track, thumb = scrollbarRects(area.right - SCROLLBAR_WIDTH, area.y, area.height - 2, count, visible, first)
    return {'scroll': first, 'first': first, 'visible': visible, 'rows': count, 'area': area,
            'cells': accountListCells(area, count, first), 'track': track, 'thumb': thumb}


def accountListCells(area, count, scroll):
    visible = area.height // ACCOUNT_ROW_HEIGHT
    first = min(max(scroll, 0), max(0, count - visible))
    width = area.width - (SCROLLBAR_WIDTH + 10 if count > visible else 0)  # the scrollbar's room
    return [(p.Rect(area.x, area.y + (i - first) * ACCOUNT_ROW_HEIGHT, width, ACCOUNT_ROW_HEIGHT - 2), i)
            for i in range(first, min(count, first + visible))]


# a stacked bar of won / drawn / lost games in rect (an empty track with no games)
def drawRecordBar(screen, rect, record):
    p.draw.rect(screen, p.Color(UI['scrollTrack']), rect, border_radius=4)
    parts = [(record.get(key, 0), UI[color]) for key, color in
             (('won', 'recordWon'), ('drawn', 'recordDrawn'), ('lost', 'recordLost'))]
    parts = [(count, color) for count, color in parts if count > 0]
    total = sum(count for count, _ in parts)
    x = rect.x
    for i, (count, color) in enumerate(parts):
        right = rect.right if i == len(parts) - 1 else rect.x + round(rect.width * (sum(c for c, _ in parts[:i + 1])) / total)
        if right <= x:
            continue
        p.draw.rect(screen, p.Color(color), p.Rect(x, rect.y, right - x, rect.height),
                    border_top_left_radius=4 if i == 0 else 0, border_bottom_left_radius=4 if i == 0 else 0,
                    border_top_right_radius=4 if i == len(parts) - 1 else 0,
                    border_bottom_right_radius=4 if i == len(parts) - 1 else 0)
        x = right


# a mode's results in chess style: +won =drawn -lost
def formatScore(record):
    return "+%d =%d -%d" % (record.get('won', 0), record.get('drawn', 0), record.get('lost', 0))


def drawProfile(screen, box, account):
    x, width = box.x + 40, box.width - 80
    profile = account.profile or {}
    y = box.y + 80
    if not profile:
        return
    rated = profile.get('rated_games', 0)
    screen.blit(get_text_surface("Rating %d" % profile.get('rating', 0), 30, UI['text'], True), (x, y))
    y += 36
    note = countGames(rated) + " rated online" if rated else "Play online games while signed in to get rated"
    screen.blit(get_fitting_text(note, width, 18, UI['textDim'], False), (x, y))
    y += 28 + 16
    stats = account.stats or {}
    screen.blit(get_text_surface("Your results", 20, UI['text'], True), (x, y))
    # the legend, right-aligned on the heading's line
    legendX = x + width
    for label, color in (("Lost", 'recordLost'), ("Drawn", 'recordDrawn'), ("Won", 'recordWon')):
        textObj = get_text_surface(label, 16, UI['textDim'], False)
        legendX -= textObj.get_width()
        screen.blit(textObj, (legendX, y + 4))
        legendX -= 16
        p.draw.rect(screen, p.Color(UI[color]), p.Rect(legendX, y + 7, 11, 11), border_radius=2)
        legendX -= 12
    y += 34
    keys = profileStatKeys(stats)
    if not keys:
        screen.blit(get_fitting_text("Games you finish while signed in are counted here", width, 18, UI['textDim'],
                                     False), (x, y + 6))
    for key in keys:
        if key == 'online':
            name = "Online"
        else:
            level = int(key[2:])
            name = "vs " + (LEVEL_OPTIONS[level] if level < len(LEVEL_OPTIONS) else "level %d" % level)
        record = stats[key]
        rowMiddle = y + ACCOUNT_STAT_ROW // 2
        nameObj = get_fitting_text(name, 128, 18, UI['text'], False)
        screen.blit(nameObj, (x, rowMiddle - nameObj.get_height() / 2))
        scoreObj = get_fitting_text(formatScore(record), 104, 18, UI['textDim'], False)
        screen.blit(scoreObj, (x + width - scoreObj.get_width(), rowMiddle - scoreObj.get_height() / 2))
        drawRecordBar(screen, p.Rect(x + 136, rowMiddle - 7, width - 136 - 112, 14), record)
        y += ACCOUNT_STAT_ROW


def drawAccountWindow(screen, view, fields, focus, message, busy, account, rows, mouse_pos, tone='error', scroll=0,
                      showPassword=False, thumbHeld=False, resetEmail=None):
    drawShade(screen)
    rects = accountLayout(view, accountRowCount(view, account, rows), scroll)
    box = rects['box']
    drawWindowBox(screen, box)
    x, width = box.x + 40, box.width - 80
    title = ACCOUNT_TITLES.get(view) or account.username or "Account"
    titleObj = get_fitting_text(title, width, 32, UI['text'])
    screen.blit(titleObj, (box.centerx - titleObj.get_width() / 2, box.y + 26))
    if view in ACCOUNT_INTROS:
        y = box.y + 76
        text = ACCOUNT_INTROS[view]
        if view == 'newPassword' and resetEmail:  # resetEmail: the account the reset link is for
            text = NEW_PASSWORD_FOR % resetEmail + " " + NEW_PASSWORD_STAY
        font = get_font(18, False)
        lines = wrapText(text, font, width)
        if len(lines) > 2:  # a long email: on a line of its own, shortened in the middle as much as it must be
            shown, keep = resetEmail, len(resetEmail)
            while font.size(NEW_PASSWORD_FOR % shown)[0] > width and keep > 2:
                keep -= 1
                shown = resetEmail[:(keep + 1) // 2] + "..." + resetEmail[len(resetEmail) - keep // 2:]
            lines = [NEW_PASSWORD_FOR % shown, NEW_PASSWORD_STAY]
        for line in lines:
            screen.blit(get_text_surface(line, 18, UI['textBody'], False), (x, y))
            y += 22

    buttons = {}
    if view in ACCOUNT_FORMS:
        labels = {'username': "Username (3-20 letters, digits or _)", 'email': "Email", 'login': "Email or username",
                  'password': {'register': "Password (at least 8 characters)",
                               'newPassword': "New password (at least 8 characters)"}.get(view, "Password")}
        for name in accountFieldNames(view):
            rect = rects['field:' + name]
            screen.blit(get_text_surface(labels[name], 17, UI['textDim'], False), (rect.x, rect.y - 22))
            drawTextField(screen, rect, fields[name], focus == name and not busy, mouse_pos, showPassword)
        messageY = rects['submit'].y - 32
        buttons = {'submit': ACCOUNT_SUBMITS[view], 'switch': ACCOUNT_SWITCHES.get(view, "")}
        if 'forgot' in rects:  # a link rather than a button: it's the way out of a sign-in that doesn't work
            rect = rects['forgot']
            hovered = rect.collidepoint(mouse_pos) and not busy
            linkObj = get_text_surface("Forgot password?", 22, UI['textDim'] if busy else UI['accent'], sans=True)
            linkPos = (rect.centerx - linkObj.get_width() / 2, rect.centery - linkObj.get_height() / 2)
            screen.blit(linkObj, linkPos)
            if hovered:
                y = linkPos[1] + linkObj.get_height()
                p.draw.line(screen, p.Color(UI['accent']), (linkPos[0], y), (linkPos[0] + linkObj.get_width(), y), 1)
    elif view == 'profile':
        drawProfile(screen, box, account)
        messageY = rects['games'].y - 34
    else:
        listLayout = accountListLayout(view, len(rows), scroll)
        for rect, i in listLayout['cells']:
            row = rows[i]
            if view == 'games':
                if rect.collidepoint(mouse_pos) and not busy:
                    p.draw.rect(screen, p.Color(UI['logHighlight']), rect, border_radius=4)
                left = "%s   %s" % (str(row.get('played_at', ''))[:10], gameRowResult(row))
                right = row.get('opponent') or "Local game"
            else:
                left = "%d. %s" % (i + 1, row['username'])
                right = "%d  (%s)" % (row["rating"], countGames(row["rated_games"]))
            screen.blit(get_fitting_text(left, rect.width // 2, 18, UI['text'], False), (rect.x + 6, rect.y + 3))
            rightObj = get_fitting_text(right, rect.width // 2 - 10, 18, UI['textDim'], False)
            screen.blit(rightObj, (rect.right - 6 - rightObj.get_width(), rect.y + 3))
        drawScrollbar(screen, listLayout, thumbHeld)
        if not rows and not busy:
            empty = "No saved games yet" if view == 'games' else "Nobody is rated yet"
            screen.blit(get_text_surface(empty, 20, UI['textDim'], False), (x, listLayout['area'].y + 6))
        messageY = rects['back'].y - 34

    if message:
        color = UI['textDim'] if busy else UI['success'] if tone == 'success' else UI['error']
        lines = wrapText(message, get_font(17, True), width) if view in ACCOUNT_FORMS else [message]
        if len(lines) > 1:  # a form has room for two lines above its button
            lines, messageY = lines[:2], messageY - 12
        for line in lines:
            screen.blit(get_fitting_text(line, width, 17 if view in ACCOUNT_FORMS else 18, color, True), (x, messageY))
            messageY += 20
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

# small board diagrams beside a help item's text (drawMiniBoard): files left to right and ranks top to bottom as
# shown, pieces by square, arrows (start, end[, color]: ARROW_COLOR when none; drawn under the pieces), 'ghosts'
# (where a piece ends up, see-through), 'rings' (a piece that is taken), 'tints' (the last move) and 'check'
CHECK_DIAGRAM = {'files': "bcde", 'ranks': "8765", 'pieces': {'e8': 'bK', 'c7': 'bp', 'd6': 'bp', 'e7': 'bp', 'b5': 'wB'},
                 'arrows': [('b5', 'e8', ANNOTATION_COLORS['red'])], 'check': 'e8'}
PROMOTION_DIAGRAM = {'files': "def", 'ranks': "87", 'pieces': {'e7': 'wp'}, 'arrows': [('e7', 'e8')],
                     'ghosts': {'e8': 'wQ'}}
CASTLING_DIAGRAM = {'files': "efgh", 'ranks': "21", 'pieces': {'e1': 'wK', 'h1': 'wR', 'f2': 'wp', 'g2': 'wp', 'h2': 'wp'},
                    'arrows': [('e1', 'g1')], 'ghosts': {'g1': 'wK', 'f1': 'wR'}}
EN_PASSANT_DIAGRAM = {'files': "def", 'ranks': "765", 'pieces': {'d5': 'bp', 'e5': 'wp'}, 'arrows': [('e5', 'd6')],
                      'rings': ['d5'], 'tints': ['d7', 'd5']}
HELP_DIAGRAM_SQ = 36  # a diagram's squares (px)
HELP_DIAGRAM_LABEL = 14  # room for the rank numbers on the left and the file letters below
HELP_DIAGRAM_GAP = 16  # between an item's text and its diagram

# (title, items); an item is (piece icon or None, heading, text), or (icon, heading, text, diagram)
HELP_PAGES = [
    ("The goal", [
        (None, "Checkmate wins",
         "Attack the opponent's king so that it has no way to escape. You may never leave your own king "
         "under attack."),
        (None, "Taking turns",
         "White moves first, then the players take turns, one move each. Click one of your pieces, then a "
         "square it can go to, or drag it there (see On the board)."),
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
    ("Check and promotion", [
        (None, "Check",
         "When your king is attacked, move it, block the attack or take the attacker. The king's square turns "
         "red, and only moves that get out of check are allowed.", CHECK_DIAGRAM),
        (None, "Promotion",
         "A pawn that reaches the far side becomes a queen, rook, bishop or knight. Pick one from the pieces "
         "shown over the square, or click elsewhere to take the move back.", PROMOTION_DIAGRAM),
    ]),
    ("Special moves", [
        (None, "Castling",
         "Click the king, then the square two steps toward a rook: the rook jumps to the king's other side. "
         "Neither piece may have moved, the squares between must be empty, and the king can't be in check or "
         "cross an attacked square.", CASTLING_DIAGRAM),
        (None, "En passant",
         "A pawn that moves two squares can be taken by an enemy pawn beside it, as if it had moved only one, "
         "but only on the very next move. Here Black's pawn has just moved from d7 to d5.", EN_PASSANT_DIAGRAM),
    ]),
    ("On the board", [
        (None, "Moving",
         "Click a piece to see where it can go: dots on free squares, rings around pieces it can take. Then "
         "click one of them, or drag the piece there. A move that would leave your king in check is refused, "
         "and the king's square flashes."),
        (None, "Arrows and marks",
         "Right-click a square to circle it, or drag with the right button to draw an arrow. Hold Shift for "
         "red, Ctrl or Alt for blue. A left click on the board clears them."),
        (None, "Premoves",
         "While your opponent thinks, choose your next move: its squares turn purple, and it's played as soon "
         "as your turn comes if it's still legal. Right-click or Esc cancels it (Settings can turn premoves off)."),
        (None, "Looking back",
         "The arrow keys, or a click on a move in the list, show earlier positions, during the game too: End "
         "or a click on the board returns. After the game, Analyze game marks mistakes with ?!, ? and ??."),
    ]),
    ("Game modes", [
        (None, "Local vs AI",
         "Play the computer. Choose its level, from Easy to Impossible, and whether you play White, Black or "
         "a random side."),
        (None, "Local 2-Player", "Two players take turns on the same screen."),
        (None, "Online Multiplayer",
         "Play a friend on another device, in a room of your own: see Playing online, the next page."),
        (None, "Clock",
         "Pick a time control before the game. 3+2 means three minutes each, plus two seconds for every "
         "move. Running out of time loses."),
        (None, "Account",
         "Sign in to keep your games, see your record and get an online rating. Forgot your password? Sign in "
         "has a reset link."),
    ]),
    ("Playing online", [
        (None, "Hosting a room",
         "Choose Online Multiplayer and click Host: you play White. Copy link puts an invite link on the "
         "clipboard to send your friend, or tell them the room code."),
        (None, "Joining",
         "Open the invite link and click Join, or type or paste the code in the room box and click Join "
         "(Black)."),
        (None, "Quick chat",
         "Chat opens a list of short messages, like Good luck! or Good game!. Each shows for a few seconds in "
         "a bubble by its sender's name."),
        (None, "Is your opponent there?",
         "The line under the room code says whether your opponent is connected, or has gone quiet and may have "
         "left."),
        (None, "Rejoin and Your move",
         "Rejoin returns to your last room, say after a reload. If your turn comes while you're in another tab "
         "or window, its title says Your move and a chime plays."),
    ]),
    ("Buttons and keys", [
        (None, "Hint", "Shows a good move on the board, up to 5 times a day."),
        (None, "Undo (Z) and Restart (R)",
         "Take back your last move (and the computer's reply). Online, the opponent must agree, and Restart "
         "leaves the room."),
        (None, "Resign and Offer Draw",
         "Give up the game, or offer a draw. The computer only accepts a draw when it is losing."),
        (None, "Menu (three lines, bottom right)",
         "Save the game as a PGN file or open one, Flip board (F), Settings (board, pieces, theme, sound) "
         "and How to play."),
        (None, "Move list and graph",
         "Scroll with the wheel or the scrollbar, or drag the list. After Analyze game, click or drag on the "
         "graph of who was better to see that moment."),
        (None, "How to play (H)",
         "Opens this window. Esc closes it. Rest the pointer on a button to see what it does, or why it's grayed "
         "out."),
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


def diagramSize(diagram):
    return (HELP_DIAGRAM_LABEL + len(diagram['files']) * HELP_DIAGRAM_SQ,
            len(diagram['ranks']) * HELP_DIAGRAM_SQ + HELP_DIAGRAM_LABEL)


# where each item of a help page goes: {'top', 'textX', 'lines' (the text wrapped), 'diagram' (its rect beside the
# text, at the right, or None), 'bottom'}; the next item starts 12 px below the bottom
def helpPageLayout(page):
    box = ACCOUNT_BOX
    x, width = box.x + 40, box.width - 80
    font = get_font(17, False)
    y = box.y + 82
    layout = []
    for item in HELP_PAGES[page][1]:
        icon, heading, text = item[:3]
        diagram = item[3] if len(item) > 3 else None
        textX = x + (HELP_ICON_SIZE + 12 if icon else 0)
        right = x + width
        diagramRect = None
        if diagram:
            diagramWidth, diagramHeight = diagramSize(diagram)
            diagramRect = p.Rect(right - diagramWidth, y + 4, diagramWidth, diagramHeight)
            right = diagramRect.x - HELP_DIAGRAM_GAP
        lines = wrapText(text, font, right - textX)
        bottom = max(y + 24 + 20 * len(lines), y + (HELP_ICON_SIZE if icon else 0),
                     diagramRect.bottom if diagramRect else 0)
        layout.append({'top': y, 'textX': textX, 'lines': lines, 'diagram': diagramRect, 'bottom': bottom})
        y = bottom + 12
    return layout


# a few squares of the board (diagram: see CHECK_DIAGRAM) in the board's colors and pieces, with file and rank
# labels, at pos (its top-left, labels included)
def drawMiniBoard(screen, pos, diagram):
    files, ranks, sq = diagram['files'], diagram['ranks'], HELP_DIAGRAM_SQ
    board = p.Rect(pos[0] + HELP_DIAGRAM_LABEL, pos[1], len(files) * sq, len(ranks) * sq)

    def square(name):  # on the layer, which has the board's size
        return p.Rect(files.index(name[0]) * sq, ranks.index(name[1]) * sq, sq, sq)

    for f in files:
        for r in ranks:
            light = ('abcdefgh'.index(f) + int(r)) % 2 == 0  # a1 is dark
            p.draw.rect(screen, p.Color(BOARD_COLORS[0 if light else 1]), square(f + r).move(board.topleft))
    layer = p.Surface(board.size, p.SRCALPHA)  # see-through tints, marks and arrows
    for name in diagram.get('tints', ()):
        layer.fill(LAST_MOVE_COLOR + (170,), square(name))
    if diagram.get('check'):
        layer.fill((255, 0, 0, 110), square(diagram['check']))
    for arrow in diagram.get('arrows', ()):  # under the pieces: a ghost at the end still shows
        color = arrow[2] if len(arrow) > 2 else ARROW_COLOR
        p.draw.polygon(layer, color, arrowPolygon(square(arrow[0]).center, square(arrow[1]).center, sq))
    screen.blit(layer, board.topleft)
    for name, piece in diagram.get('ghosts', {}).items():
        ghost = DIAGRAM_IMAGES[piece].copy()
        ghost.set_alpha(150)
        screen.blit(ghost, square(name).move(board.topleft))
    for name, piece in diagram['pieces'].items():
        screen.blit(DIAGRAM_IMAGES[piece], square(name).move(board.topleft))
    layer.fill((0, 0, 0, 0))
    for name in diagram.get('rings', ()):
        p.draw.circle(layer, ANNOTATION_COLORS['red'], square(name).center, sq // 2 - 1, 3)
    screen.blit(layer, board.topleft)
    p.draw.rect(screen, p.Color(UI['textDim']), board.inflate(2, 2), 1)
    for i, f in enumerate(files):
        label = get_text_surface(f, 13, UI['textDim'], False)
        screen.blit(label, (board.x + i * sq + (sq - label.get_width()) // 2, board.bottom + 1))
    for i, r in enumerate(ranks):
        label = get_text_surface(r, 13, UI['textDim'], False)
        screen.blit(label, (pos[0] + (HELP_DIAGRAM_LABEL - 3 - label.get_width()) // 2,
                            board.y + i * sq + (sq - label.get_height()) // 2))


def drawHelpWindow(screen, page, mouse_pos):
    drawShade(screen)
    rects = helpLayout()
    box = rects['box']
    drawWindowBox(screen, box)
    x, width = box.x + 40, box.width - 80

    title, items = HELP_PAGES[page]
    titleObj = get_fitting_text(title, width - 60, 32, UI['text'])
    screen.blit(titleObj, (box.centerx - titleObj.get_width() / 2, box.y + 26))
    pageObj = get_text_surface("%d / %d" % (page + 1, len(HELP_PAGES)), 16, UI['textDim'], False)
    screen.blit(pageObj, (box.right - 16 - pageObj.get_width(), box.y + 14))

    textFont = get_font(17, False)
    for item, placed in zip(items, helpPageLayout(page)):
        icon, heading = item[:2]
        y = placed['top']
        if icon:
            screen.blit(HELP_IMAGES[icon], (x, y))
        screen.blit(get_text_surface(heading, 19, UI['text'], True), (placed['textX'], y))
        y += 24
        for line in placed['lines']:
            screen.blit(textFont.render(line, True, p.Color(UI['textBody'])), (placed['textX'], y))
            y += 20
        if placed['diagram']:
            drawMiniBoard(screen, placed['diagram'].topleft, item[3])

    buttons = {'prev': ("Back", page > 0), 'close': ("Close", True), 'next': ("Next", page < len(HELP_PAGES) - 1)}
    for name, (label, enabled) in buttons.items():
        drawButton(screen, rects[name], label, enabled, mouse_pos)


# arrows: (start square, end square) pairs drawn over the pieces, or (start, end, color) triples
# hidden: the square whose piece isn't drawn (it's being dragged); rings: (square, color) of the player's marks
# flash: (king's square, ms since the refused move) while the king's square pulses (drawKingFlash)
# premove: {'squares', 'moves'} during the opponent's turn: squares tinted in PREMOVE_COLOR (the premove, or the
# piece picked up for one) and the moves whose targets get the move hints
def drawGameState(screen, gs, validMoves, squareSelected, flip=False, arrows=(), hidden=None, rings=(), flash=None,
                  premove=None):
    drawSquare(screen, flip)  # draw square on board
    # last move played (unless switched off in Settings)
    if gs.moveLog and settings.get('lastMove'):
        lastMove = gs.moveLog[-1]
        tintSquare(screen, lastMove.startRow, lastMove.startCol, LAST_MOVE_COLOR, 170, flip)
        tintSquare(screen, lastMove.endRow, lastMove.endCol, LAST_MOVE_COLOR, 170, flip)
    highlightSquares(screen, gs, squareSelected, flip)
    for row, col in (premove['squares'] if premove else ()):
        tintSquare(screen, row, col, PREMOVE_COLOR, PREMOVE_ALPHA, flip)

    # Check/Checkmate effect: Highlight the king's square in red
    if gs.inCheck:
        row, col = gs.whiteKinglocation if gs.whiteToMove else gs.blackKinglocation
        if flip:
            row, col = 7 - row, 7 - col
        s = p.Surface((SQ_SIZE, SQ_SIZE))
        s.set_alpha(200 if gs.checkmate else 100)
        s.fill(p.Color("red"))
        screen.blit(s, (col * SQ_SIZE, row * SQ_SIZE))

    if flash is not None:  # under the king, so the piece stays clear
        drawKingFlash(screen, flash[0], flash[1], flip)
    drawPieces(screen, gs.board, flip, hidden)
    drawMoveMarkers(screen, gs, validMoves, squareSelected, flip)
    if premove and settings.get('moveMarkers'):
        drawMarkers(screen, gs.board, premove['moves'], flip)
    for square, color in rings:
        drawRing(screen, square, color, flip)
    for arrow in arrows:
        drawArrow(screen, arrow[0], arrow[1], flip, *arrow[2:])


# the board square (row, col) under a point on the screen (the canvas; the board lies at LAYOUT.board)
def boardSquare(pos, flip=False):
    x, y = toBoard(pos)
    row, col = min(7, max(0, y // SQ_SIZE)), min(7, max(0, x // SQ_SIZE))
    return (7 - row, 7 - col) if flip else (row, col)


# the color of a mark or arrow from the keys held: Shift red, Ctrl or Alt blue, otherwise green
def annotationColor(mods):
    if mods & p.KMOD_SHIFT:
        return 'red'
    if mods & (p.KMOD_CTRL | p.KMOD_ALT):
        return 'blue'
    return 'green'


# drawing the same mark or arrow again removes it; in another color it changes color
def toggleAnnotation(store, key, color):
    if store.get(key) == color:
        del store[key]
    else:
        store[key] = color


# why the side to move can't play start -> end although the piece moves that way: it would leave their king
# in check (REFUSED_IN_CHECK when it's in check already, else REFUSED_EXPOSES_KING). None when the move is legal,
# or when the piece can't go there anyway (pins and checks ignored), which is just a change of selection
def refusalReason(gs, start, end):
    saved = (gs.inCheck, gs.pins, gs.checks, gs.checkmate, gs.stalemate)
    try:
        legal = gs.getValidMoves()
        inCheck = gs.inCheck
        gs.pins, gs.checks = [], []  # the moves without pins and checks; the king's own are checked anyway
        possible = gs.getAllPossibleMoves()
    finally:
        gs.inCheck, gs.pins, gs.checks, gs.checkmate, gs.stalemate = saved

    def goes(move):
        return (move.startRow, move.startCol) == tuple(start) and (move.endRow, move.endCol) == tuple(end)
    if any(goes(move) for move in legal) or not any(goes(move) for move in possible):
        return None
    return REFUSED_IN_CHECK if inCheck else REFUSED_EXPOSES_KING


# a ring around a square, for the player's marks; see-through like the arrows
def drawRing(screen, square, color, flip=False):
    row, col = square
    if flip:
        row, col = 7 - row, 7 - col
    layer = p.Surface((SQ_SIZE, SQ_SIZE), p.SRCALPHA)
    p.draw.circle(layer, color, (SQ_SIZE // 2, SQ_SIZE // 2), SQ_SIZE // 2 - 3, max(4, SQ_SIZE // 13))
    screen.blit(layer, (col * SQ_SIZE, row * SQ_SIZE))


# the king's square after a refused move: a red tint and outline that pulse twice and fade out over KING_FLASH_MS
def drawKingFlash(screen, square, elapsed, flip=False):
    t = elapsed / KING_FLASH_MS
    if not 0 <= t < 1:
        return
    strength = (0.6 + 0.4 * math.cos(4 * math.pi * t)) * (1 - t ** 3)
    row, col = square
    if flip:
        row, col = 7 - row, 7 - col
    layer = p.Surface((SQ_SIZE, SQ_SIZE), p.SRCALPHA)
    layer.fill(KING_FLASH_COLOR + (int(110 * strength),))
    p.draw.rect(layer, KING_FLASH_COLOR + (int(240 * strength),), layer.get_rect(), 6)
    screen.blit(layer, (col * SQ_SIZE, row * SQ_SIZE))


# a piece being dragged: centered under the pointer, with a quiet outline on the square it would land on
def drawDraggedPiece(screen, piece, pos):
    if onBoard(pos):
        layer = p.Surface((SQ_SIZE, SQ_SIZE), p.SRCALPHA)
        p.draw.rect(layer, DRAG_TARGET_COLOR, layer.get_rect(), 4)
        x, y = toBoard(pos)
        screen.blit(layer, (LAYOUT.board.x + (x // SQ_SIZE) * SQ_SIZE, LAYOUT.board.y + (y // SQ_SIZE) * SQ_SIZE))
    screen.blit(IMAGES[piece], (pos[0] - SQ_SIZE // 2, pos[1] - SQ_SIZE // 2))


# ((start row, col), (end row, col)) of a move in coordinate notation, e.g. "g1f3"
def codeSquares(code):
    return ((Move.ranksToRows[code[1]], Move.filesToCols[code[0]]),
            (Move.ranksToRows[code[3]], Move.filesToCols[code[2]]))


# a see-through arrow from the center of one square to another, over the pieces: hints and the analysis's best
# move in ARROW_COLOR, the player's own arrows in their ANNOTATION_COLORS
def drawArrow(screen, start, end, flip=False, color=ARROW_COLOR):
    global ARROW_LAYER
    if ARROW_LAYER is None:
        ARROW_LAYER = p.Surface((BOARD_WIDTH, BOARD_HEIGHT), p.SRCALPHA)
    ARROW_LAYER.fill((0, 0, 0, 0))
    (r1, c1), (r2, c2) = start, end
    if flip:
        r1, c1, r2, c2 = 7 - r1, 7 - c1, 7 - r2, 7 - c2
    start = ((c1 + 0.5) * SQ_SIZE, (r1 + 0.5) * SQ_SIZE)
    end = ((c2 + 0.5) * SQ_SIZE, (r2 + 0.5) * SQ_SIZE)
    p.draw.polygon(ARROW_LAYER, color, arrowPolygon(start, end, SQ_SIZE))
    screen.blit(ARROW_LAYER, (0, 0))


# the outline of an arrow between two square centers, for squares of size sq: one polygon, so the shaft and head
# don't overlap and darken where they meet
def arrowPolygon(start, end, sq):
    (x1, y1), (x2, y2) = start, end
    length = math.hypot(x2 - x1, y2 - y1)
    ux, uy = (x2 - x1) / length, (y2 - y1) / length  # along the arrow
    nx, ny = -uy, ux  # across it
    shaft, head, headLength = sq * 0.09, sq * 0.24, sq * 0.42  # half widths, and the head's length
    sx, sy = x1 + ux * sq * 0.2, y1 + uy * sq * 0.2  # starts a little off the piece's center
    bx, by = x2 - ux * headLength, y2 - uy * headLength  # where the head begins
    return [(sx + nx * shaft, sy + ny * shaft), (bx + nx * shaft, by + ny * shaft), (bx + nx * head, by + ny * head),
            (x2, y2), (bx - nx * head, by - ny * head), (bx - nx * shaft, by - ny * shaft),
            (sx - nx * shaft, sy - ny * shaft)]


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
    if not settings.get('coordinates'):  # switched off in Settings
        return

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
    if not settings.get('moveMarkers') or not ownPieceSelected(gs, squareSelected):
        return
    row, col = squareSelected
    drawMarkers(screen, gs.board, [move for move in validMoves if move.startRow == row and move.startCol == col], flip)


# a dot or ring on the target square of each of moves
def drawMarkers(screen, board, moves, flip=False):
    if not MOVE_MARKERS:
        for name in ('dot', 'ring'):
            surface = p.Surface((SQ_SIZE, SQ_SIZE), p.SRCALPHA)
            center = (SQ_SIZE // 2, SQ_SIZE // 2)
            if name == 'dot':
                p.draw.circle(surface, MOVE_MARKER_COLOR, center, SQ_SIZE // 6)
            else:
                p.draw.circle(surface, MOVE_MARKER_COLOR, center, SQ_SIZE // 2 - 2, 7)
            MOVE_MARKERS[name] = surface
    for move in moves:
        marker = MOVE_MARKERS['ring' if board[move.endRow][move.endCol] != '--' else 'dot']
        end_r = (7 - move.endRow) if flip else move.endRow
        end_c = (7 - move.endCol) if flip else move.endCol
        screen.blit(marker, (end_c * SQ_SIZE, end_r * SQ_SIZE))


# hidden: a square whose piece is left out (it's being dragged)
def drawPieces(screen, board, flip=False, hidden=None):
    for row in range(DIMENSION):
        for col in range(DIMENSION):
            piece = board[row][col]
            if piece != "--" and (row, col) != hidden:
                draw_row = (7 - row) if flip else row
                draw_col = (7 - col) if flip else col
                screen.blit(IMAGES[piece], p.Rect(
                    draw_col * SQ_SIZE, draw_row * SQ_SIZE, SQ_SIZE, SQ_SIZE))


# --- the move list: one row per move number (number, White's move, Black's move), newest at the bottom, with a
# scrollbar when not all rows fit. moveListLayout() works out what is shown and where; clicks, drags and drawing use it

MOVE_ROW_HEIGHT = 26
MOVE_LIST_PADDING = 6  # above the first row
MOVE_NUMBER_RIGHT = PANEL_X + 48  # the move numbers are right-aligned to this x
MOVE_COLUMNS = (PANEL_X + 56, PANEL_X + 186)  # left edges of the White and Black cells
MOVE_CELL_WIDTH = 122
MOVE_TEXT_SIZE = 19
SCROLLBAR_X = PANEL_X + MOVE_LOG_PANEL_WIDTH - 14
SCROLLBAR_WIDTH = 6
SCROLLBAR_HIT = 18  # px wide strip around the bar that takes its clicks (the bar itself is thin)
SCROLLBAR_MIN_THUMB = 24


# what the move list shows between top and bottom for a game of plies moves, scrolled back scroll rows from the
# newest; follow: a ply to keep in view (the shown move), scrolling as little as needed
# returns {'scroll' (clamped), 'first' (first row shown), 'visible' (rows that fit), 'rows', 'area',
# 'cells': [(rect, ply)], 'numbers': [(move number, y)], 'track' and 'thumb' (rects, None when everything fits)}
def moveListLayout(plies, top, bottom, scroll=0, follow=None):
    layout = LAYOUT  # the sizes and columns (MOVE_ROW_HEIGHT, MOVE_COLUMNS... in landscape)
    rowHeight = layout.moveRow
    rows = (plies + 1) // 2
    visible = max(1, (bottom - top - layout.movePadding) // rowHeight)
    if follow is not None and rows:
        row = min(max(follow, 0) // 2, rows - 1)
        first = max(0, rows - visible - scroll)
        if row < first:
            scroll = rows - visible - row
        elif row >= first + visible:
            scroll = rows - 1 - row
    scroll = min(max(scroll, 0), max(0, rows - visible))
    first = max(0, rows - visible - scroll)
    y0 = top + layout.movePadding
    cells, numbers = [], []
    for row in range(first, min(rows, first + visible)):
        y = y0 + (row - first) * rowHeight
        numbers.append((row + 1, y))
        for side in (0, 1):
            if 2 * row + side < plies:
                cells.append((p.Rect(layout.moveColumns[side], y, layout.moveCell, rowHeight - 2), 2 * row + side))
    track, thumb = scrollbarRects(layout.scrollbarX, y0, visible * rowHeight - 2, rows, visible, first)
    return {'scroll': scroll, 'first': first, 'visible': visible, 'rows': rows, 'cells': cells, 'numbers': numbers,
            'area': p.Rect(layout.panel.x, top, layout.panel.width, bottom - top), 'track': track, 'thumb': thumb}


# the ply of the move drawn at pos, or None
def moveListPly(layout, pos):
    for rect, ply in layout['cells']:
        if rect.collidepoint(pos):
            return ply
    return None


# which part of the scrollbar is at pos: 'thumb', 'before' / 'after' it on the track, or None (also with no bar)
def scrollbarPart(layout, pos):
    track = layout['track']
    if track is None or abs(pos[0] - track.centerx) > SCROLLBAR_HIT // 2 or not track.top <= pos[1] < track.bottom:
        return None
    thumb = layout['thumb']
    if pos[1] < thumb.top:
        return 'before'
    return 'after' if pos[1] >= thumb.bottom else 'thumb'


# the scroll that puts the thumb's top at thumbTop (dragging the thumb)
def scrollForThumb(layout, thumbTop):
    if layout['track'] is None:
        return 0
    return layout['rows'] - layout['visible'] - firstRowForThumb(layout, thumbTop)


# a click on the track pages: before the thumb a page of older moves, after it a page of newer ones
def scrollForPage(layout, part):
    return layout['scroll'] + (layout['visible'] if part == 'before' else -layout['visible'])


# dragging the list itself moves it with the pointer: down shows older moves (touch style); startScroll: at the press
def scrollForListDrag(startScroll, dy):
    return startScroll + round(dy / LAYOUT.moveRow)


# the list's rows: numbers, moves (marks from the analysis after them) and the scrollbar
# currentPly: the move to highlight (the shown position); marks: ply -> (mark, loss); thumbHeld: the thumb is dragged
def drawMoveList(screen, layout, moveLog, currentPly=None, marks=None, thumbHeld=False, figurines=None):
    marks = marks or {}
    textSize = LAYOUT.moveText
    numberFont = get_font(textSize - 1, False)
    for number, y in layout['numbers']:
        numberObj = get_text_surface("%d." % number, textSize - 1, UI['textDim'], False)
        screen.blit(numberObj, (LAYOUT.moveNumberRight - numberObj.get_width(),
                                y + (LAYOUT.moveRow - 2 - numberFont.get_height()) // 2))
    for rect, ply in layout['cells']:
        if ply == currentPly:
            p.draw.rect(screen, p.Color(UI['logHighlight']), rect, border_radius=4)
        move = moveLog[ply]
        textObj = sanSurface(move.san or str(move), 'w' if ply % 2 == 0 else 'b', textSize, UI['text'],
                             figurines=figurines)
        x, y = rect.x + 6, rect.centery - textObj.get_height() // 2
        screen.blit(textObj, (x, y))
        if ply in marks:
            mark = marks[ply][0]
            markObj = get_text_surface(mark, textSize - 2, UI[MARK_KINDS[mark]], True)
            screen.blit(markObj, (x + textObj.get_width() + 2, rect.centery - markObj.get_height() // 2))
    drawScrollbar(screen, layout, thumbHeld)


# --- figurine notation (Settings > Game > Notation): the piece letters of a move (Nf3, exd8=Q) drawn as small
# pieces of the current set in the mover's color; used in the move list and the review info box

FIGURINE_CACHE = {}  # (san, color, size, text color, bold, piece set) -> surface


# a move's text split into ('text', str) and ('piece', letter) parts: the leading piece letter and a promotion's
def sanParts(san):
    parts = []
    for i, ch in enumerate(san):
        if ch in "KQRBN" and (i == 0 or san[i - 1] == '='):
            parts.append(('piece', ch))
        elif parts and parts[-1][0] == 'text':
            parts[-1] = ('text', parts[-1][1] + ch)
        else:
            parts.append(('text', ch))
    return parts


# a piece for figurine notation, about as big as a capital letter of the text and trimmed to its width (plus a
# pixel of space); a piece in the text's own shade (a black piece on the dark theme, a white one on the light theme)
# gets a soft outline in the text color so it stands out from the panel
def figurineIcon(folder, piece, size, textColor):
    iconSize = size + 5  # the piece images have a margin; at this size a piece reads like a capital letter
    icon = p.transform.smoothscale(previewImage(folder, piece), (iconSize, iconSize))
    bounds = icon.get_bounding_rect()
    trimmed = p.Surface((bounds.width + 4, iconSize), p.SRCALPHA)
    trimmed.blit(icon, (1, 0), p.Rect(bounds.x, 0, bounds.width, iconSize))
    lightText = sum(textColor[:3]) > 3 * 128
    if (piece[0] == 'b') == lightText:
        outline = p.mask.from_surface(trimmed).to_surface(setcolor=tuple(textColor[:3]) + (110,),
                                                           unsetcolor=(0, 0, 0, 0))
        result = p.Surface(trimmed.get_size(), p.SRCALPHA)
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            result.blit(outline, (dx, dy))
        result.blit(trimmed, (0, 0))
        trimmed = result
    return trimmed


# the text of a move: with the Notation switch on figurines (figurines None reads it), letters otherwise
# color: the mover ('w' or 'b'), whose pieces the icons show
def sanSurface(san, color, size, textColor, bold=False, figurines=None):
    if figurines is None:
        figurines = settingValue('figurines')
    if not figurines or not any(kind == 'piece' for kind, _ in sanParts(san)):
        return get_text_surface(san, size, textColor, bold)
    pieceSet = settingValue('pieces')
    key = (san, color, size, tuple(textColor), bold, pieceSet)
    if key not in FIGURINE_CACHE:
        height = get_font(size, bold).get_height()
        parts = []
        for kind, value in sanParts(san):
            if kind == 'piece':
                parts.append(figurineIcon(PIECE_SETS[pieceSet], color + value, size, textColor))
            else:
                parts.append(get_text_surface(value, size, textColor, bold))
        surface = p.Surface((sum(part.get_width() for part in parts), max([height] + [part.get_height() for part in parts])),
                            p.SRCALPHA)
        x = 0
        for part in parts:
            surface.blit(part, (x, (surface.get_height() - part.get_height()) // 2))
            x += part.get_width()
        FIGURINE_CACHE[key] = surface
    return FIGURINE_CACHE[key]


# --- the evaluation graph after the game (once an analysis exists): White's advantage up, per ply, the shown ply
# marked; a click or drag on it shows that position

GRAPH_HEIGHT = 2 * ROW_HEIGHT + ROW_GAP  # takes the place of the Analyze game row, two rows high
GRAPH_PADDING = 4  # between the frame and the chart


def graphChart(rect):
    return rect.inflate(-2 * GRAPH_PADDING, -2 * GRAPH_PADDING)


# x of a ply (0 = the start position, plies = the final one) on the graph
def graphX(rect, ply, plies):
    chart = graphChart(rect)
    return chart.x + round((chart.width - 1) * ply / max(1, plies))


# y of an evaluation (pawns, White's view), capped at EVAL_CAP; the square root lets small advantages show
def graphY(rect, score):
    chart = graphChart(rect)
    share = capEval(score) / EVAL_CAP
    share = math.copysign(math.sqrt(abs(share)), share)
    return round(chart.y + (chart.height - 1) * (1 - share) / 2)


# the ply nearest to x on the graph (clicking or dragging on it)
def graphPly(rect, plies, x):
    chart = graphChart(rect)
    return max(0, min(plies, round((x - chart.x) / max(1, chart.width - 1) * plies)))


# evals: the analysis's evaluations so far (one per ply from the start); plies: the moves of the game;
# marks: ply -> (mark, loss) (a mark's dot sits on the position after its move); shownPly: the position on the board
def drawEvalGraph(screen, rect, evals, plies, marks, shownPly, done=True):
    p.draw.rect(screen, p.Color(UI['infoBox']), rect, border_radius=BUTTON_RADIUS)
    p.draw.rect(screen, p.Color(UI['infoBoxBorder']), rect, 1, border_radius=BUTTON_RADIUS)
    chart = graphChart(rect)
    middle = graphY(rect, 0)
    if evals:
        # Black's share is the background of the analysed part; White's is the area up to the line
        right = graphX(rect, len(evals) - 1, plies)
        p.draw.rect(screen, p.Color(UI['graphBlack']), p.Rect(chart.x, chart.y, right - chart.x + 1, chart.height),
                    border_radius=3)
        points = [(graphX(rect, ply, plies), graphY(rect, score)) for ply, score in enumerate(evals)]
        if len(points) > 1:
            p.draw.polygon(screen, p.Color(UI['graphWhite']),
                           [(chart.x, chart.bottom - 1)] + points + [(right, chart.bottom - 1)])
            p.draw.lines(screen, p.Color(UI['graphEdge']), False, points, 1)
    p.draw.line(screen, p.Color(UI['graphMiddle']), (chart.x, middle), (chart.right - 1, middle), 1)
    x = graphX(rect, shownPly, plies)
    p.draw.line(screen, p.Color(UI['accent']), (x, chart.y), (x, chart.bottom - 1), 2)
    for ply, (mark, _) in marks.items():
        if ply + 1 < len(evals):
            center = (graphX(rect, ply + 1, plies), graphY(rect, evals[ply + 1]))
            p.draw.circle(screen, p.Color(UI['infoBox']), center, 5)
            p.draw.circle(screen, p.Color(UI[MARK_KINDS[mark]]), center, 4)
    if not done:  # the graph fills in as the positions are searched
        textObj = get_text_surface("Analyzing... %d/%d" % (len(evals), plies + 1), scaled(17), UI['textDim'], False)
        box = p.Rect(0, 0, textObj.get_width() + 12, textObj.get_height() + 2)
        box.topright = (chart.right - 2, chart.y + 2)
        p.draw.rect(screen, p.Color(UI['infoBox']), box, border_radius=4)
        screen.blit(textObj, (box.x + 6, box.y + 1))


# what the analysis found, by player: "White: 1 blunder, 2 mistakes · Black: 1 inaccuracy" or "No mistakes found"
# compact: a shorter form for when the words don't fit ("White 1??, 2? · Black 1?!")
def analysisSummary(marks, compact=False):
    if not marks:
        return "No mistakes found"
    words = (("??", "blunder", "blunders"), ("?", "mistake", "mistakes"), ("?!", "inaccuracy", "inaccuracies"))
    parts = []
    for color, name in ((0, "White"), (1, "Black")):
        counts = {mark: 0 for mark in MARK_KINDS}
        for ply, (mark, _) in marks.items():
            if ply % 2 == color:
                counts[mark] += 1
        if compact:
            found = ["%d%s" % (counts[mark], mark) for mark, _, _ in words if counts[mark]]
            parts.append("%s %s" % (name, ", ".join(found) if found else "none"))
        else:
            found = ["%d %s" % (counts[mark], one if counts[mark] == 1 else many)
                     for mark, one, many in words if counts[mark]]
            parts.append("%s: %s" % (name, ", ".join(found) if found else "no mistakes"))
    return " · ".join(parts)


# the shown position, its evaluation and what the analysis says about the move that led to it
# result: the game's result text, shown at the final position (the result card may be hidden)
def drawReviewInfo(screen, rect, moveLog, ply, analysis, marks, isCheckmate, result=None, figurines=None):
    p.draw.rect(screen, p.Color(UI['infoBox']), rect, border_radius=BUTTON_RADIUS)
    p.draw.rect(screen, p.Color(UI['infoBoxBorder']), rect, 1, border_radius=BUTTON_RADIUS)
    evals = analysis['evals'] if analysis else []
    after = "   Checkmate" if isCheckmate else "   Eval " + formatEval(evals[ply]) if ply < len(evals) else ""
    # the first line: "After 12. Nf3   Eval +0.3", the move in figurines when they're on; it shrinks to fit
    width, inset = rect.width - scaled(16), scaled(8)
    for size in range(scaled(17), scaled(11), -1):
        if ply == 0:
            parts = [get_text_surface("Start position" + after, size, UI['text'], True)]
        else:
            i = ply - 1
            move = moveLog[i]
            parts = [get_text_surface("After %d.%s " % (i // 2 + 1, "" if i % 2 == 0 else ".."), size, UI['text'], True),
                     sanSurface(move.san or str(move), 'w' if i % 2 == 0 else 'b', size, UI['text'], True, figurines)]
            if after:
                parts.append(get_text_surface(after, size, UI['text'], True))
        if sum(part.get_width() for part in parts) <= width:
            break
    x, lineHeight = rect.x + inset, max(part.get_height() for part in parts)
    for part in parts:
        screen.blit(part, (x, rect.y + scaled(5) + (lineHeight - part.get_height()) // 2))
        x += part.get_width()

    if ply > 0 and ply - 1 in marks:
        mark, loss = marks[ply - 1]
        kind = {"??": "Blunder", "?": "Mistake", "?!": "Inaccuracy"}[mark]
        second = "%s: loses %.1f. Best was %s" % (kind, loss, analysis['bestSan'][ply - 1])
    elif analysis and not analysis['done']:
        second = "Analyzing the game..."
    elif analysis:
        second = analysisSummary(marks)
        if get_font(scaled(14), False).size(second)[0] > width:
            second = analysisSummary(marks, compact=True)
    else:
        second = result if result and ply == len(moveLog) else "Step through the moves with the arrow keys"
    screen.blit(get_fitting_text(second, width, scaled(16), UI['textDim'], False), (rect.x + inset, rect.y + scaled(29)))


# --- Settings window, drawn over the board like the other windows: a Board tab and a Game tab of settings rows,
# each a label on the left and its choices on the right

SETTINGS_BOX = p.Rect(84, 34, 600, 700)
SETTINGS_LABEL_WIDTH = 160  # the labels' column; the choices take the rest
SETTINGS_TABS = [('board', "Board"), ('game', "Game")]
SETTINGS_ROWS = {'board': ['board', 'pieces', 'coordinates', 'moveMarkers', 'lastMove', 'animation'],
                 'game': ['uiTheme', 'sound', 'volume', 'figurines', 'premoves']}
SETTING_LABELS = {'board': "Board colors", 'pieces': "Pieces", 'coordinates': "Coordinates", 'moveMarkers': "Move hints",
                  'lastMove': "Last move", 'animation': "Animation", 'uiTheme': "Theme", 'sound': "Sound",
                  'volume': "Volume", 'figurines': "Notation", 'premoves': "Premoves"}
# the switches: setting -> its choices as (value, label), in the order shown
SETTING_CHOICES = {
    'coordinates': [(True, "On"), (False, "Off")],
    'moveMarkers': [(True, "On"), (False, "Off")],
    'lastMove': [(True, "On"), (False, "Off")],
    'animation': [('off', "Off"), ('fast', "Fast"), ('normal', "Normal"), ('slow', "Slow")],
    'uiTheme': [('light', "Light"), ('dark', "Dark")],
    'sound': [(True, "On"), (False, "Off")],
    'figurines': [(False, "Letters"), (True, "Figurines")],
    'premoves': [(True, "On"), (False, "Off")],
}
# shown when the pointer rests on a setting's label
SETTING_TIPS = {'board': "Colors of the board's squares", 'pieces': "The look of the pieces",
                'coordinates': "Letters and numbers along the board's edges",
                'moveMarkers': "Dots and rings where the selected piece can go",
                'lastMove': "Color the squares of the last move", 'animation': "How fast the pieces slide",
                'uiTheme': "Colors of the side panel and the windows",
                'sound': "Sounds of moves, checks and the game's start and end",
                'volume': "How loud the sounds are",
                'figurines': "Moves in the list as letters (Nf3) or small pieces",
                'premoves': "Choose your next move while the opponent is thinking"}
VOLUME_STEP = 10
SEGMENT_LABEL_SIZE = 24
PREVIEW_SIZE = 72  # piece previews in the Settings window
PREVIEW_IMAGES = {}  # (folder, piece) -> image, loaded on first use


# a switch value as it appears in rect names: 'on' / 'off' for True / False
def choiceId(value):
    if isinstance(value, bool):
        return 'on' if value else 'off'
    return str(value)


# the saved value of a setting, or its default when the saved one isn't a valid choice
def settingValue(kind):
    value = settings.get(kind)
    if kind == 'board':
        return value if value in BOARD_THEMES else settings.DEFAULTS['board']
    if kind == 'pieces':
        return value if value in PIECE_SETS else settings.DEFAULTS['pieces']
    if kind == 'volume':
        try:
            return max(0, min(100, int(value)))
        except (TypeError, ValueError):
            return settings.DEFAULTS['volume']
    if any(value == choice and type(value) is type(choice) for choice, _ in SETTING_CHOICES[kind]):
        return value
    return settings.DEFAULTS[kind]


# rects of the Settings window's parts, by name: 'tab:board', 'board:Green', 'pieces:Modern', 'coordinates:on',
# 'animation:fast', 'uiTheme:dark', 'volume:-' / 'volume:+', 'close', ... and 'label:<setting>' (not clickable)
def settingsLayout(tab='board'):
    box = SETTINGS_BOX
    x, width = box.x + 40, box.width - 80
    controlsX, controlsWidth = x + SETTINGS_LABEL_WIDTH, width - SETTINGS_LABEL_WIDTH
    rects = {'box': box}
    tabWidth = 150
    for i, (name, _) in enumerate(SETTINGS_TABS):
        rects['tab:' + name] = p.Rect(box.centerx - tabWidth - 4 + i * (tabWidth + 8), box.y + 76, tabWidth, ROW_HEIGHT)
    y = box.y + 150
    for row in SETTINGS_ROWS[tab]:
        height = ROW_HEIGHT
        if row == 'board':  # a swatch per board theme, its name below
            height = 88
            gap = (controlsWidth - len(BOARD_THEMES) * height) // (len(BOARD_THEMES) - 1)
            for i, name in enumerate(BOARD_THEMES):
                rects['board:' + name] = p.Rect(controlsX + i * (height + gap), y, height, height)
        elif row == 'pieces':  # two pieces of each style, its name below
            height = PREVIEW_SIZE
            for i, name in enumerate(PIECE_SETS):
                rects['pieces:' + name] = p.Rect(controlsX + i * (2 * PREVIEW_SIZE + 40), y, 2 * PREVIEW_SIZE, height)
        elif row == 'volume':  # - and + with the value between them
            rects['volume:-'] = p.Rect(controlsX, y, 56, height)
            rects['volume:+'] = p.Rect(controlsX + 56 + 90, y, 56, height)
        else:
            choices = SETTING_CHOICES[row]
            segment = min(120, (controlsWidth - 8 * (len(choices) - 1)) // len(choices))
            for i, (value, _) in enumerate(choices):
                rects['%s:%s' % (row, choiceId(value))] = p.Rect(controlsX + i * (segment + 8), y, segment, height)
        rects['label:' + row] = p.Rect(x, y, SETTINGS_LABEL_WIDTH - 10, height)
        y += height + (44 if row in ('board', 'pieces') else 14)  # the swatches and previews have names below
    rects['close'] = p.Rect(x, box.bottom - 24 - ROW_HEIGHT, width, ROW_HEIGHT)
    return rects


def changeVolume(step):
    settings.put('volume', max(0, min(100, settingValue('volume') + step)))
    settings.put('sound', True)  # changing the volume means the player wants to hear it
    applySoundSettings()
    playSound('move')  # how loud it is now


# applies the choice clicked in the Settings window and remembers it
# returns the tab to show next, or None when the window closes
def settingsClick(location, tab='board'):
    for name, rect in settingsLayout(tab).items():
        if name == 'box' or name.startswith('label:') or not rect.collidepoint(location):
            continue
        if name == 'close':
            return None
        kind, choice = name.split(':')
        if kind == 'tab':
            return choice
        if kind == 'volume':
            if settingsEnabled(name):
                changeVolume(VOLUME_STEP if choice == '+' else -VOLUME_STEP)
        elif kind in SETTING_CHOICES:
            value = next(value for value, _ in SETTING_CHOICES[kind] if choiceId(value) == choice)
            settings.put(kind, value)
            if kind == 'uiTheme':
                setUiTheme(value)
            elif kind == 'sound':
                applySoundSettings()
                if value:
                    playSound('move')
        else:
            settings.put(kind, choice)
            if kind == 'board':
                setBoardTheme(choice)
            else:
                loadImages(choice)
    return tab


# Esc closes the window; Tab and the arrow keys switch tabs
def settingsKey(tab, key):
    if key == p.K_ESCAPE:
        return None
    if key in (p.K_TAB, p.K_LEFT, p.K_RIGHT):
        names = [name for name, _ in SETTINGS_TABS]
        return names[(names.index(tab) + 1) % len(names)]
    return tab


# the volume can't go below 0 or above 100; everything else can always be clicked
def settingsEnabled(name):
    if name == 'volume:-':
        return settingValue('volume') > 0
    if name == 'volume:+':
        return settingValue('volume') < 100
    return True


# what the pointer is over in the Settings window: (id, tooltip or None, clickable), like the game's pointer targets
def settingsPointer(tab, pos):
    for name, rect in settingsLayout(tab).items():
        if name == 'box' or not rect.collidepoint(pos):
            continue
        if name.startswith('label:'):
            return 'settings:' + name, SETTING_TIPS.get(name[len('label:'):]), False
        return 'settings:' + name, None, settingsEnabled(name)
    return None, None, False


def previewImage(folder, piece):
    if (folder, piece) not in PREVIEW_IMAGES:
        PREVIEW_IMAGES[(folder, piece)] = p.transform.smoothscale(
            p.image.load(folder + "/" + piece + ".png"), (PREVIEW_SIZE, PREVIEW_SIZE))
    return PREVIEW_IMAGES[(folder, piece)]


# one choice of a switch (or a tab): the chosen one in the accent color, the others quiet
def drawSegment(screen, rect, text, selected, mouse_pos=(-1, -1), size=SEGMENT_LABEL_SIZE):
    drawButton(screen, rect, text, True, mouse_pos, color=UI['accent'] if selected else UI['segment'], size=size,
               textColor=UI['accentText'] if selected else UI['segmentText'])


def drawSettingsWindow(screen, mouse_pos, tab='board'):
    drawShade(screen)
    rects = settingsLayout(tab)
    box = rects['box']
    drawWindowBox(screen, box)
    titleObj = get_text_surface("Settings", 32, UI['text'])
    screen.blit(titleObj, (box.centerx - titleObj.get_width() / 2, box.y + 22))
    for name, label in SETTINGS_TABS:
        drawSegment(screen, rects['tab:' + name], label, name == tab, mouse_pos, BUTTON_LABEL_SIZE)
    lineY = rects['tab:board'].bottom + 16
    p.draw.line(screen, p.Color(UI['fieldBorder']), (box.x + 24, lineY), (box.right - 25, lineY))

    for row in SETTINGS_ROWS[tab]:
        label = rects['label:' + row]
        labelObj = get_text_surface(SETTING_LABELS[row], 20, UI['text'])
        top = label.y + 10 if row in ('board', 'pieces') else label.centery - labelObj.get_height() / 2
        screen.blit(labelObj, (label.x, top))
        current = settingValue(row)
        if row == 'volume':
            for name in ('volume:-', 'volume:+'):
                rect = rects[name]
                enabled = settingsEnabled(name)
                drawButton(screen, rect, "", enabled, mouse_pos)
                color = p.Color(UI['buttonText'] if enabled else UI['buttonTextDisabled'])
                p.draw.rect(screen, color, p.Rect(rect.centerx - 9, rect.centery - 1, 18, 4))  # the minus
                if name == 'volume:+':
                    p.draw.rect(screen, color, p.Rect(rect.centerx - 2, rect.centery - 8, 4, 18))
            between = p.Rect(rects['volume:-'].right, rects['volume:-'].y, 90, ROW_HEIGHT)
            soundOn = settingValue('sound')
            valueObj = get_text_surface("%d%%" % current if soundOn else "Muted", 20,
                                        UI['text'] if soundOn else UI['textDim'], soundOn)
            screen.blit(valueObj, (between.centerx - valueObj.get_width() / 2, between.centery - valueObj.get_height() / 2))
        elif row == 'uiTheme':  # a sample of each theme's panel: its background, edge and text
            for value, text in SETTING_CHOICES[row]:
                rect = rects['uiTheme:' + value]
                palette = PALETTES[value]
                p.draw.rect(screen, p.Color(palette['panel']), rect, border_radius=BUTTON_RADIUS)
                p.draw.rect(screen, p.Color(palette['stripLine']), rect, 1, border_radius=BUTTON_RADIUS)
                nameObj = get_text_surface(text, SEGMENT_LABEL_SIZE, palette['text'], sans=True)
                screen.blit(nameObj, (rect.centerx - nameObj.get_width() / 2, rect.centery - nameObj.get_height() / 2 + 1))
                if current == value:
                    p.draw.rect(screen, p.Color(UI['accent']), rect.inflate(10, 10), 4, border_radius=BUTTON_RADIUS + 4)
                elif rect.collidepoint(mouse_pos):
                    p.draw.rect(screen, p.Color(UI['hoverOutline']), rect.inflate(10, 10), 2,
                                border_radius=BUTTON_RADIUS + 4)
        elif row in ('board', 'pieces'):
            for choice in (BOARD_THEMES if row == 'board' else PIECE_SETS):
                rect = rects[row + ':' + choice]
                if row == 'board':  # a 2x2 corner of the board in these colors
                    half = rect.width // 2
                    for r in range(2):
                        for c in range(2):
                            p.draw.rect(screen, BOARD_THEMES[choice][(r + c) % 2],
                                        (rect.x + c * half, rect.y + r * half, half, half))
                else:  # a white king and a black knight of this style, on the chosen board colors
                    for i, piece in enumerate(('wK', 'bN')):
                        square = p.Rect(rect.x + i * PREVIEW_SIZE, rect.y, PREVIEW_SIZE, PREVIEW_SIZE)
                        p.draw.rect(screen, BOARD_COLORS[i], square)
                        screen.blit(previewImage(PIECE_SETS[choice], piece), square.topleft)
                if current == choice:
                    p.draw.rect(screen, p.Color(UI['accent']), rect.inflate(10, 10), 4)
                elif rect.collidepoint(mouse_pos):
                    p.draw.rect(screen, p.Color(UI['hoverOutline']), rect.inflate(10, 10), 2)
                nameObj = get_text_surface(choice, 18, UI['text'] if current == choice else UI['textDim'],
                                           current == choice)
                screen.blit(nameObj, (rect.centerx - nameObj.get_width() / 2, rect.bottom + 9))
        else:
            for value, text in SETTING_CHOICES[row]:
                drawSegment(screen, rects['%s:%s' % (row, choiceId(value))], text, current == value, mouse_pos)

    drawButton(screen, rects['close'], "Close", True, mouse_pos)


# --- tooltips and the pointer's look

TOOLTIP_DELAY_MS = 600  # the pointer rests on a control this long before its tooltip shows
TOOLTIP_SIZE = 22  # sans font
# what each panel control does; names as in panelRows()
TOOLTIPS = {
    'mode': "Play the computer, a friend here, or online",
    'level': "How strong the computer plays",
    'side': "Your color against the computer",
    'clock': "Time for each player: minutes + seconds per move",
    'hint': "Show a good move on the board",
    'room': "Type or paste the room code your friend sent",
    'host': "Create a room and play White",
    'join': "Join this room and play Black",
    'rejoin': "Go back to your last room",
    'invite': "Copy an invite link to send your friend",
    'chat': "Send your opponent a quick message",
    'save': "Save this game as a PGN file",
    'load': "Open a game from a PGN file",
    'help': "How to play (H)",
    'resign': "Give up this game",
    'draw': "Offer your opponent a draw",
    'analyze': "Let the computer mark the mistakes",
    'graph': "Click or drag to see that move",
    'first': "First move", 'prev': "Previous move (Left)", 'next': "Next move (Right)", 'last': "Last move",
    'undo': "Undo (Z)",
    'restart': "Restart (R)",
    'account': "Sign in to save games and get rated",
    'menu': "More: save, load, flip board, settings, help",
    'flip': "Turn the board around (F)",
    'settings': "Board, pieces, theme and sound",
}


# the tooltip of an enabled panel control; online, Undo asks the opponent and Restart leaves the room
def tooltipText(name, connected=False, signedIn=False):
    if connected and name == 'undo':
        return "Ask your opponent to undo (Z)"
    if connected and name == 'restart':
        return "Leave the room"
    if signedIn and name == 'account':
        return "Your games, record and rating"
    return TOOLTIPS.get(name)


# why a panel control can't be clicked right now (None when it can, or no reason applies)
# shown as its tooltip, and in the status slot when it's clicked anyway (touch screens have no hover)
def disabledReason(name, gameOver=False, online=False, connected=False, humanTurn=True, hintsLeft=1,
                   hintBusy=False, prompt=False, analysis=None, moves=0, atStart=False, atEnd=False, roomCode="",
                   chatWait=False):
    if name == 'hint':
        if gameOver:
            return "The game is over"
        if online:
            return "Hints are off in online games"
        if hintsLeft <= 0:
            return "No hints left today"
        if hintBusy:
            return "Looking for a good move..."
        if not humanTurn:
            return "Wait for your turn"
    elif name in ('resign', 'draw'):
        if gameOver:
            return "The game is over"
        if online and not connected:
            return "Join a room first"
        if name == 'draw' and prompt:
            return "Answer the open question first"
    elif name == 'undo' and online and not connected:
        return "No game yet"
    elif name == 'save' and moves == 0:
        return "Make a move first"
    elif name == 'load' and online:
        return "Leave online play first"
    elif name == 'join' and not roomCode:
        return "Type a room code first"
    elif name == 'chat' and chatWait:
        return "Wait a moment"
    elif name == 'analyze':
        if moves == 0:
            return "Make a move first"
        return "The game is already analyzed" if analysis == 'done' else "The analysis is running"
    elif name in ('first', 'prev') and atStart:
        return "This is the start of the game"
    elif name in ('next', 'last') and atEnd:
        return "This is the final position"
    return None


# where a tooltip for text goes with the pointer at pos: below and right of it, kept inside the screen
def tooltipRect(text, pos, screenSize):
    width, height = get_font(scaled(TOOLTIP_SIZE), True, True).size(text)
    rect = p.Rect(pos[0] + 12, pos[1] + 22, width + 18, height + 12)
    if rect.bottom > screenSize[1] - 4:
        rect.bottom = pos[1] - 10  # above the pointer instead
    rect.clamp_ip(p.Rect(4, 4, screenSize[0] - 8, screenSize[1] - 8))
    return rect


def drawTooltip(screen, text, pos):
    rect = tooltipRect(text, pos, screen.get_size())
    p.draw.rect(screen, p.Color(UI['tooltipBg']), rect, border_radius=6)
    p.draw.rect(screen, p.Color(*shadeColor(UI['tooltipBg'], 40 if sum(UI['tooltipBg']) < 384 else -40)), rect, 1,
                border_radius=6)
    textObj = get_text_surface(text, scaled(TOOLTIP_SIZE), UI['tooltipText'], sans=True)
    screen.blit(textObj, (rect.x + 9, rect.centery - textObj.get_height() / 2 + 1))
    return rect


CURSOR = ['arrow']  # the pointer's current look: 'hand' over anything clickable, 'ibeam' over text fields, else 'arrow'
SYSTEM_CURSORS = {'hand': 'SYSTEM_CURSOR_HAND', 'ibeam': 'SYSTEM_CURSOR_IBEAM', 'arrow': 'SYSTEM_CURSOR_ARROW'}


# changes the pointer's look, only when it should look different; some platforms (or pygame builds) can't
def setCursor(kind):
    if CURSOR[0] == kind:
        return
    CURSOR[0] = kind
    try:
        cursor = getattr(p, SYSTEM_CURSORS.get(kind, ''), p.SYSTEM_CURSOR_ARROW)
        try:
            p.mouse.set_cursor(cursor)
        except TypeError:  # pygame 2.0.0 sets system cursors only through set_system_cursor
            p.mouse.set_system_cursor(cursor)
    except Exception:  # e.g. no cursor support (headless)
        pass


# a check mark at the left of a button, for the current choice in a dropdown
def drawCheckMark(screen, rect):
    x, y = rect.x + scaled(12), rect.centery
    p.draw.lines(screen, p.Color(UI['buttonText']), False, [(x, y), (x + scaled(6), y + scaled(6)),
                                                             (x + scaled(17), y - scaled(7))], 3)


# three lines, for the menu button
def drawMenuIcon(screen, rect):
    color = p.Color(UI['buttonText'])
    for dy in (-7, 0, 7):
        p.draw.rect(screen, color, p.Rect(rect.centerx - scaled(10), rect.centery + scaled(dy) - 1, scaled(20), 3),
                    border_radius=1)


# the open menu's items over the panel, like dropdown options; states: which can be clicked (controlStates)
def drawMenu(screen, menuRect, states, mouse_pos):
    drawPopup(screen, menuItemRects(menuRect), dict(MENU_ITEMS), states, mouse_pos)


# a list opened from a button (popupItemRects): its frame and its items as buttons, with one label size
def drawPopup(screen, rects, labels, states, mouse_pos):
    box = popupBoxRect(rects)
    p.draw.rect(screen, p.Color(UI['window']), box, border_radius=BUTTON_RADIUS + 4)
    p.draw.rect(screen, p.Color(UI['windowBorder']), box, 2, border_radius=BUTTON_RADIUS + 4)
    names = list(rects)
    size = evenLabelSizes([names], rects, labels)[names[0]]
    for name, rect in rects.items():
        drawButton(screen, rect, labels[name], states.get(name, True), mouse_pos, size=size)


def drawNavIcon(screen, rect, name):
    cx, cy = rect.center
    white = p.Color(UI['buttonText'])
    s = scaled
    if name in ('first', 'prev'):
        tip = cx - s(5) if name == 'prev' else cx - s(3)
        p.draw.polygon(screen, white, [(tip, cy), (tip + s(11), cy - s(8)), (tip + s(11), cy + s(8))])
        if name == 'first':
            p.draw.rect(screen, white, p.Rect(tip - s(5), cy - s(8), s(3), 2 * s(8) + 1))
    else:
        tip = cx + s(5) if name == 'next' else cx + s(3)
        p.draw.polygon(screen, white, [(tip, cy), (tip - s(11), cy - s(8)), (tip - s(11), cy + s(8))])
        if name == 'last':
            p.draw.rect(screen, white, p.Rect(tip + s(3), cy - s(8), s(3), 2 * s(8) + 1))


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
    # the piece's position comes from the time passed, so the speed doesn't depend on the computer
    duration = animationDuration(move)
    if duration <= 0:  # animation is off
        return
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
# (on the canvas, in the middle of the board; as large as the panel's buttons in portrait, for touch)
def resultCardLayout(text, buttons):
    titleObj = get_fitting_text(text, BOARD_WIDTH - 120, scaled(42), "white")
    noteObj = get_text_surface(RESULT_CARD_NOTE, scaled(17), (205, 205, 205), False)
    buttonWidth, gap, rowHeight = scaled(170), scaled(16), LAYOUT.rowHeight
    rowWidth = len(buttons) * buttonWidth + (len(buttons) - 1) * gap
    width = max(titleObj.get_width(), noteObj.get_width(), rowWidth) + scaled(60)
    height = scaled(18) + titleObj.get_height() + 4 + noteObj.get_height() + scaled(16) + rowHeight + scaled(22)
    card = p.Rect(0, 0, width, height)
    card.center = LAYOUT.board.center
    rects = {'card': card}
    x = card.centerx - rowWidth // 2
    for i, name in enumerate(buttons):
        rects[name] = p.Rect(x + i * (buttonWidth + gap), card.bottom - scaled(22) - rowHeight, buttonWidth, rowHeight)
    return titleObj, noteObj, rects


# --- what other players send: anyone with the room's code can post to it, so nothing from it may stop the game

# the opponent's {'uid', 'name', 'rating'} from a message's 'player' field, or None when it has none or it doesn't
# make sense (a name keeps only the characters usernames have)
def onlinePlayerInfo(player):
    if not isinstance(player, dict) or not player.get('uid'):
        return None
    rating = player.get('rating') or 0
    if isinstance(rating, bool) or not isinstance(rating, (int, float)) or not -1e6 < rating < 1e6:
        return None  # also NaN and infinity
    name = "".join(ch for ch in str(player.get('name') or "") if ch in USERNAME_CHARACTERS)[:20]
    return {'uid': str(player['uid'])[:64], 'name': name or "?", 'rating': int(rating)}


# whether a received state can be adopted: a time control of two whole seconds counts (or none), clocks in ms,
# a result of two printable texts, the moves a text (a modified client's message would otherwise stop the game)
def wellFormedState(msg):
    def number(x, low):
        return not isinstance(x, bool) and isinstance(x, (int, float)) and low <= x < 1e12  # not NaN or infinity
    tc, clocks, result = msg.get('tc'), msg.get('clocks'), msg.get('result')
    if tc is not None and not (isinstance(tc, list) and len(tc) == 2 and all(number(x, 0) for x in tc)):
        return False
    if clocks is not None and not (isinstance(clocks, dict) and all(number(clocks.get(c, 0), -1e12) for c in 'wb')):
        return False
    if result is not None and not (isinstance(result, list) and len(result) == 2
                                   and all(isinstance(x, str) and len(x) <= 100 and x.isprintable() for x in result)):
        return False
    return isinstance(msg.get('moves') or "", str)


# what the online status line says: (text, palette key of its color, note for the opponent's name or None)
# role: ours; opponentSeen: server time of the opponent's latest message (None before any); serverTime: the latest
# server time of any message in the room, ours included (we ping when quiet, so it keeps up); networkStatus: net.last_status
def presenceStatus(role, opponentSeen, serverTime, networkStatus):
    if "HEALTHY" not in networkStatus and "READY" not in networkStatus:
        return "Connecting to the server...", 'warning', None
    if opponentSeen is None:
        if role == 'host':
            return "Waiting for your opponent: send the link or the code", 'textDim', "not here yet"
        return "Waiting for the host to answer...", 'textDim', "not here yet"
    silent = serverTime - opponentSeen
    if silent <= OPPONENT_GONE_SECONDS:
        return "Opponent connected", 'success', None
    return "Opponent silent for %d min: they may have left" % max(1, silent // 60), 'error', "may have left"


# --- invite links and the quick chat

COPY_WAIT_MS = 3000  # browser: how long Copy link waits for the clipboard's answer before saying it failed


# the link that opens the game with the room's Join prompt (site: browser.siteUrl(), the public site on desktop)
def inviteUrl(site, code):
    return site + ('&' if '?' in site else '?') + 'room=' + code


# the QUICK_CHAT index a received message shows, or None: only a chat from the opponent's role with a known id,
# sent within CHAT_FRESH_SECONDS of the room's latest server time and of when we joined (joinedAt; None while
# we haven't heard our own sync_request back: until then the room's history is still arriving)
def incomingChat(msg, opponentRole, serverTime, joinedAt):
    if msg.get('type') != 'chat' or msg.get('role') != opponentRole:
        return None
    index, sent = msg.get('id'), msg.get('_time')
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(QUICK_CHAT):
        return None
    if isinstance(sent, bool) or not isinstance(sent, (int, float)) or not isinstance(serverTime, (int, float)):
        return None
    if not isinstance(joinedAt, (int, float)) or sent < joinedAt - CHAT_FRESH_SECONDS:
        return None
    return index if serverTime - sent <= CHAT_FRESH_SECONDS else None


# whether another chat message may go out now (ticks), the last one having gone at lastSent (None: none yet)
def chatReady(now, lastSent):
    return lastSent is None or now - lastSent >= CHAT_INTERVAL_MS


CHAT_TEXT_SIZE = 24  # sans (pygame's default font, which runs small)
CHAT_TAIL = 8  # how far the bubble's tail reaches toward the strip


# (bubble rect, tail triangle) of a chat message next to the player strip at stripY: below it for the strip at the
# top of the panel, above it for the one at the bottom; the tail points at the strip's color marker. It stays in
# the panel, over the move list, so it never covers the board or the controls.
# lift: px it rises above the lower strip, to clear the status slot while a message shows there
# span: portrait, where the strips lie above and below the board: the bubble goes inside the strip instead, in
# this free span after the name (drawPlayerStrip), its tail pointing back at the name (it never runs past the span)
def chatBubbleLayout(text, stripY, below, lift=0, span=None):
    width = min(get_font(scaled(CHAT_TEXT_SIZE), True, True).size(text)[0] + scaled(28), LAYOUT.controlsWidth)
    if span is not None:
        left, right = span[0] + CHAT_TAIL + scaled(6), span[1] - scaled(6)
        rect = p.Rect(left, 0, max(min(width, right - left), scaled(60)), scaled(36))
        rect.x = min(left, right - rect.width)  # after a very long name it covers the name's end, not the clock
        rect.centery = stripY + LAYOUT.stripHeight // 2
        tail = [(rect.x + 1, rect.centery - 6), (rect.x + 1, rect.centery + 6), (rect.x - CHAT_TAIL, rect.centery)]
        return rect, tail
    rect = p.Rect(LAYOUT.panel.x + scaled(10), 0, width, scaled(36))
    tipX = LAYOUT.panel.x + scaled(18)  # under or over the strip's color marker
    if below:
        rect.top = stripY + LAYOUT.stripHeight + CHAT_TAIL + 2
        tail = [(tipX - 4, rect.top + 1), (tipX + 10, rect.top + 1), (tipX, rect.top - CHAT_TAIL)]
    else:
        rect.bottom = stripY - CHAT_TAIL - 2 - lift
        tail = [(tipX - 4, rect.bottom - 2), (tipX + 10, rect.bottom - 2), (tipX, rect.bottom + CHAT_TAIL)]
    return rect, tail


# landscape: px the lower strip's bubble rises (chatBubbleLayout's lift) to clear what lies just above that strip
# (areas: panelAreas): the status message while one shows, and the review info after the game (the status slot is
# above the info then)
def chatBubbleLift(areas, statusShown, gameOver):
    stripY = areas['bottomStrip'].y
    if statusShown:
        return stripY - areas['status'].y
    return stripY - areas['info'].y if gameOver else 0


# age: ms since the message came; it fades out over the last CHAT_FADE_MS of CHAT_BUBBLE_MS
def drawChatBubble(screen, text, stripY, below, age=0, lift=0, span=None):
    rect, tail = chatBubbleLayout(text, stripY, below, lift, span)
    xs, ys = [x for x, _ in tail], [y for _, y in tail]
    area = rect.union(p.Rect(min(xs) - 2, min(ys) - 2, max(xs) - min(xs) + 4, max(ys) - min(ys) + 4))
    layer = p.Surface(area.size, p.SRCALPHA)
    local = rect.move(-area.x, -area.y)
    localTail = [(x - area.x, y - area.y) for x, y in tail]
    # the tail's border: the tail shifted 1 px toward its tip (left in a strip, else up or down)
    shift = (-1, 0) if span is not None else (0, -1 if below else 1)
    p.draw.polygon(layer, UI['bubbleBorder'], [(x + shift[0], y + shift[1]) for x, y in localTail])
    p.draw.rect(layer, UI['bubble'], local, border_radius=12)
    p.draw.rect(layer, UI['bubbleBorder'], local, 1, border_radius=12)
    p.draw.polygon(layer, UI['bubble'], localTail)
    textObj = get_fitting_text(text, rect.width - scaled(28), scaled(CHAT_TEXT_SIZE), UI['bubbleText'], sans=True)
    layer.blit(textObj, (local.x + scaled(14), local.centery - textObj.get_height() / 2 + 1))
    left = CHAT_BUBBLE_MS - age
    if left < CHAT_FADE_MS:
        layer.set_alpha(max(0, round(255 * left / CHAT_FADE_MS)))
    screen.blit(layer, area.topleft)
    return rect


# the open quick chat list over the panel, like the menu
def drawChatList(screen, chatRect, mouse_pos):
    rects = chatItemRects(chatRect)
    drawPopup(screen, rects, dict(enumerate(QUICK_CHAT)), {}, mouse_pos)


# the result on a dark card in the middle of the board, so it reads over any position, with buttons for what's next
def drawEndGameText(screen, text, buttons, mouse_pos):
    titleObj, noteObj, rects = resultCardLayout(text, buttons)
    card = rects['card']
    shade = p.Surface(card.size, p.SRCALPHA)
    p.draw.rect(shade, (30, 30, 30, 215), shade.get_rect(), border_radius=14)
    screen.blit(shade, card.topleft)
    screen.blit(titleObj, (card.centerx - titleObj.get_width() / 2, card.y + scaled(18)))
    screen.blit(noteObj, (card.centerx - noteObj.get_width() / 2, card.y + scaled(18) + 4 + titleObj.get_height()))
    for name in buttons:
        drawButton(screen, rects[name], RESULT_BUTTONS[name], True, mouse_pos, size=LAYOUT.labelSize)


# what the Looking back banner says while the board shows the position after ply moves of moveLog
def lookBackText(moveLog, ply):
    if ply == 0:
        shown = "the start position"
    else:
        i = ply - 1
        shown = "after %d.%s %s" % (i // 2 + 1, "" if i % 2 == 0 else "..", moveLog[i].san or str(moveLog[i]))
    return "Looking back: %s  -  click here or press End to return" % shown


# a see-through bar across the top of the board, in the theme's colors, so the pieces under it still show
# (on the board's surface; LAYOUT.banner, which is LOOK_BACK_BANNER in landscape)
def drawLookBackBanner(screen, text):
    rect = LAYOUT.banner
    layer = p.Surface(rect.size, p.SRCALPHA)
    layer.fill(UI['bannerBg'])
    screen.blit(layer, rect.topleft)
    textObj = get_fitting_text(text, rect.width - 24, scaled(22), UI['bannerText'], True, sans=True)
    screen.blit(textObj, (rect.centerx - textObj.get_width() / 2, rect.centery - textObj.get_height() / 2))


# a separate GameState with the same moves, for searching in the background while gs stays on screen
def copyGame(gs):
    board = GameState()
    if board.playerWantsToPlayAsBlack:
        board.board = board.board1
    for move in gs.moveLog:
        board.makeMove(move)
    return board


# the moves the player (not to move in gs) could choose as a premove: those that would be legal if it were their
# turn now. En passant is left out (the opponent's coming move decides it), and so is taking the king (when the
# player is giving check), which can never become legal
def premoveMoves(gs):
    board = copyGame(gs)
    board.whiteToMove = not board.whiteToMove
    board.enpasantPossible = ()
    return [move for move in board.getValidMoves() if move.pieceCaptured[1:] != 'K']


# what becomes of a premove (start, end) once it's the player's turn: the legal move to play (a promotion stays
# a queen), or None when it isn't legal any more and is dropped
def resolvePremove(premove, validMoves):
    start, end = premove
    for move in validMoves:
        if (move.startRow, move.startCol) == tuple(start) and (move.endRow, move.endCol) == tuple(end):
            return move
    return None


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



setLayout('landscape')  # the live LAYOUT (see Layout): here, as it reads constants from all over the module


# if we import main then main function wont run it will run only while running this file
if __name__ == "__main__":
    asyncio.run(main())
