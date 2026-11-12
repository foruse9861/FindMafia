"""MAFIA WORLD - entry point (python-telegram-bot 22.x, polling)."""
import asyncio
import glob
import logging
import os
from logging.handlers import RotatingFileHandler

from utils import rich

rich.check_ptb_version()  # exits with a clear message if the wrong library version is installed

from telegram import BotCommand, Update  # noqa: E402
from telegram.ext import (Application, CallbackQueryHandler, ChatMemberHandler, CommandHandler,  # noqa: E402
                          ContextTypes, MessageHandler, filters)

import config  # noqa: E402
from database.db import db  # noqa: E402
from game import lobby, recovery  # noqa: E402
from handlers import admin, callbacks, game_handlers, start  # noqa: E402

log = logging.getLogger("mafia")


def setup_logging():
    os.makedirs("logs", exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(config.LOG_LEVEL)
    for h in (logging.StreamHandler(), RotatingFileHandler("logs/bot.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")):
        h.setFormatter(fmt)
        root.addHandler(h)
    logging.getLogger("httpx").setLevel(logging.WARNING)


async def _backup_loop():
    base = os.path.join(os.path.dirname(config.DB_PATH) or ".", "backups")
    await asyncio.sleep(60)
    while True:
        try:
            from datetime import datetime
            await db.backup(os.path.join(base, f"mafia_{datetime.now():%Y%m%d}.db"))
            for old in sorted(glob.glob(os.path.join(base, "mafia_*.db")))[:-7]:
                os.remove(old)
        except Exception:
            log.exception("backup failed")
        await asyncio.sleep(24 * 3600)


async def post_init(app: Application):
    await db.init()
    rich.chat_rich_off.update(await db.chats_with_rich_off())
    await recovery.recover(app.bot)
    await app.bot.set_my_commands([
        BotCommand("start", "Open the main menu"), BotCommand("play", "Open a Mafia lobby (in a group)"),
        BotCommand("help", "How to play"), BotCommand("cancelgame", "Cancel the game (host/admin)"), BotCommand("stopgame", "Stop a running game (host/admin)"),
        BotCommand("admin", "Group settings (admins)"),
    ])
    app.bot_data["backup_task"] = asyncio.create_task(_backup_loop())
    log.info("MAFIA WORLD ready as @%s (rich messages: %s)", app.bot.username, "on" if config.RICH_MESSAGES else "off")


async def post_shutdown(app: Application):
    t = app.bot_data.get("backup_task")
    if t:
        t.cancel()
    await db.close()


async def on_error(update: object, ctx: ContextTypes.DEFAULT_TYPE):
    log.error("Unhandled error", exc_info=ctx.error)
    if isinstance(update, Update) and update.callback_query:
        try:
            await update.callback_query.answer("Something went wrong. Please try again.")
        except Exception:
            pass


def build_application(token: str | None = None, request=None) -> Application:
    b = Application.builder().token(token or config.BOT_TOKEN).post_init(post_init).post_shutdown(post_shutdown)
    if request is not None:
        b = b.request(request).get_updates_request(request)
    app = b.build()
    app.add_handler(CommandHandler("start", start.cmd_start))
    app.add_handler(CommandHandler("help", start.cmd_help))
    app.add_handler(CommandHandler("play", lobby.cmd_play))
    app.add_handler(CommandHandler("startgame", admin.cmd_startgame))
    app.add_handler(CommandHandler("cancelgame", lobby.cmd_cancel))
    app.add_handler(CommandHandler("stopgame", admin.cmd_stopgame))
    for name, fn in (("admin", admin.cmd_admin), ("setplayers", admin.cmd_setplayers), ("settimer", admin.cmd_settimer),
                     ("setmode", admin.cmd_setmode), ("setroles", admin.cmd_setroles), ("ban", admin.cmd_ban),
                     ("unban", admin.cmd_unban), ("resetstats", admin.cmd_resetstats), ("announce", admin.cmd_announce),
                     ("richtest", admin.cmd_richtest)):
        app.add_handler(CommandHandler(name, fn))
    app.add_handler(CallbackQueryHandler(game_handlers.act_callback, pattern=r"^act:"))
    app.add_handler(CallbackQueryHandler(game_handlers.vote_callback, pattern=r"^vote:"))
    app.add_handler(CallbackQueryHandler(admin.richtest_callback, pattern=r"^adm:rt:"))
    app.add_handler(CallbackQueryHandler(admin.admin_callback, pattern=r"^adm:"))
    app.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, game_handlers.left_member))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, game_handlers.private_message))
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & ~filters.COMMAND & ~filters.StatusUpdate.ALL, game_handlers.group_moderation), group=1)
    app.add_handler(CallbackQueryHandler(lobby.lobby_callback, pattern=r"^lob:"))
    app.add_handler(CallbackQueryHandler(callbacks.pill_callback, pattern=r"^pill:"))
    app.add_handler(CallbackQueryHandler(start.menu_callback, pattern=r"^menu:"))
    app.add_handler(ChatMemberHandler(start.my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_error_handler(on_error)
    return app


def main():
    setup_logging()
    if not config.BOT_TOKEN:
        raise SystemExit("BOT_TOKEN is missing. Copy .env.example to .env and set BOT_TOKEN.")
    build_application().run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
