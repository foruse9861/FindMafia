"""Admin tools: group settings dashboard, owner stats, bans, announcements, rich test."""
import logging

from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M, Update
from telegram.constants import ChatType
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from database.db import DEFAULT_SETTINGS, db
from game import engine, lobby
from utils import rich, texts
from utils.validators import is_group_admin, is_owner, rate_limited, seen_callback

log = logging.getLogger(__name__)
TOGGLES = {"advanced_roles": "Advanced roles", "hardcore": "Hardcore (hidden roles)", "secret_voting": "Secret voting",
           "tie_rule": "Tie: random elimination", "rich": "Rich messages"}
TIMERS = {"lobby_seconds": "Lobby", "night_seconds": "Night", "discussion_seconds": "Discussion", "voting_seconds": "Voting"}


async def _is_admin(update, ctx) -> bool:
    c, u = update.effective_chat, update.effective_user
    return is_owner(u.id) or (c.type != ChatType.PRIVATE and await is_group_admin(ctx.bot, c.id, u.id))


async def settings_screen(chat_id: int):
    s = await db.all_settings(chat_id)
    d = texts.Doc().h("🛠 Group settings")
    d.table([["Players", f"{s['min_players']} - {s['max_players']}"],
             *[[n, f"{s[k]}s"] for k, n in TIMERS.items()],
             *[[n, "ON" if s[k] else "OFF"] for k, n in TOGGLES.items()]])
    d.p("Change with the buttons. Commands: /setplayers min max, /settimer lobby|night|discussion|voting seconds.")
    rows = [[B(f"{'✅' if s[k] else '⬜'} {n}", callback_data=f"adm:t:{k}")] for k, n in TOGGLES.items()]
    rows += [[B(f"➖ {n}", callback_data=f"adm:d:{k}"), B(f"{n} {s[k]}s", callback_data="adm:noop"), B(f"➕ {n}", callback_data=f"adm:u:{k}")] for k, n in TIMERS.items()]
    return d.screen(), M(rows)


async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    c, u, bot = update.effective_chat, update.effective_user, ctx.bot
    if not await _is_admin(update, ctx):
        await update.effective_message.reply_text("Admins only."); return
    if c.type == ChatType.PRIVATE:
        if not is_owner(u.id):
            await update.effective_message.reply_text("Open /admin inside a group to change that group's settings."); return
        d = texts.Doc().h("👑 Owner dashboard")
        d.table([["Users", await db.user_count()], ["Groups", await db.group_count()], ["Active games", await db.active_game_count()],
                 ["Finished games", await db.games_total()], ["Banned users", await db.banned_count()]])
        d.details("Commands", texts.Doc().ul(["/ban id [reason]", "/unban id", "/announce text", "/resetstats id", "/stopgame (in a group)", "/richtest"]))
        await rich.send_screen(bot, c.id, d.screen())
        return
    scr, kb = await settings_screen(c.id)
    await rich.send_screen(bot, c.id, scr, kb, update.effective_message.message_thread_id if update.effective_message.is_topic_message else None)


async def admin_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q, bot = update.callback_query, ctx.bot
    if seen_callback(q.id):
        return
    if not q.message or q.message.chat.type == ChatType.PRIVATE or not await is_group_admin(bot, q.message.chat_id, q.from_user.id):
        await q.answer("Admins only.", show_alert=True); return
    if rate_limited(q.from_user.id, 0.3):
        await q.answer(); return
    _, op, *rest = q.data.split(":")
    cid = q.message.chat_id
    if op == "t" and rest[0] in TOGGLES:
        k = rest[0]
        new = 0 if await db.get_setting(cid, k) else 1
        await db.set_setting(cid, k, new)
        if k == "rich":
            (rich.chat_rich_off.discard if new else rich.chat_rich_off.add)(cid)
    elif op in ("u", "d") and rest[0] in TIMERS:
        k = rest[0]
        cur = await db.get_setting(cid, k)
        await db.set_setting(cid, k, max(15, min(600, cur + (15 if op == "u" else -15))))
    else:
        await q.answer(); return
    scr, kb = await settings_screen(cid)
    await rich.edit_screen(bot, cid, q.message.message_id, scr, kb)
    await q.answer("Saved ✅")


async def cmd_setplayers(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update, ctx) or update.effective_chat.type == ChatType.PRIVATE:
        return
    try:
        lo, hi = int(ctx.args[0]), int(ctx.args[1])
        assert 5 <= lo <= hi <= 30
    except (IndexError, ValueError, AssertionError):
        await update.effective_message.reply_text("Usage: /setplayers <min 5+> <max up to 30>"); return
    await db.set_setting(update.effective_chat.id, "min_players", lo)
    await db.set_setting(update.effective_chat.id, "max_players", hi)
    await update.effective_message.reply_text(f"✅ Players: {lo}-{hi}")


async def cmd_settimer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update, ctx) or update.effective_chat.type == ChatType.PRIVATE:
        return
    try:
        key = f"{ctx.args[0].lower()}_seconds"
        val = int(ctx.args[1])
        assert key in TIMERS and 15 <= val <= 600
    except (IndexError, ValueError, AssertionError):
        await update.effective_message.reply_text("Usage: /settimer lobby|night|discussion|voting <15-600 seconds>"); return
    await db.set_setting(update.effective_chat.id, key, val)
    await update.effective_message.reply_text(f"✅ {ctx.args[0]} timer: {val}s")


