"""In-game callbacks (night actions, votes), mafia private chat relay, group moderation, leaving."""
import logging

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from game import engine, night, voting
from game import roles as R
from game.engine import GAMES, USER_GAME
from keyboards import role_buttons as rb
from utils import rich, texts
from utils.validators import rate_limited, seen_callback

log = logging.getLogger(__name__)


async def act_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q, bot = update.callback_query, ctx.bot
    if seen_callback(q.id):
        return
    if rate_limited(q.from_user.id, 0.3):
        await q.answer("Slow down 🙂"); return
    p = q.data.split(":")
    try:
        gid, tok, kind = int(p[1]), int(p[2]), p[3]
    except (IndexError, ValueError):
        await q.answer(); return
    game = GAMES.get(gid)
    uid = q.from_user.id
    if not game or not q.message or q.message.chat_id != uid or uid not in game.players:   # must come from the player's own private chat
        await q.answer("This game is over.", show_alert=True); return
    pl = game.players[uid]
    if game.phase != "night" or tok != game.phase_token or not pl.alive:
        await q.answer("This night is over.", show_alert=True); return
    mid = q.message.message_id
    role = R.ROLES[pl.role]
    if kind in ("m", "back"):                         # mode selection screen
        mode = p[4] if kind == "m" and len(p) > 4 else None
        hint = "Now choose a target." if mode else None
        await rich.edit_screen(bot, uid, mid, texts.action_prompt(game, role, None, hint), rb.action_menu(game, pl, mode))
        await q.answer(); return
    if kind == "skip":
        ok, msg = await night.submit_action(bot, game, uid, tok, "skip", None, None)
    elif kind == "go":
        ok, msg = await night.submit_action(bot, game, uid, tok, "go", p[4], None)
    else:
        ok, msg = await night.submit_action(bot, game, uid, tok, "t", p[4], int(p[5]))
    await q.answer(msg, show_alert=not ok)


async def vote_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if seen_callback(q.id):
        return
    if rate_limited(q.from_user.id, 0.3):
        await q.answer("Slow down 🙂"); return
    p = q.data.split(":")
    try:
        gid, tok, arg = int(p[1]), int(p[2]), p[3]
    except (IndexError, ValueError):
        await q.answer(); return
    game = GAMES.get(gid)
    if not game or not q.message or q.message.chat_id != game.chat_id:
        await q.answer("This game is over.", show_alert=True); return
    ok, msg = await voting.submit_vote(game, q.from_user.id, tok, arg)
    await q.answer(msg, show_alert=not ok)


async def private_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Mafia team chat: text sent privately to the bot during the night is relayed to alive teammates."""
    u, m = update.effective_user, update.effective_message
    game = GAMES.get(USER_GAME.get(u.id, -1))
    if not game or game.status != "active" or not m.text:
        return
    me = game.players.get(u.id)
    if not me or not me.alive or R.team_of(me.role) != "mafia" or game.phase != "night":
        return
    for t in game.alive_players():
        if t.user_id != u.id and R.team_of(t.role) == "mafia":
            await night.dm(ctx.bot, t.user_id, texts.notice(f"🔪 {me.name}", m.text[:500]))


async def group_moderation(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Dead players and silenced players cannot influence the game (needs the Delete Messages right)."""
    m, u = update.effective_message, update.effective_user
    game = engine.BY_CHAT.get(update.effective_chat.id)
    if not game or game.status != "active" or not u:
        return
    p = game.players.get(u.id)
    if not p:
        return
    if (not p.alive) or (p.silenced and game.phase in ("day", "voting")):
        try:
            await m.delete()
        except TelegramError:
            if not game.stopped_notice_sent:
                game.stopped_notice_sent = True
                await ctx.bot.send_message(game.chat_id, "ℹ️ Give me the Delete Messages admin right so I can remove messages of dead/silenced players.")


async def left_member(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """A player who leaves the group during a game is eliminated without XP."""
    lm = update.effective_message.left_chat_member
    game = engine.BY_CHAT.get(update.effective_chat.id)
    if not lm or not game or game.status != "active":
        return
    p = game.players.get(lm.id)
    if not p or not p.alive:
        return
    p.alive, p.fled, p.death_note = False, True, "left the game"
    await rich.send_screen(ctx.bot, game.chat_id, texts.notice("🚪 Player left", f"{p.name} left the group and is out of the game."), thread_id=game.thread_id)
    await engine.check_end(ctx.bot, game)
