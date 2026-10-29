'''
    The AI: NegaMax with alpha-beta pruning, searched one depth at a time (iterative deepening)
    until the time budget of the difficulty level runs out.

    - quiescence search: at the end of the main search, captures and promotions are followed
      until the position is quiet, so trades aren't misjudged at the edge of the search
    - transposition table: positions already searched keep their score and best move, which is
      tried first the next time (by far the biggest help to alpha-beta)
    - move ordering by killer moves and history, null move pruning and late move reductions, so the
      same time reaches deeper; a depth cut off by the clock still contributes its best move so far
    - opening book: the first moves come from common opening lines, picked at random
    - LEVEL (0-4) picks the time budget, depth limit and randomness from LEVELS
'''


import random
import asyncio
import time
from engine import GameState

pieceScore = {"K": 0, "Q": 9, "R": 5, "B": 3, "N": 3, "p": 1}

knightScores = [[1, 1, 1, 1, 1, 1, 1, 1],
                [1, 2, 2, 2, 2, 2, 2, 1],
                [1, 2, 3, 3, 3, 3, 2, 1],
                [1, 2, 3, 4, 4, 3, 2, 1],
                [1, 2, 3, 4, 4, 3, 2, 1],
                [1, 2, 3, 3, 3, 3, 2, 1],
                [1, 2, 2, 2, 2, 2, 2, 1],
                [1, 1, 1, 1, 1, 1, 1, 1]]

bishopScores = [[4, 3, 2, 1, 1, 2, 3, 4],
                [3, 4, 3, 2, 2, 3, 4, 3],
                [2, 3, 4, 3, 3, 4, 3, 2],
                [1, 2, 3, 4, 4, 3, 2, 1],
                [1, 2, 3, 4, 4, 3, 2, 1],
                [2, 3, 4, 3, 3, 4, 3, 2],
                [3, 4, 3, 2, 2, 3, 4, 3],
                [4, 3, 2, 1, 1, 2, 3, 4]]

queenScores = [[1, 1, 1, 3, 1, 1, 1, 1],
               [1, 2, 3, 3, 3, 1, 1, 1],
               [1, 4, 3, 3, 3, 4, 2, 1],
               [1, 2, 3, 3, 3, 2, 2, 1],
               [1, 2, 3, 3, 3, 2, 2, 1],
               [1, 4, 3, 3, 3, 4, 2, 1],
               [1, 1, 2, 3, 3, 1, 1, 1],
               [1, 1, 1, 3, 1, 1, 1, 1]]

rookScores = [[4, 3, 4, 4, 4, 4, 3, 4],
              [4, 4, 4, 4, 4, 4, 4, 4],
              [1, 1, 2, 3, 3, 2, 1, 1],
              [1, 2, 3, 4, 4, 3, 2, 1],
              [1, 2, 3, 4, 4, 3, 2, 1],
              [1, 1, 2, 2, 2, 2, 1, 1],
              [4, 4, 4, 4, 4, 4, 4, 4],
              [4, 3, 2, 1, 1, 2, 3, 4]]

whitePawnScores = [[8, 8, 8, 8, 8, 8, 8, 8],
                   [8, 8, 8, 8, 8, 8, 8, 8],
                   [5, 6, 6, 7, 7, 6, 6, 5],
                   [2, 3, 3, 5, 5, 3, 3, 2],
                   [1, 2, 3, 4, 4, 3, 2, 1],
                   [1, 1, 2, 3, 3, 2, 1, 1],
                   [1, 1, 1, 0, 0, 1, 1, 1],
                   [0, 0, 0, 0, 0, 0, 0, 0]]

blackPawnScores = [[0, 0, 0, 0, 0, 0, 0, 0],
                   [1, 1, 1, 0, 0, 1, 1, 1],
                   [1, 1, 2, 3, 3, 2, 1, 1],
                   [1, 2, 3, 4, 4, 3, 2, 1],
                   [2, 3, 3, 5, 5, 3, 3, 2],
                   [5, 6, 6, 7, 7, 6, 6, 5],
                   [8, 8, 8, 8, 8, 8, 8, 8],
                   [8, 8, 8, 8, 8, 8, 8, 8]]

