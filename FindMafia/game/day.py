"""Day phase: announcement, discussion, then voting."""
import asyncio
import logging

from database.db import db
from game import engine, voting
from services.gif_manager import send_gif
from utils import rich, texts

log = logging.getLogger(__name__)


async def day_phase(bot, game):
    game.phase, game.phase_token = "day", game.phase_token + 1
    await db.update_game(game.game_id, phase="day", day_no=game.day_no)
    summary = game.last_night or {}
    if summary.get("deaths"):
        await send_gif(bot, game.chat_id, "MAFIA_ACTION_GIF", game.thread_id)
    elif summary.get("saved"):
        await send_gif(bot, game.chat_id, "DOCTOR_SAVE_GIF", game.thread_id)
    await send_gif(bot, game.chat_id, "DAY_GIF", game.thread_id)
    secs = int(game.settings["discussion_seconds"])
    await rich.send_screen(bot, game.chat_id, texts.day_screen(game, summary.get("lines", []), secs), thread_id=game.thread_id)
    if await engine.check_end(bot, game):
        return
    await asyncio.sleep(secs)
    if game.status != "active":
        return
    await voting.run_vote(bot, game)
    for p in game.players.values():
        p.silenced = False
