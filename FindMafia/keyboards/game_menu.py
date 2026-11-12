from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M


def lobby(game_id: int, can_start: bool) -> M:
    rows = [[B("✅ Join Game", callback_data=f"lob:join:{game_id}"), B("🚪 Leave Game", callback_data=f"lob:leave:{game_id}")],
            [B("👥 Player List", callback_data=f"lob:list:{game_id}:0")]]
    if can_start:
        rows.append([B("▶️ Start Now (host)", callback_data=f"lob:start:{game_id}")])
    rows.append([B("❌ Cancel Game (host/admin)", callback_data=f"lob:cancel:{game_id}")])
    return M(rows)


def player_list(game_id: int, page: int, pages: int) -> M:
    nav = []
    if page > 0:
        nav.append(B("◀ Prev", callback_data=f"lob:list:{game_id}:{page - 1}"))
    if page < pages - 1:
        nav.append(B("Next ▶", callback_data=f"lob:list:{game_id}:{page + 1}"))
    rows = [nav] if nav else []
    rows.append([B("✖ Close", callback_data=f"lob:close:{game_id}")])
    return M(rows)


def start_bot_link(bot_username: str, payload: str = "") -> M:
    suffix = f"?start={payload}" if payload else ""
    return M([[B("▶️ Open bot & press Start", url=f"https://t.me/{bot_username}{suffix}")]])
