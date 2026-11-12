"""Night phase: private action prompts, submission, and the full resolution of every role."""
import asyncio
import logging
import random
import time
from collections import Counter, defaultdict

from telegram.error import TelegramError

from database.db import db
from game import engine
from game import roles as R
from keyboards import role_buttons as rb
from services.gif_manager import send_gif
from utils import rich, texts

log = logging.getLogger(__name__)


async def dm(bot, uid: int, screen, markup=None):
    try:
        return await rich.send_screen(bot, uid, screen, markup)
    except TelegramError as e:
        log.info("DM to %s failed: %s", uid, e)
        return None


async def run_game(bot, game):
    from game import day
    try:
        while game.status == "active":
            await night_phase(bot, game)
            if game.status != "active":
                return
            if await engine.check_end(bot, game):
                return
            await day.day_phase(bot, game)
            if game.status != "active":
                return
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("game loop crashed (game %s)", game.game_id)
        await engine.cancel_game(bot, game, "Something went wrong, so the game was stopped safely. Send /play to start a new one.")


async def night_phase(bot, game):
    game.day_no += 1
    game.phase, game.phase_token = "night", game.phase_token + 1
    game.night_actions.clear(); game.prompt_msgs.clear()
    secs = int(game.settings["night_seconds"])
    game.phase_deadline = time.monotonic() + secs
    await db.update_game(game.game_id, phase="night", day_no=game.day_no)
    await send_gif(bot, game.chat_id, "NIGHT_GIF", game.thread_id)
    await rich.send_screen(bot, game.chat_id, texts.night_screen(game, secs), thread_id=game.thread_id)
    game.events = asyncio.Event()
    game.required = set()
    for p in game.alive_players():
        acts = rb.usable_actions(p)
        acts = [a for a in acts if rb.targets_for(game, p, a) or a.target is None]
        if not acts:
            continue
        mid = await dm(bot, p.user_id, texts.action_prompt(game, R.ROLES[p.role]), rb.action_menu(game, p))
        if mid:
            game.prompt_msgs[p.user_id] = mid
            game.required.add(p.user_id)
    wait = secs if game.required else min(secs, 6)
    try:
        await asyncio.wait_for(game.events.wait(), wait)
    except asyncio.TimeoutError:
        pass
    game.phase = "resolving"
    game.phase_token += 1          # expires every old button
    await resolve_night(bot, game)


def _check_all_done(game):
    if game.required and all(u in game.night_actions for u in game.required) and game.events:
        game.events.set()


async def submit_action(bot, game, uid: int, token: int, kind: str, key: str | None, idx: int | None) -> tuple[bool, str]:
    """Validate and record a night action. kind: t (target) | go (no target) | skip."""
    if game.status != "active" or game.phase != "night" or token != game.phase_token:
        return False, "This night is over."
    p = game.players.get(uid)
    if not p or not p.alive:
        return False, "You are not alive in this game."
    if kind == "skip":
        game.night_actions[uid] = ("skip", None)
        _check_all_done(game)
        return True, "You skip tonight."
    action = next((a for a in R.ROLES[p.role].actions if a.key == key), None)
    if action is None:
        return False, "Your role cannot do that."
    if action.uses is not None and p.uses.get(action.key, 0) <= 0:
        return False, "No uses left."
    target = None
    if kind == "t":
        target = game.player_at(idx) if idx is not None else None
        if target is None or target not in rb.targets_for(game, p, action):
            return False, "Invalid target."
        game.night_actions[uid] = (action.key, target.user_id)
        label = f"{action.label} → {target.name}"
        if action.key == "kill":
            for m in game.alive_players():
                if m.user_id != uid and R.team_of(m.role) == "mafia":
                    await dm(bot, m.user_id, texts.notice("🔪 Team", f"{p.name} chose: {target.name}"))
    else:
        game.night_actions[uid] = (action.key, None)
        label = action.label
    mid = game.prompt_msgs.get(uid)
    if mid:
        await rich.edit_screen(bot, uid, mid, texts.action_prompt(game, R.ROLES[p.role], label), rb.action_menu(game, p))
    _check_all_done(game)
    return True, "Choice saved ✅"


def _team_label(t: str) -> str:
    return R.TEAM_NAMES[t]


