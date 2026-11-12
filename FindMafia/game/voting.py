"""Day voting: live tally, one changeable vote per player, tie rules, jester/executioner wins."""
import asyncio
import logging
import random
import time
from collections import defaultdict

from database.db import db
from game import engine, win_conditions
from keyboards import role_buttons as rb
from services.gif_manager import send_gif
from utils import rich, texts

log = logging.getLogger(__name__)


def weight(p) -> int:
    return 2 if p.role == "mayor" else 1


def tally(game):
    """-> (weights {target_uid: w}, voters {target_uid: [names]}, skip_weight)"""
    w, names, skip = defaultdict(int), defaultdict(list), 0
    for voter, target in game.votes.items():
        v = game.players[voter]
        if not v.alive:
            continue
        if target == 0:
            skip += weight(v)
        else:
            w[target] += weight(v)
            names[target].append(v.name)
    return w, names, skip


def rows_for(game, secret: bool):
    w, names, _ = tally(game)
    rows = []
    for t, c in sorted(w.items(), key=lambda x: -x[1]):
        rows.append([game.players[t].name, c] if secret else [game.players[t].name, c, ", ".join(names[t])[:60]])
    return rows


async def submit_vote(game, uid: int, token: int, arg: str) -> tuple[bool, str]:
    if game.status != "active" or game.phase != "voting" or token != game.phase_token:
        return False, "Voting is closed."
    voter = game.players.get(uid)
    if not voter or not voter.alive:
        return False, "Only living players can vote."
    if arg == "s":
        target_uid, msg = 0, "You skipped the vote."
    else:
        t = game.player_at(int(arg)) if arg.isdigit() else None
        if t is None or not t.alive:
            return False, "Invalid choice."
        if t.user_id == uid:
            return False, "You cannot vote for yourself."
        target_uid, msg = t.user_id, f"You voted for {t.name} ✅"
    game.votes[uid] = target_uid
    game.vote_dirty = True
    await db.save_vote(game.game_id, game.day_no, uid, target_uid)
    return True, msg


async def _render(bot, game, secret, left):
    voters = game.alive_players()
    _, _, skip = tally(game)
    scr = texts.vote_screen(game, rows_for(game, secret), left, secret, skip, len(voters), len([v for v in voters if v.user_id in game.votes]))
    await rich.edit_screen(bot, game.chat_id, game.vote_msg_id, scr, rb.vote_keyboard(game))


async def run_vote(bot, game):
    game.phase, game.phase_token = "voting", game.phase_token + 1
    game.votes.clear(); game.vote_dirty = False
    secs = int(game.settings["voting_seconds"])
    secret = bool(game.settings.get("secret_voting"))
    deadline = time.monotonic() + secs
    await db.update_game(game.game_id, phase="voting")
    await send_gif(bot, game.chat_id, "VOTING_GIF", game.thread_id)
    scr = texts.vote_screen(game, [], secs, secret, 0, len(game.alive_players()), 0)
    game.vote_msg_id = await rich.send_screen(bot, game.chat_id, scr, rb.vote_keyboard(game), game.thread_id)
    last = time.monotonic()
    while time.monotonic() < deadline and game.status == "active":
        await asyncio.sleep(0.4)
        alive = game.alive_players()
        if all(p.user_id in game.votes for p in alive):
            break
        now = time.monotonic()
        if (game.vote_dirty and now - last >= 2.5) or now - last >= config_interval():
            game.vote_dirty = False
            last = now
            await _render(bot, game, secret, deadline - now)
    if game.status != "active":
        return
    game.phase, game.phase_token = "counting", game.phase_token + 1
    await _finish(bot, game, secret)


def config_interval() -> float:
    import config
    return config.EDIT_INTERVAL


async def _finish(bot, game, secret):
    w, names, skip = tally(game)
    rows = rows_for(game, secret)
    top = max(w.values(), default=0)
    best = [t for t, c in w.items() if c == top and c > 0]
    if not best or skip >= top:
        victim, outcome = None, "Nobody was eliminated."
    elif len(best) > 1 and not game.settings.get("tie_rule"):
        victim, outcome = None, "It's a tie - nobody was eliminated."
    else:
        victim = random.choice(best)
        outcome = f"{game.players[victim].name} was voted out with {top} vote(s)."
    await rich.edit_screen(bot, game.chat_id, game.vote_msg_id, texts.vote_result(game, rows, secret, outcome))
    if victim is None:
        return
    p = game.players[victim]
    p.alive, p.death_note = False, "voted out"
    await db.set_player_state(game.game_id, victim, alive=False)
    hide = bool(game.settings.get("hardcore"))
    await send_gif(bot, game.chat_id, "ELIMINATION_GIF", game.thread_id)
    await rich.send_screen(bot, game.chat_id, texts.elimination(p.name, None if hide else p.role, "was eliminated by the village"), thread_id=game.thread_id)
    # neutral special wins end the game immediately
    if p.role == "jester":
        await engine.finish_game(bot, game, win_conditions.solo_win(game, victim, "The Jester fooled everyone and got voted out!"))
        return
    for e in game.alive_players():
        if e.role == "executioner" and e.exec_target == victim:
            await engine.finish_game(bot, game, win_conditions.solo_win(game, e.user_id, "The Executioner got their target voted out!"))
            return
    await engine.after_deaths(bot, game)
