from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M

from utils import texts


def main_menu() -> M:
    return M([
        [B("🎮 Play Mafia", callback_data="menu:play")],
        [B("👤 My Profile", callback_data="menu:profile"), B("📊 My Statistics", callback_data="menu:stats")],
        [B("🏆 Leaderboard", callback_data="menu:lb:all:0")],
        [B("📖 How to Play", callback_data="menu:how"), B("🎭 All Roles", callback_data="menu:roles")],
        [B("⚙️ Settings", callback_data="menu:settings")],
    ])


def back_only() -> M:
    return M([[B(texts.tr("back"), callback_data="menu:home")]])


def play_menu(bot_username: str) -> M:
    return M([[B("➕ Add me to a group", url=f"https://t.me/{bot_username}?startgroup=true")],
              [B(texts.tr("back"), callback_data="menu:home")]])


def settings_menu(rich_on: bool) -> M:
    label = "🎨 Rich look: ON (tap to turn OFF)" if rich_on else "🎨 Rich look: OFF (tap to turn ON)"
    return M([[B(label, callback_data="menu:rich")], [B(texts.tr("back"), callback_data="menu:home")]])


def leaderboard(period: str, page: int, has_next: bool) -> M:
    row = [B(f"« {n} »" if k == period else n, callback_data=f"menu:lb:{k}:0") for k, n in texts.LB_PERIODS]
    nav = []
    if page > 0:
        nav.append(B("◀ Prev", callback_data=f"menu:lb:{period}:{page - 1}"))
    if has_next:
        nav.append(B("Next ▶", callback_data=f"menu:lb:{period}:{page + 1}"))
    rows = [row[:2], row[2:]]
    if nav:
        rows.append(nav)
    rows.append([B(texts.tr("back"), callback_data="menu:home")])
    return M(rows)
