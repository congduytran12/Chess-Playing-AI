with open("main.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    stripped = line.strip()
    if stripped in ["import asyncio", "import random", "import string"]:
        # We only want to remove them if they are indented inside the game loop, not at the top level
        if line.startswith(" ") and len(line) - len(stripped) > 4:
            continue
    new_lines.append(line)

with open("main.py", "w", encoding="utf-8") as f:
    f.writelines(new_lines)
print("Fix applied.")