# the king hides behind its pawns while queens and rooks are around (white's view, row 7 is its back rank)...
kingMiddleScores = [[-3, -3, -3, -3, -3, -3, -3, -3],
                    [-3, -3, -3, -3, -3, -3, -3, -3],
                    [-3, -3, -3, -3, -3, -3, -3, -3],
                    [-3, -3, -3, -3, -3, -3, -3, -3],
                    [-3, -3, -3, -3, -3, -3, -3, -3],
                    [-2, -2, -2, -2, -2, -2, -2, -2],
                    [0, 0, -1, -1, -1, -1, 0, 0],
                    [2, 3, 1, 0, 0, 1, 3, 2]]

# ...and walks to the center in the endgame
kingEndScores = [[0, 1, 2, 3, 3, 2, 1, 0],
                 [1, 2, 3, 4, 4, 3, 2, 1],
                 [2, 3, 4, 5, 5, 4, 3, 2],
                 [3, 4, 5, 6, 6, 5, 4, 3],
                 [3, 4, 5, 6, 6, 5, 4, 3],
                 [2, 3, 4, 5, 5, 4, 3, 2],
                 [1, 2, 3, 4, 4, 3, 2, 1],
                 [0, 1, 2, 3, 3, 2, 1, 0]]


piecePositionScores = {"N": knightScores, "B": bishopScores, "Q": queenScores,
                       "R": rookScores, "wp": whitePawnScores, "bp": blackPawnScores}

ENDGAME_MATERIAL = 14  # queens, rooks and minor pieces of both sides at or below this count as an endgame


CHECKMATE = 1000
STALEMATE = 0
INFINITY = 10 ** 6
MATE_THRESHOLD = CHECKMATE - 200  # scores beyond this are forced mates

# (name, seconds to think, depth limit or None, random noise in pawns added to each move's score)
LEVELS = [("Easy", 0.3, 1, 1.5),
          ("Normal", 0.6, 2, 0.4),
          ("Hard", 1.2, 3, 0),
          ("Very Hard", 2.5, None, 0),
          ("Impossible", 5.0, None, 0)]
LEVEL = 1  # index into LEVELS, set from the difficulty dropdown

MAX_QUIESCENCE_DEPTH = 8
NULL_MOVE_MIN_DEPTH = 3  # null move pruning from this depth...
NULL_MOVE_REDUCTION = 2  # ...searching the null move this much shallower
LMR_MIN_DEPTH = 3  # late move reductions from this depth, for quiet moves after the first LMR_MIN_INDEX
LMR_MIN_INDEX = 3
YIELD_SECONDS = 0.03  # give the browser a turn at least this often while searching
TT_MAX_ENTRIES = 200000

# transposition table: position key -> (depth, score, bound, best move id)
EXACT, LOWER, UPPER = 0, 1, 2
transpositionTable = {}


class SearchTimeout(Exception):
    pass


def findRandomMoves(validMoves):
    return validMoves[random.randint(0, len(validMoves) - 1)]


# returns the AI's move: from the opening book while it lasts, then from a search within the level's time budget
# history: position keys of the game so far, so the search can see repetitions
async def findBestMove(gs, validMoves, level=None, history=(), useBook=True):
    if not validMoves:
        return None
    name, seconds, maxDepth, noise = LEVELS[LEVEL if level is None else level]
    if len(validMoves) == 1:
        return validMoves[0]  # nothing to think about
    if useBook:
        move = bookMove(gs, validMoves)
        if move is not None:
            print(f"AI: {move} from the opening book")
            return move
    score, move, depth = await searchPosition(gs, validMoves, seconds, maxDepth, noise, history)
    print(f"AI ({name}): {move} score {score:.2f} depth {depth}")
    return move


