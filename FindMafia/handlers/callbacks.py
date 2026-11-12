"""Pill callbacks. Pills only DISPLAY state: they answer with a popup and never trigger game actions."""
from telegram import Update
from telegram.ext import ContextTypes

from game import roles
from game.engine import GAMES
from services.achievements import ACHIEVEMENTS
from utils.validators import rate_limited, seen_callback


async def pill_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if seen_callback(q.id):
        return
    if rate_limited(q.from_user.id, 0.3):
        await q.answer()
        return
    p = (q.data or "").split(":")
    kind = p[1] if len(p) > 1 else ""
    text = "OK"
    try:
        if kind == "t":                                   # team pill on a private role card
            text = f"Team: {roles.TEAM_NAMES.get(p[2], p[2])}"
        elif kind == "b":                                 # badge pill
            name, desc = ACHIEVEMENTS[p[2]]
            text = f"{name}: {desc}"
        elif kind in ("j", "a"):                          # lobby / alive-dead pill (public info only)
            game = GAMES.get(int(p[2]))
            if not game or not q.message or q.message.chat_id != game.chat_id:
                text = "This game has ended."
            else:
                pl = game.player_at(int(p[3]))
                if pl is None:
                    text = "Unknown player."
                elif kind == "j":
                    text = f"{pl.name} joined the game."
                else:
                    text = f"{pl.name} is {'alive' if pl.alive else 'dead'}."
    except (IndexError, KeyError, ValueError):
        text = "This button is no longer valid."
    await q.answer(text)
