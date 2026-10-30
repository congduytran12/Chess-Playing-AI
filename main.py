from pathlib import Path
import os
import runpy
import sys


ROOT_DIR = Path(__file__).resolve().parent
GAME_DIR = ROOT_DIR / "game"

os.chdir(GAME_DIR)
sys.path.insert(0, str(GAME_DIR))
runpy.run_path(str(GAME_DIR / "main.py"), run_name="__main__")