# iterative deepening: search depth 1, 2, 3... until the time runs out or maxDepth is reached
# returns (score for the side to move in pawns, best move, depth reached); restores gs before returning
async def searchPosition(gs, validMoves, seconds, maxDepth=None, noise=0, history=()):
    if not validMoves:
        return (-CHECKMATE if gs.inCheck else STALEMATE), None, 0
    search = Search(gs, history)
    startLength = len(gs.moveLog)
    start = time.time()
    moves = list(validMoves)
    random.shuffle(moves)  # equal moves come out in a different order every game
    bestScore, bestMove, depth = 0, None, 0
    while maxDepth is None or depth < maxDepth:
        # depth 1 always finishes, so there is a move to play
        search.deadline = start + seconds if depth >= 1 else None
        try:
            score, move = await search.root(depth + 1, moves, bestMove, noise)
        except SearchTimeout:
            while len(gs.moveLog) > startLength:
                gs.undoMove()
            if search.rootBestMove is not None:
                # the unfinished depth searched the previous best move first, so the best move it found so
                # far is at least as good: the time spent on it isn't wasted
                bestScore, bestMove = search.rootBestScore, search.rootBestMove
            break
        bestScore, bestMove, depth = score, move, depth + 1
        if abs(score) > MATE_THRESHOLD:
            break  # a forced mate was found, searching deeper won't change it
    gs.getValidMoves()  # the search leaves check and pin flags from deeper positions behind
    return bestScore, bestMove, depth


