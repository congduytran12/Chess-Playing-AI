import os

with open("main.py", "r", encoding="utf-8") as f:
    text = f.read()

target_mouse = """                if dropdownMainRect.collidepoint(location):
                    dropdown_open = True
                    continue
                
                # Check for undo button click"""

replace_mouse = """                if dropdownMainRect.collidepoint(location):
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
                        import asyncio
                        asyncio.create_task(net.send({'type': 'undo_response', 'accepted': True}))
                        continue
                    elif denyBtn.collidepoint(location):
                        opponentRequestedUndo = False
                        import asyncio
                        asyncio.create_task(net.send({'type': 'undo_response', 'accepted': False}))
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
                        import random
                        import string
                        roomCode = ''.join(random.choices(string.digits, k=4))
                        net.set_topic(roomCode)
                        networkConnected = True
                        continue
                    elif joinBtn.collidepoint(location):
                        if len(roomCode) == 4:
                            multiplayerRole = 'client'
                            net.set_topic(roomCode)
                            import asyncio
                            asyncio.create_task(net.send({'type': 'join'}))
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
                
                # Check for undo button click"""

text = text.replace(target_mouse, replace_mouse)
with open("main.py", "w", encoding="utf-8") as f:
    f.write(text)
print("Mouse logic patched")
