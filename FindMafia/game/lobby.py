"""Lobby: create, join/leave, countdown, host controls."""
import asyncio
import logging
import sqlite3
import time

from telegram import Update
from telegram.constants import ChatType
from telegram.error import TelegramError
from telegram.ext import ContextTypes

import config
from database.db import db
from game import engine
from game.engine import BY_CHAT, GAMES, USER_GAME, Game, Player
from keyboards import game_menu
from services.gif_manager import send_gif
from utils import rich, texts
from utils.validators import is_group_admin, rate_limited, seen_callback

log = logging.getLogger(__name__)
MIN_REFRESH_GAP = 2.5


def _name(user) -> str:
    n = (user.full_name or user.first_name or str(user.id)).strip()
    return n[:24] or str(user.id)


def lobby_markup(game: Game):
    return game_menu.lobby(game.game_id, can_start=game.count >= game.min_players)


async def refresh_lobby(bot, game: Game):
    """Edit the lobby message (rate limited, coalesced)."""
    if game.status != "lobby" or not game.lobby_msg_id or game.refresh_pending:
        return
    game.refresh_pending = True
    try:
        wait = game.last_edit + MIN_REFRESH_GAP - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        if game.status != "lobby":
            return
        host = game.players.get(game.host_id)
        scr = texts.lobby(game, host.name if host else "-")
        await rich.edit_screen(bot, game.chat_id, game.lobby_msg_id, scr, lobby_markup(game))
        game.last_edit = time.monotonic()
    except TelegramError as e:
        log.warning("lobby refresh failed: %s", e)
    finally:
        game.refresh_pending = False


async def countdown(bot, game: Game):
    try:
        while game.status == "lobby":
            left = game.seconds_left()
            if left <= 0:
                break
            await asyncio.sleep(min(config.EDIT_INTERVAL, left))
            if game.status == "lobby" and game.seconds_left() > 0:
                await refresh_lobby(bot, game)
        if game.status != "lobby":
            return
        if game.count >= game.min_players:
            await engine.start_game(bot, game)
        else:
            await engine.cancel_game(bot, game, f"Not enough players (minimum {game.min_players}). The lobby was closed.")
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("countdown crashed")
        await engine.cancel_game(bot, game, "Something went wrong. The game was cancelled safely.")