class Search:
    def __init__(self, gs, history):
        self.gs = gs
        self.history = set(history)  # positions already played in the game
        self.path = []  # positions on the way to the current node
        self.deadline = None
        self.maxExtendedPly = 0
        self.nodes = 0
        self.lastYield = time.time()
        self.rootBestScore, self.rootBestMove = -INFINITY, None  # best so far in the depth being searched
        self.killers = {}  # ply -> ids of the two latest quiet moves that caused a cutoff there
        self.historyScores = {}  # (piece, end row, end col) -> how often and how deep such quiet moves cut off
        self.nullSaved = []  # en passant squares put aside by null moves

    async def tick(self):
        self.nodes += 1
        if self.nodes & 63 == 0:
            now = time.time()
            if self.deadline is not None and now > self.deadline:
                raise SearchTimeout()
            if now - self.lastYield > YIELD_SECONDS:
                await asyncio.sleep(0)  # Yield for browser UI
                self.lastYield = time.time()

    def evaluate(self):  # from the side to move's point of view
        score = scoreBoard(self.gs)
        return score if self.gs.whiteToMove else -score

    async def root(self, depth, moves, previousBest, noise):
        gs = self.gs
        rootKey = gs.getPositionKey()
        entry = transpositionTable.get(rootKey)
        orderMoves(moves, previousBest.moveID if previousBest else (entry[3] if entry else None))
        self.path = [rootKey]
        self.maxExtendedPly = 2 * depth + 2  # stops a long run of checks from extending forever
        alpha = -INFINITY
        bestScore, bestMove = -INFINITY, None
        self.rootBestScore, self.rootBestMove = -INFINITY, None
        for move in moves:
            gs.makeMove(move)
            if noise:
                # every move needs its exact score before the noise is added
                score = -await self.negamax(depth - 1, 1, -INFINITY, INFINITY) + random.uniform(-noise, noise)
            else:
                score = -await self.negamax(depth - 1, 1, -INFINITY, -alpha)
            gs.undoMove()
            if score > bestScore:
                bestScore, bestMove = score, move
                self.rootBestScore, self.rootBestMove = score, move
            if score > alpha:
                alpha = score
        if not noise:
            storeEntry(rootKey, depth, toTableScore(bestScore, 0), EXACT, bestMove.moveID)
        return bestScore, bestMove

    async def negamax(self, depth, ply, alpha, beta, allowNull=True):
        await self.tick()
        gs = self.gs
        key = gs.getPositionKey()
        if key in self.path or key in self.history:
            return STALEMATE  # a repeated position heads for a draw
        moves = gs.getValidMoves()
        if not moves:
            # being mated later is less bad, so the winning side goes for the quickest mate
            return -(CHECKMATE - ply) if gs.inCheck else STALEMATE
        inCheck = gs.inCheck  # gs.inCheck changes as soon as a reply is searched
        if inCheck and ply < self.maxExtendedPly:
            depth += 1  # check extension: forcing lines (like mating attacks) are followed further
        if depth <= 0:
            return await self.quiesce(alpha, beta, ply, moves, 0)

        entry = transpositionTable.get(key)
        tableMoveId = None
        if entry is not None:
            entryDepth, entryScore, bound, tableMoveId = entry
            if entryDepth >= depth:
                score = fromTableScore(entryScore, ply)
                if bound == EXACT or (bound == LOWER and score >= beta) or (bound == UPPER and score <= alpha):
                    return score

        self.path.append(key)
        # null move: let the opponent move twice; if we are still above beta, a real move surely is too, so
        # this line is cut off after a much shallower search (not in check, and not with only king and pawns,
        # where passing can be the better choice - zugzwang)
        if (allowNull and depth >= NULL_MOVE_MIN_DEPTH and not inCheck and beta < MATE_THRESHOLD
                and hasPieces(gs)):
            self.makeNullMove()
            try:
                score = -await self.negamax(depth - 1 - NULL_MOVE_REDUCTION, ply + 1, -beta, -beta + 1, False)
            finally:
                self.undoNullMove()
            if score >= beta:
                self.path.pop()
                return beta

        killers = self.killers.get(ply, ())
        orderMoves(moves, tableMoveId, killers, self.historyScores)
        alphaOriginal = alpha
        bestScore, bestMoveId = -INFINITY, None
        for index, move in enumerate(moves):
            quiet = not move.isCapture and not move.isPawnPromotion
            gs.makeMove(move)
            if (index >= LMR_MIN_INDEX and depth >= LMR_MIN_DEPTH and quiet and not inCheck
                    and move.moveID not in killers):
                # late move reduction: quiet moves this far down the ordering rarely matter, so they get
                # a shallower search first, and a full one only if they turn out better than expected
                score = -await self.negamax(depth - 2, ply + 1, -alpha - 1, -alpha)
                if score > alpha:
                    score = -await self.negamax(depth - 1, ply + 1, -beta, -alpha)
            else:
                score = -await self.negamax(depth - 1, ply + 1, -beta, -alpha)
            gs.undoMove()
            if score > bestScore:
                bestScore, bestMoveId = score, move.moveID
            if score > alpha:
                alpha = score
            if alpha >= beta:
                if quiet:
                    self.rememberCutoff(move, ply, depth)
                break  # the opponent won't allow this line
        self.path.pop()

        if bestScore <= alphaOriginal:
            bound = UPPER
        elif bestScore >= beta:
            bound = LOWER
        else:
            bound = EXACT
        storeEntry(key, depth, toTableScore(bestScore, ply), bound, bestMoveId)
        return bestScore

    # a quiet move that caused a cutoff is likely to do so again: in sibling positions (killer moves) and
    # anywhere the same piece goes to the same square (history)
    def rememberCutoff(self, move, ply, depth):
        killers = self.killers.setdefault(ply, [None, None])
        if killers[0] != move.moveID:
            killers[1], killers[0] = killers[0], move.moveID
        key = (move.pieceMoved, move.endRow, move.endCol)
        self.historyScores[key] = self.historyScores.get(key, 0) + depth * depth

    # passing the turn, for the null move search; it must be undone even when the search times out
    def makeNullMove(self):
        gs = self.gs
        self.nullSaved.append(gs.enpasantPossible)
        gs.whiteToMove = not gs.whiteToMove
        gs.enpasantPossible = ()
        gs.enpasantPossibleLog.append(())  # what undoMove restores in the positions after it

    def undoNullMove(self):
        gs = self.gs
        gs.whiteToMove = not gs.whiteToMove
        gs.enpasantPossibleLog.pop()
        gs.enpasantPossible = self.nullSaved.pop()

    # follows captures and promotions until the position is quiet; moves are the legal moves here
    async def quiesce(self, alpha, beta, ply, moves, qdepth):
        gs = self.gs
        if gs.inCheck:
            # no standing pat while in check: every escape is searched
            if qdepth >= MAX_QUIESCENCE_DEPTH:
                return self.evaluate()
            bestScore = -INFINITY
            candidates = moves
        else:
            standPat = self.evaluate()  # the side to move can usually do at least this well by not capturing
            if standPat >= beta or qdepth >= MAX_QUIESCENCE_DEPTH:
                return standPat
            bestScore = standPat
            if standPat > alpha:
                alpha = standPat
            # skip captures that can't bring the score back up to alpha (delta pruning)
            candidates = [m for m in moves if m.isPawnPromotion or
                          (m.isCapture and standPat + pieceScore[m.pieceCaptured[1]] + 2 > alpha)]
            orderMoves(candidates, None)

        for move in candidates:
            gs.makeMove(move)
            await self.tick()
            nextMoves = gs.getValidMoves()
            if not nextMoves:
                score = (CHECKMATE - ply - 1) if gs.inCheck else STALEMATE
            else:
                score = -await self.quiesce(-beta, -alpha, ply + 1, nextMoves, qdepth + 1)
            gs.undoMove()
            if score > bestScore:
                bestScore = score
            if score > alpha:
                alpha = score
            if alpha >= beta:
                break
        return bestScore