async def resolve_night(bot, game):
    P, rng = game.players, random
    acts = {u: a for u, a in game.night_actions.items() if a[0] != "skip" and P[u].alive}
    msgs: list[tuple[int, object]] = []

    def tell(uid, title, text):
        msgs.append((uid, texts.notice(title, text)))

    # 1) role blocks (consort / jailor are not blockable)
    blocked, jailed = set(), set()
    for u, (k, t) in acts.items():
        if k == "block" and t:
            blocked.add(t); tell(t, "💋 Distracted", "Someone distracted you. Your action failed tonight.")
        if k == "jail" and t:
            blocked.add(t); jailed.add(t); tell(t, "⛓️ Jailed", "You were jailed tonight. You cannot act, but you are safe.")
    active = {u: a for u, a in acts.items() if u not in blocked or a[0] in ("block", "jail", "execute")}
    for u, (k, t) in active.items():                       # spend limited uses
        if P[u].uses.get(k) is not None:
            P[u].uses[k] -= 1

    visits = defaultdict(list)
    for u, (k, t) in active.items():
        if t and k not in ("seance",):
            visits[t].append((u, k))

    # 2) protections
    protected, guards, alert = defaultdict(list), defaultdict(list), set()
    for u, (k, t) in active.items():
        if k == "protect": protected[t].append(u); P[u].last_protected = t
        elif k == "vest": protected[u].append(u)
        elif k == "guard": guards[t].append(u)
        elif k == "alert": alert.add(u)
    for t in jailed:
        protected[t].append(None)
    for u in game.alive_players():                          # a doctor who did not act can protect same target again
        if u.user_id not in active or active[u.user_id][0] != "protect":
            u.last_protected = None

    # 3) attacks
    attacks = []
    kv = {u: t for u, (k, t) in active.items() if k == "kill" and t}
    if kv:
        gf = [u for u in kv if P[u].role == "godfather"]
        if gf:
            attacker, target = gf[0], kv[gf[0]]
        else:
            top = Counter(kv.values()).most_common()
            best = [t for t, c in top if c == top[0][1]]
            target = rng.choice(best)
            attacker = rng.choice([u for u, t in kv.items() if t == target])
        attacks.append(("mafia", attacker, target))
    for u, (k, t) in active.items():
        if k == "murder": attacks.append(("sk", u, t))
        elif k == "shoot": attacks.append(("vig", u, t))
        elif k == "execute": attacks.append(("exec", u, t))
        elif k == "ignite":
            attacks += [("fire", u, d.user_id) for d in game.alive_players() if d.doused]
    died: dict[int, str] = {}
    credit: dict[int, int] = {}
    saved: set[int] = set()
    for kind, att, tgt in attacks:
        T = P[tgt]
        if not T.alive or tgt in died:
            continue
        hard = kind in ("exec", "fire")
        if tgt in alert and not hard:
            if att not in died and P[att].alive:
                died[att] = "visited a Veteran on alert"; credit[att] = tgt
            continue
        if kind == "mafia" and T.role == "serial_killer":
            tell(att, "🔪 Failed", "Your target survived the attack.")
            continue
        if not hard:
            bgs = [b for b in guards.get(tgt, []) if P[b].alive and b not in died]
            if bgs:
                b = bgs[0]
                died[b] = "died protecting someone"; credit[b] = att
                if att not in died:
                    died[att] = "was killed by a Bodyguard"; credit[att] = b
                saved.add(tgt)
                tell(tgt, "💂 Saved", "You were attacked, but a Bodyguard saved you!")
                continue
            if protected.get(tgt):
                saved.add(tgt)
                tell(tgt, "🛡 Saved", "You were attacked, but you survived!")
                for d in protected[tgt]:
                    if d is not None and d != tgt:
                        tell(d, "🩺 Success", "Your patient was attacked and you saved them!")
                continue
        died[tgt] = {"mafia": "killed by the Mafia", "sk": "murdered", "vig": "shot", "exec": "executed", "fire": "burned"}[kind]
        credit[tgt] = att
    for u, (k, t) in active.items():
        if k == "douse" and t: P[t].doused = True
        if k == "frame" and t: P[t].framed = True
        if k == "silence" and t: P[t].silenced = True
    if any(k == "ignite" for k, _ in active.values()):
        for p in P.values(): p.doused = False
    cleaned = {t for u, (k, t) in active.items() if k == "clean" and t}

    # 4) investigations (use the state before deaths are applied)
    for u, (k, t) in active.items():
        if k not in ("investigate", "interrogate", "investigate_role", "seance") or not t:
            continue
        T = P[t]
        if k == "investigate":
            team = "mafia" if T.framed else ("town" if T.role == "godfather" else R.team_of(T.role))
            res = _team_label(team)
        elif k == "interrogate":
            sus = T.framed or (T.role != "godfather" and (R.team_of(T.role) == "mafia" or T.role in R.HOSTILE_NEUTRAL))
            res = "Suspicious 🔴" if sus else "Not suspicious 🟢"
        else:
            res = f"{R.ROLES[T.role].emoji} {R.ROLES[T.role].name}"
        msgs.append((u, texts.private_result(f"{R.ROLES[P[u].role].emoji} Night {game.day_no} result", [[T.name, res]])))

    # 5) apply deaths
    lines, dead_ids = [], []
    for uid, cause in died.items():
        p = P[uid]
        p.alive, p.death_note = False, cause
        p.role_hidden = uid in cleaned
        if credit.get(uid) in P:
            P[credit[uid]].kills += 1
        dead_ids.append(uid)
        await db.set_player_state(game.game_id, uid, alive=False)
        hide = game.settings.get("hardcore") or p.role_hidden
        lines.append(f"💀 {p.name} was found dead." + (" Their role could not be determined." if hide else f" They were {R.ROLES[p.role].emoji} {R.ROLES[p.role].name}."))
        tell(uid, "💀 You died", f"You {cause}. You are now a spectator - please do not give hints.")
    if saved and not died:
        lines.append("🛡 Someone was attacked tonight, but was saved!")
    elif not died:
        lines.append("Nobody died tonight.")
    for p in P.values():
        if p.silenced and p.alive:
            lines.append(f"🤐 {p.name} was silenced and cannot speak today.")
        p.framed = False
    for uid, scr in msgs:
        await dm(bot, uid, scr)
    game.last_night = {"lines": lines, "deaths": dead_ids, "saved": bool(saved)}
    await engine.after_deaths(bot, game)
