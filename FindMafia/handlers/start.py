"""/start, main menu and its sections (menu sections edit the same message)."""
import logging

from telegram import Update
from telegram.constants import ChatMemberStatus, ChatType
from telegram.ext import ContextTypes

from database.db import db
from keyboards import main_menu as kb
from services import statistics
from services.gif_manager import send_gif
from utils import rich, texts
from utils.validators import rate_limited, seen_callback

log = logging.getLogger(__name__)


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat, user, msg = update.effective_chat, update.effective_user, update.effective_message
    if chat.type != ChatType.PRIVATE:
        await msg.reply_text("Hi! Send /play here to open a Mafia lobby. 🎭")
        return
    if await db.is_banned(user.id):
        await msg.reply_text("You are banned from this bot.")
        return
    await db.upsert_user(user.id, user.username, user.first_name, dm_ok=True)
    await send_gif(ctx.bot, chat.id, "WELCOME_GIF")
    await rich.send_screen(ctx.bot, chat.id, texts.main_menu(), kb.main_menu())
    bonus = await statistics.claim_daily(user.id)
    if bonus:
        await rich.send_screen(ctx.bot, chat.id, texts.notice("🎁 Daily reward", f"+{bonus} XP for visiting today!"))
    if ctx.args and ctx.args[0].startswith("join"):
        await msg.reply_text("✅ You are ready! Go back to the group and tap Join Game.")


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await rich.send_screen(ctx.bot, update.effective_chat.id, texts.how_to_play(),
                           thread_id=update.effective_message.message_thread_id if update.effective_message.is_topic_message else None)


async def my_chat_member(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Track whether a user can receive our private messages."""
    m = update.my_chat_member
    if m.chat.type != ChatType.PRIVATE:
        return
    if m.new_chat_member.status == ChatMemberStatus.BANNED:
        await db.set_dm_ok(m.chat.id, False)
    elif m.new_chat_member.status == ChatMemberStatus.MEMBER:
        await db.upsert_user(m.from_user.id, m.from_user.username, m.from_user.first_name, dm_ok=True)


async def menu_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    bot, user = ctx.bot, q.from_user
    if seen_callback(q.id):
        return
    if rate_limited(user.id):
        await q.answer("Slow down a little 🙂")
        return
    if not q.message:
        await q.answer()
        return
    chat_id, mid = q.message.chat_id, q.message.message_id
    parts = q.data.split(":")
    section = parts[1] if len(parts) > 1 else "home"
    await db.upsert_user(user.id, user.username, user.first_name)

    async def show(screen, markup):
        await rich.edit_screen(bot, chat_id, mid, screen, markup)

    if section == "home":
        await show(texts.main_menu(), kb.main_menu())
    elif section == "play":
        await show(texts.play_instructions(bot.username), kb.play_menu(bot.username))
    elif section == "how":
        await show(texts.how_to_play(), kb.back_only())
    elif section == "roles":
        await show(texts.all_roles(), kb.back_only())
    elif section in ("profile", "stats"):
        p = await db.get_profile(user.id)
        if section == "profile":
            await show(texts.profile(p, await db.favorite_role(user.id), await db.earned_achievements(user.id)), kb.back_only())
        else:
            await show(texts.statistics(p, await statistics.weekly_progress(user.id), await statistics.recent_rewards(user.id)), kb.back_only())
    elif section == "lb":
        period = parts[2] if len(parts) > 2 and parts[2] in dict(texts.LB_PERIODS) else "all"
        page = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
        rows = await db.leaderboard(period, texts.LB_PER_PAGE + 1, page * texts.LB_PER_PAGE)
        has_next = len(rows) > texts.LB_PER_PAGE
        await show(texts.leaderboard(period, rows[:texts.LB_PER_PAGE], page), kb.leaderboard(period, page, has_next))
    elif section in ("settings", "rich"):
        if section == "rich":
            new = 0 if chat_id not in rich.chat_rich_off else 1
            await db.set_setting(chat_id, "rich", new)
            (rich.chat_rich_off.discard if new else rich.chat_rich_off.add)(chat_id)
        on = rich.rich_enabled(chat_id)
        await show(texts.settings_private(on), kb.settings_menu(chat_id not in rich.chat_rich_off))
    await q.answer()