# best move from the table first, then captures of the most valuable piece by the least valuable one,
# then promotions, then the quiet moves that caused cutoffs before (killers, then by history);
# good ordering lets alpha-beta skip most of the tree
def orderMoves(moves, firstMoveId, killers=(), historyScores=None):
    def priority(move):
        if move.moveID == firstMoveId:
            return -100000
        if move.pieceCaptured != '--':
            return -10000 - (10 * pieceScore[move.pieceCaptured[1]] - pieceScore[move.pieceMoved[1]])
        if move.isPawnPromotion:
            return -9000
        if move.moveID in killers:
            return -8000
        if historyScores:
            return -min(historyScores.get((move.pieceMoved, move.endRow, move.endCol), 0), 7000)
        return 0
    moves.sort(key=priority)


# True when the side to move has a piece other than its king and pawns (null moves are unsafe without)
def hasPieces(gs):
    color = 'w' if gs.whiteToMove else 'b'
    for row in gs.board:
        for square in row:
            if square[0] == color and square[1] not in 'Kp':
                return True
    return False


# mate scores are stored relative to the position, not the root, so they stay right in other lines
def toTableScore(score, ply):
    if score > MATE_THRESHOLD:
        return score + ply
    if score < -MATE_THRESHOLD:
        return score - ply
    return score


def fromTableScore(score, ply):
    if score > MATE_THRESHOLD:
        return score - ply
    if score < -MATE_THRESHOLD:
        return score + ply
    return score


def storeEntry(key, depth, score, bound, moveId):
    if len(transpositionTable) >= TT_MAX_ENTRIES:
        transpositionTable.clear()
    transpositionTable[key] = (depth, score, bound, moveId)


'''
Positive score is good for white
Negative score is good for black
'''


def scoreBoard(gs):
    score = 0
    material = 0  # queens, rooks and minor pieces, to tell the endgame apart
    kings = []
    for row in range(len(gs.board)):
        boardRow = gs.board[row]
        for col in range(len(boardRow)):
            square = boardRow[col]
            if square == "--":
                continue
            piece = square[1]
            # Map the row back to standard coordinates if the board is flipped
            eval_row = 7 - row if gs.playerWantsToPlayAsBlack else row
            if piece == "K":
                kings.append((square[0], eval_row, col))
                continue
            # score positionally based on piece type
            if piece == "p":
                piecePositionScore = piecePositionScores[square][eval_row][col]
            else:
                piecePositionScore = piecePositionScores[piece][eval_row][col]
                material += pieceScore[piece]
            value = pieceScore[piece] + piecePositionScore * .1
            score += value if square[0] == 'w' else -value

    kingScores = kingEndScores if material <= ENDGAME_MATERIAL else kingMiddleScores
    for color, row, col in kings:
        if color == 'w':
            score += kingScores[row][col] * .1
        else:
            score -= kingScores[7 - row][col] * .1  # black's back rank is row 0
    return score


