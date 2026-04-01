import os

with open("main.py", "r", encoding="utf-8") as f:
    text = f.read()

target_draw = """        # Draw Dropdown
        btn_w = 200
        btn_h = 40
        dropdownMainRect = p.Rect(BOARD_WIDTH + MOVE_LOG_PANEL_WIDTH // 2 - btn_w // 2, BOARD_HEIGHT - 130, btn_w, btn_h)
        p.draw.rect(screen, p.Color(DARK_SQUARE_COLOR), dropdownMainRect)
        p.draw.rect(screen, p.Color('black'), dropdownMainRect, 1)

        diff_font = p.font.SysFont("Arial", 20, True, False)
        titles = ["Easy", "Normal", "Hard", "Very Hard", "Impossible"]
        
        main_text = f"Difficulty: {titles[chessAi.DEPTH - 1]} \u25B2" if dropdown_open else f"Difficulty: {titles[chessAi.DEPTH - 1]} \u25BC"
        textObj = diff_font.render(main_text, True, p.Color('white'))
        textLoc = dropdownMainRect.move(
            dropdownMainRect.width / 2 - textObj.get_width() / 2,
            dropdownMainRect.height / 2 - textObj.get_height() / 2
        )
        screen.blit(textObj, textLoc)

        if dropdown_open:
            for i in range(5):
                optRect = p.Rect(BOARD_WIDTH + MOVE_LOG_PANEL_WIDTH // 2 - btn_w // 2, BOARD_HEIGHT - 130 - (5 - i) * btn_h, btn_w, btn_h)
                # Hover effect
                mouse_pos = p.mouse.get_pos()
                color = p.Color(MOVE_HIGHLIGHT_COLOR) if optRect.collidepoint(mouse_pos) else p.Color(DARK_SQUARE_COLOR)
                p.draw.rect(screen, color, optRect)
                p.draw.rect(screen, p.Color('black'), optRect, 1)

                optTextObj = diff_font.render(titles[i], True, p.Color('white'))
                optTextLoc = optRect.move(
                    optRect.width / 2 - optTextObj.get_width() / 2,
                    optRect.height / 2 - optTextObj.get_height() / 2
                )
                screen.blit(optTextObj, optTextLoc)"""

replace_draw = """        btn_w = 200
        btn_h = 40
        diff_font = p.font.SysFont("Arial", 20, True, False)

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
            main_text = f"Difficulty: {titles[chessAi.DEPTH - 1]} \\u25B2" if dropdown_open else f"Difficulty: {titles[chessAi.DEPTH - 1]} \\u25BC"
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
                    screen.blit(optTextObj, optRect.move(optRect.width / 2 - optTextObj.get_width() / 2, optRect.height / 2 - optTextObj.get_height() / 2))"""

text = text.replace(target_draw, replace_draw)
with open("main.py", "w", encoding="utf-8") as f:
    f.write(text)
print("Draw logic patched")