async def _set_mode(update, ctx, key, val, text):
    if await _is_admin(update, ctx) and update.effective_chat.type != ChatType.PRIVATE:
        await db.set_setting(update.effective_chat.id, key, val)
        await update.effective_message.reply_text(text)


async def cmd_setmode(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    hard = bool(ctx.args) and ctx.args[0].lower() == "hardcore"
    await _set_mode(update, ctx, "hardcore", int(hard), "✅ Hardcore mode ON (roles stay hidden)" if hard else "✅ Normal mode (roles are revealed)")


async def cmd_setroles(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    adv = bool(ctx.args) and ctx.args[0].lower() == "advanced"
    await _set_mode(update, ctx, "advanced_roles", int(adv), "✅ Advanced roles ON" if adv else "✅ Basic roles only")


async def cmd_startgame(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    g = engine.BY_CHAT.get(update.effective_chat.id)
    if g and g.status == "lobby":
        if update.effective_user.id != g.host_id and not await _is_admin(update, ctx):
            await update.effective_message.reply_text("Only the host or an admin can start the game."); return
        if g.count < g.min_players:
            await update.effective_message.reply_text(f"At least {g.min_players} players are needed."); return
        await engine.start_game(ctx.bot, g)
    else:
        await lobby.cmd_play(update, ctx)


async def cmd_stopgame(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    g = engine.BY_CHAT.get(update.effective_chat.id)
    if not g:
        await update.effective_message.reply_text("There is no active game here."); return
    if update.effective_user.id != g.host_id and not await _is_admin(update, ctx):
        await update.effective_message.reply_text("Only the host or a group admin can stop the game."); return
    await engine.cancel_game(ctx.bot, g, "The game was stopped by the host/admin. No XP was given.")


async def cmd_ban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return
    try:
        uid = int(ctx.args[0])
    except (IndexError, ValueError):
        await update.effective_message.reply_text("Usage: /ban <user_id> [reason]"); return
    await db.ban(uid, " ".join(ctx.args[1:]))
    await update.effective_message.reply_text(f"🚫 {uid} banned")


async def cmd_unban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return
    try:
        await db.unban(int(ctx.args[0]))
        await update.effective_message.reply_text("✅ Unbanned")
    except (IndexError, ValueError):
        await update.effective_message.reply_text("Usage: /unban <user_id>")


async def cmd_resetstats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return
    try:
        uid = int(ctx.args[0])
    except (IndexError, ValueError):
        await update.effective_message.reply_text("Usage: /resetstats <user_id>"); return
    await db.transaction([
        ("UPDATE profiles SET xp=0, level=1, games=0, wins=0, losses=0, mafia_wins=0, town_wins=0, neutral_wins=0, eliminations=0, survived=0 WHERE user_id=?", (uid,)),
        ("DELETE FROM xp_log WHERE user_id=?", (uid,)), ("DELETE FROM achievements WHERE user_id=?", (uid,)),
        ("DELETE FROM game_history WHERE user_id=?", (uid,)), ("DELETE FROM role_history WHERE user_id=?", (uid,))])
    await update.effective_message.reply_text("✅ Stats reset")


async def cmd_announce(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id) or not ctx.args:
        return
    text = " ".join(ctx.args)
    sent = 0
    for r in await db.fetchall("SELECT chat_id FROM groups"):
        try:
            await rich.send_screen(ctx.bot, r["chat_id"], texts.notice("📢 Announcement", text)); sent += 1
        except TelegramError:
            pass
    await update.effective_message.reply_text(f"Sent to {sent} group(s).")


async def cmd_richtest(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update, ctx):
        return
    c = update.effective_chat
    d = texts.Doc().h("🧪 Rich message test").table([["Table", "works"], ["Pills", "below"]])
    d.pills([("Green", "pill:t:town", "success"), ("Red", "pill:t:mafia", "danger"), ("Blue", "pill:t:neutral", "primary"), ("Neutral", "pill:t:none", None)])
    d.details("Details block", texts.Doc().p("If you can open this, collapsible blocks work."))
    kb = M([[B("✅ I can see the table and pills", callback_data="adm:rt:1")], [B("❌ Message looks empty or broken", callback_data="adm:rt:0")]])
    await rich.send_screen(ctx.bot, c.id, d.screen(), kb)


async def richtest_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q.message or not (is_owner(q.from_user.id) or q.message.chat.type == ChatType.PRIVATE or await is_group_admin(ctx.bot, q.message.chat_id, q.from_user.id)):
        await q.answer("Admins only.", show_alert=True); return
    cid = q.message.chat_id
    if q.data.endswith(":1"):
        await q.answer("Great - rich messages stay ON ✅", show_alert=True)
    else:
        await db.set_setting(cid, "rich", 0)
        rich.chat_rich_off.add(cid)
        await q.answer("Rich messages are now OFF for this chat. Use /admin to turn them on again.", show_alert=True)
    try:
        await q.message.delete()
    except TelegramError:
        pass