# common opening lines; the book is built from them on first use
BOOK_LINES = [
    "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7 Re1 b5 Bb3 d6",  # Ruy Lopez
    "e4 e5 Nf3 Nc6 Bb5 Nf6 O-O Nxe4 d4 Nd6",  # Berlin
    "e4 e5 Nf3 Nc6 Bc4 Bc5 c3 Nf6 d3 d6 O-O O-O",  # Italian
    "e4 e5 Nf3 Nc6 Bc4 Nf6 d3 Be7 O-O O-O",  # Two Knights
    "e4 e5 Nf3 Nc6 d4 exd4 Nxd4 Nf6 Nxc6 bxc6",  # Scotch
    "e4 e5 Nf3 Nf6 Nxe5 d6 Nf3 Nxe4 d4 d5 Bd3",  # Petrov
    "e4 e5 Nc3 Nf6 Nf3 Nc6 d4 exd4 Nxd4",  # Four Knights
    "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6 Be2 e5",  # Najdorf
    "e4 c5 Nf3 Nc6 d4 cxd4 Nxd4 Nf6 Nc3 e5 Ndb5 d6",  # Sveshnikov
    "e4 c5 Nf3 e6 d4 cxd4 Nxd4 Nc6 Nc3 Qc7",  # Taimanov
    "e4 c5 Nc3 Nc6 g3 g6 Bg2 Bg7 d3 d6",  # Closed Sicilian
    "e4 e6 d4 d5 Nc3 Nf6 Bg5 Be7 e5 Nfd7",  # French
    "e4 e6 d4 d5 e5 c5 c3 Nc6 Nf3 Qb6",  # French Advance
    "e4 c6 d4 d5 Nc3 dxe4 Nxe4 Bf5 Ng3 Bg6",  # Caro-Kann
    "e4 c6 d4 d5 e5 Bf5 Nf3 e6 Be2",  # Caro-Kann Advance
    "e4 d5 exd5 Qxd5 Nc3 Qa5 d4 Nf6 Nf3 c6",  # Scandinavian
    "e4 Nf6 e5 Nd5 d4 d6 Nf3 Bg4 Be2 e6",  # Alekhine
    "e4 d6 d4 Nf6 Nc3 g6 Nf3 Bg7 Be2 O-O",  # Pirc
    "d4 d5 c4 e6 Nc3 Nf6 Bg5 Be7 e3 O-O Nf3",  # Queen's Gambit Declined
    "d4 d5 c4 c6 Nf3 Nf6 Nc3 dxc4 a4 Bf5",  # Slav
    "d4 d5 c4 dxc4 Nf3 Nf6 e3 e6 Bxc4 c5 O-O",  # Queen's Gambit Accepted
    "d4 Nf6 c4 g6 Nc3 Bg7 e4 d6 Nf3 O-O Be2 e5",  # King's Indian
    "d4 Nf6 c4 e6 Nc3 Bb4 e3 O-O Bd3 d5 Nf3",  # Nimzo-Indian
    "d4 Nf6 c4 e6 Nf3 b6 g3 Bb7 Bg2 Be7 O-O O-O",  # Queen's Indian
    "d4 Nf6 c4 g6 Nc3 d5 cxd5 Nxd5 e4 Nxc3 bxc3 Bg7",  # Grunfeld
    "d4 Nf6 Nf3 d5 Bf4 e6 e3 c5 c3 Nc6",  # London
    "d4 d5 Nf3 Nf6 e3 e6 Bd3 c5 c3 Nc6",  # Colle
    "c4 e5 Nc3 Nf6 Nf3 Nc6 g3 d5 cxd5 Nxd5",  # English
    "c4 c5 Nf3 Nc6 Nc3 g6 g3 Bg7 Bg2 Nf6",  # Symmetrical English
    "c4 Nf6 Nc3 e6 e4 d5 e5 d4",  # Mikenas
    "Nf3 d5 g3 Nf6 Bg2 c6 O-O Bg4 d3",  # Reti
    "Nf3 Nf6 c4 g6 Nc3 Bg7 e4 d6 d4 O-O",  # transposes to the King's Indian
]
_book = None  # position key -> move codes (repeated codes are picked more often)


def buildBook():
    book = {}
    for line in BOOK_LINES:
        gs = GameState()
        moves = gs.getValidMoves()
        for san in line.split():
            move = gs.findMoveBySan(san, moves)
            if move is None:
                print(f"AI: opening book move {san} doesn't fit its line: {line}")
                break
            book.setdefault(gs.getPositionKey(), []).append(move.getCode())
            gs.makeMove(move)
            moves = gs.getValidMoves()
    return book


def bookMove(gs, validMoves):
    global _book
    if _book is None:
        _book = buildBook()
    codes = _book.get(gs.getPositionKey())
    if not codes:
        return None
    return gs.findMoveByCode(random.choice(codes), validMoves)
