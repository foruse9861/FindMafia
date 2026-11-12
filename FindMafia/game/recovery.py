"""Restart recovery: interrupted games are cancelled safely (once) and the group is told."""
import logging

from telegram.error import TelegramError

from database.db import db, utcnow
from utils import rich, texts

log = logging.getLogger(__name__)


async def recover(bot) -> int:
    games = await db.unfinished_games()
    for g in games:
        await db.update_game(g["game_id"], status="cancelled", ended_at=utcnow())
        scr = texts.notice("🔄 Game cancelled", "The bot was restarted, so this game was cancelled safely. Send /play to start a new one.")
        try:
            if g.get("lobby_msg_id"):
                await rich.edit_screen(bot, g["chat_id"], g["lobby_msg_id"], scr)
            else:
                await rich.send_screen(bot, g["chat_id"], scr, thread_id=g.get("thread_id"))
        except TelegramError as e:
            log.info("recovery notice for game %s failed: %s", g["game_id"], e)
    if games:
        log.info("Recovered (cancelled) %d interrupted game(s)", len(games))
    return len(games)