# ------------------------------------------------------------------ commands
async def cmd_play(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg, chat, user = update.effective_message, update.effective_chat, update.effective_user
    bot = ctx.bot
    if chat.type == ChatType.PRIVATE:
        await rich.send_screen(bot, chat.id, texts.play_instructions(bot.username))
        return
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    thread = msg.message_thread_id if getattr(msg, "is_topic_message", False) else None
    if await db.is_banned(user.id):
        await msg.reply_text("You are banned from playing.")
        return
    await db.upsert_user(user.id, user.username, user.first_name)
    await db.ensure_group(chat.id, chat.title)
    if chat.id in BY_CHAT:
        await msg.reply_text("A game is already running in this group.")
        return
    if user.id in USER_GAME:
        await msg.reply_text("You are already in another game.")
        return
    if not await db.is_dm_ok(user.id):
        await rich.send_screen(bot, chat.id, texts.notice("▶️ One quick step", f"{_name(user)}, open a private chat with me and press Start first. "
                                                          "I need it to send your secret role."),
                               game_menu.start_bot_link(bot.username), thread)
        return
    st = await db.all_settings(chat.id)
    try:
        gid = await db.create_game(chat.id, thread, user.id)
    except sqlite3.IntegrityError:
        await msg.reply_text("A game is already running in this group.")
        return
    game = Game(gid, chat.id, thread, user.id, min_players=st["min_players"], max_players=st["max_players"],
                lobby_seconds=st["lobby_seconds"], settings=st)
    game.lobby_deadline = time.monotonic() + game.lobby_seconds
    game.players[user.id] = Player(user.id, _name(user), user.username)
    engine.register(game)
    USER_GAME[user.id] = gid
    await db.add_game_player(gid, user.id, game.players[user.id].name)
    await send_gif(bot, chat.id, "LOBBY_GIF", thread)
    scr = texts.lobby(game, game.players[user.id].name)
    game.lobby_msg_id = await rich.send_screen(bot, chat.id, scr, lobby_markup(game), thread)
    game.last_edit = time.monotonic()
    await db.update_game(gid, lobby_msg_id=game.lobby_msg_id)
    game.spawn(countdown(bot, game))


async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat, user = update.effective_chat, update.effective_user
    game = BY_CHAT.get(chat.id)
    if not game:
        await update.effective_message.reply_text("There is no active game here.")
        return
    if user.id != game.host_id and not await is_group_admin(ctx.bot, chat.id, user.id):
        await update.effective_message.reply_text("Only the host or a group admin can cancel the game.")
        return
    await engine.cancel_game(ctx.bot, game, "The game was cancelled by the host/admin.")


# ------------------------------------------------------------------ callbacks
async def lobby_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    bot = ctx.bot
    if seen_callback(q.id):
        return
    if rate_limited(q.from_user.id):
        await q.answer("Slow down a little 🙂")
        return
    parts = (q.data or "").split(":")
    try:
        action, gid = parts[1], int(parts[2])
    except (IndexError, ValueError):
        await q.answer()
        return
    game = GAMES.get(gid)
    if not q.message or not game or q.message.chat_id != game.chat_id or game.status != "lobby":
        await q.answer("This lobby is no longer active.", show_alert=True)
        return
    user = q.from_user

    if action == "join":
        if await db.is_banned(user.id):
            await q.answer("You are banned from playing.", show_alert=True)
            return
        await db.upsert_user(user.id, user.username, user.first_name)
        if not await db.is_dm_ok(user.id):
            await q.answer(url=f"https://t.me/{bot.username}?start=join")
            return
        async with game.lock:
            if game.status != "lobby":
                await q.answer("The lobby just closed.", show_alert=True)
                return
            if user.id in game.players:
                await q.answer("You already joined 🙂")
                return
            if user.id in USER_GAME:
                await q.answer("You are already in another game.", show_alert=True)
                return
            if game.count >= game.max_players:
                await q.answer("The lobby is full.", show_alert=True)
                return
            game.players[user.id] = Player(user.id, _name(user), user.username)
            USER_GAME[user.id] = game.game_id
        await db.add_game_player(game.game_id, user.id, game.players[user.id].name)
        await q.answer("You joined the game ✅")
        await refresh_lobby(bot, game)

    elif action == "leave":
        async with game.lock:
            if user.id not in game.players:
                await q.answer("You are not in this game.")
                return
            game.players.pop(user.id)
            USER_GAME.pop(user.id, None)
            if user.id == game.host_id and game.players:
                game.host_id = next(iter(game.players))
                await db.update_game(game.game_id, host_id=game.host_id)
        await db.remove_game_player(game.game_id, user.id)
        await q.answer("You left the game.")
        if game.count == 0:
            await engine.cancel_game(bot, game, "Everybody left. The lobby was closed.")
        else:
            await refresh_lobby(bot, game)

    elif action == "list":
        page = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
        scr, page, pages = texts.player_list(game, page)
        kb = game_menu.player_list(game.game_id, page, pages)
        if game.list_msg_id and await rich.edit_screen(bot, game.chat_id, game.list_msg_id, scr, kb):
            pass
        else:
            game.list_msg_id = await rich.send_screen(bot, game.chat_id, scr, kb, game.thread_id)
        await q.answer()

    elif action == "close":
        if game.list_msg_id and q.message.message_id == game.list_msg_id:
            await engine._delete_quiet(bot, game.chat_id, game.list_msg_id)
            game.list_msg_id = None
        await q.answer()

    elif action in ("start", "cancel"):
        if user.id != game.host_id and not await is_group_admin(bot, game.chat_id, user.id):
            await q.answer("Only the host or a group admin can do this.", show_alert=True)
            return
        if action == "start":
            if game.count < game.min_players:
                await q.answer(f"At least {game.min_players} players are needed.", show_alert=True)
                return
            await q.answer("Starting the game…")
            await engine.start_game(bot, game)
        else:
            await q.answer("Game cancelled.")
            await engine.cancel_game(bot, game, "The game was cancelled by the host/admin.")
    else:
        await q.answer()
