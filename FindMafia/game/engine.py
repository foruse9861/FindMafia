"""Game state registry + data classes. The phase logic lives in night.py / day.py / voting.py."""
import asyncio
import time
from dataclasses import dataclass, field

import config


@dataclass
class Player:
    user_id: int
    name: str
    username: str | None = None
    role: str | None = None
    alive: bool = True
    # per-game ability state (filled in when the game starts)
    uses: dict = field(default_factory=dict)
    silenced: bool = False
    doused: bool = False
    framed: bool = False
    last_protected: int | None = None     # doctor: last night's target
    exec_target: int | None = None         # executioner: user id of the target
    death_note: str = ""                   # how they died (public text)
    role_hidden: bool = False              # janitor cleaned
    kills: int = 0                         # kills made by this player's role (for stats)
    fled: bool = False                     # left the group mid-game (no XP)


@dataclass
class Game:
    game_id: int
    chat_id: int
    thread_id: int | None
    host_id: int
    min_players: int = config.MIN_PLAYERS
    max_players: int = config.MAX_PLAYERS
    lobby_seconds: int = config.LOBBY_SECONDS
    status: str = "lobby"                 # lobby | starting | active | finished | cancelled
    players: dict = field(default_factory=dict)      # user_id -> Player (insertion ordered)
    settings: dict = field(default_factory=dict)
    lobby_deadline: float = 0.0
    lobby_msg_id: int | None = None
    list_msg_id: int | None = None
    last_edit: float = 0.0
    refresh_pending: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    tasks: set = field(default_factory=set)
    # --- phase state (used by night/day/voting) ---
    phase: str = "lobby"                  # lobby | night | day | voting | over
    day_no: int = 0
    phase_token: int = 0                  # increments on every phase change (expires old buttons)
    phase_deadline: float = 0.0
    phase_msg_id: int | None = None
    vote_msg_id: int | None = None
    night_actions: dict = field(default_factory=dict)   # user_id -> (action_key, target_id|None)
    mafia_votes: dict = field(default_factory=dict)     # user_id -> target_id
    votes: dict = field(default_factory=dict)           # voter_id -> target_id
    events: asyncio.Event | None = None
    required: set = field(default_factory=set)          # players that must act this night
    prompt_msgs: dict = field(default_factory=dict)     # user_id -> private action message id
    last_night: dict = field(default_factory=dict)      # summary of the last night resolution
    result: dict | None = None
    stopped_notice_sent: bool = False
    winner: str | None = None

    @property
    def count(self) -> int:
        return len(self.players)

    def alive_players(self) -> list:
        return [p for p in self.players.values() if p.alive]

    def idx_of(self, user_id: int) -> int:
        return list(self.players).index(user_id)

    def player_at(self, idx: int):
        try:
            return list(self.players.values())[idx]
        except IndexError:
            return None

    def seconds_left(self) -> float:
        return max(0.0, self.lobby_deadline - time.monotonic())

    def spawn(self, coro):
        t = asyncio.create_task(coro)
        self.tasks.add(t)
        t.add_done_callback(self.tasks.discard)
        return t

    def cancel_tasks(self, except_current: bool = True):
        cur = asyncio.current_task()
        for t in list(self.tasks):
            if except_current and t is cur:
                continue
            t.cancel()


# ----------------------------------------------------------------- registry
GAMES: dict[int, Game] = {}        # game_id -> Game
BY_CHAT: dict[int, Game] = {}      # chat_id -> active Game (one per group)
USER_GAME: dict[int, int] = {}     # user_id -> game_id (one active game per user)


def register(game: Game):
    GAMES[game.game_id] = game
    BY_CHAT[game.chat_id] = game


def unregister(game: Game):
    GAMES.pop(game.game_id, None)
    if BY_CHAT.get(game.chat_id) is game:
        BY_CHAT.pop(game.chat_id, None)
    for uid in list(game.players):
        if USER_GAME.get(uid) == game.game_id:
            USER_GAME.pop(uid, None)


# ================================================================= lifecycle
import logging  # noqa: E402

from telegram.error import Forbidden, TelegramError  # noqa: E402

from database.db import db  # noqa: E402
from game import roles  # noqa: E402
from services.gif_manager import send_gif  # noqa: E402
from utils import rich, texts  # noqa: E402

log = logging.getLogger(__name__)


async def _delete_quiet(bot, chat_id, message_id):
    if not message_id:
        return
    try:
        await bot.delete_message(chat_id, message_id)
    except TelegramError:
        pass


async def cancel_game(bot, game: Game, reason: str):
    """Safely cancel a game in any pre-finish state."""
    if game.status in ("finished", "cancelled"):
        return
    was_active = game.status == "active"
    game.status = "cancelled"
    game.phase = "over"
    game.cancel_tasks()
    await db.update_game(game.game_id, status="cancelled", ended_at=_now())
    await _delete_quiet(bot, game.chat_id, game.list_msg_id)
    scr = texts.notice("❌ Game cancelled", reason)
    if (not was_active) and game.lobby_msg_id and await rich.edit_screen(bot, game.chat_id, game.lobby_msg_id, scr):
        pass
    else:
        try:
            await rich.send_screen(bot, game.chat_id, scr, thread_id=game.thread_id)
        except TelegramError:
            pass
    unregister(game)


def _now():
    from database.db import utcnow
    return utcnow()


async def start_game(bot, game: Game) -> bool:
    async with game.lock:
        if game.status != "lobby":
            return False
        if game.count < game.min_players:
            return False
        game.status = "starting"
    game.cancel_tasks()
    await db.update_game(game.game_id, status="starting")

    ids = list(game.players)
    mapping = roles.assign_roles(ids, bool(game.settings.get("advanced_roles")))
    for uid, role in mapping.items():
        p = game.players[uid]
        p.role = role
        for a in roles.ROLES[role].actions:
            if a.uses is not None:
                p.uses[a.key] = a.uses
    import random
    town = [u for u, r in mapping.items() if roles.team_of(r) == "town"]
    for uid, role in mapping.items():
        if role == "executioner" and town:
            game.players[uid].exec_target = random.choice(town)

    # --- private role cards (must succeed for everyone) ---
    failed = []
    mafia_ids = [u for u in ids if roles.team_of(mapping[u]) == "mafia"]
    for uid in ids:
        p = game.players[uid]
        mates = None
        if p.role and roles.team_of(p.role) == "mafia":
            mates = [f"{game.players[m].name} ({roles.ROLES[mapping[m]].name})" for m in mafia_ids if m != uid] or None
        target = game.players[p.exec_target].name if p.exec_target else None
        try:
            await rich.send_screen(bot, uid, texts.role_card(p.role, mates, target))
        except Forbidden:
            failed.append(p)
            await db.set_dm_ok(uid, False)
        except TelegramError as e:
            log.warning("role card to %s failed: %s", uid, e)
            failed.append(p)
        await asyncio.sleep(0.05)
    if failed:
        names = ", ".join(p.name for p in failed)
        await cancel_game(bot, game, f"I could not send secret roles to: {names}. "
                                     "They must open a private chat with me and press Start, then try again.")
        return False

    await db.transaction(
        [("UPDATE games SET status='active', started_at=? WHERE game_id=?", (_now(), game.game_id))] +
        [("UPDATE game_players SET role=? WHERE game_id=? AND user_id=?", (r, game.game_id, u)) for u, r in mapping.items()] +
        [("INSERT INTO role_history(user_id, role) VALUES(?,?)", (u, r)) for u, r in mapping.items()])
    game.status = "active"
    await _delete_quiet(bot, game.chat_id, game.list_msg_id)
    scr = texts.game_started(game, len(mafia_ids))
    if not (game.lobby_msg_id and await rich.edit_screen(bot, game.chat_id, game.lobby_msg_id, scr)):
        await rich.send_screen(bot, game.chat_id, scr, thread_id=game.thread_id)
    await send_gif(bot, game.chat_id, "GAME_START_GIF", game.thread_id)

    from game import night
    game.spawn(night.run_game(bot, game))
    return True


# ================================================================= shared end-of-game / death helpers
async def after_deaths(bot, game: Game):
    """Mafia promotion and executioner -> jester conversion after any death."""
    import random
    from game import night
    alive = game.alive_players()
    mafia = [p for p in alive if roles.team_of(p.role) == "mafia"]
    if mafia and not any(p.role in roles.KILLER_MAFIA for p in mafia):
        new = random.choice(mafia)
        new.role = "mafia"
        await night.dm(bot, new.user_id, texts.notice("🔪 Promoted", "Your team has no killer left. You are now a Mafia killer!"))
    for p in alive:
        if p.role == "executioner" and p.exec_target and not game.players[p.exec_target].alive:
            p.role = "jester"
            await night.dm(bot, p.user_id, texts.notice("🤡 Your target died", "You are now a Jester: get voted out to win!"))


async def check_end(bot, game: Game) -> bool:
    from game import win_conditions
    res = win_conditions.evaluate(game)
    if res:
        await finish_game(bot, game, res)
        return True
    return False


async def finish_game(bot, game: Game, result: dict):
    from services import statistics
    if game.status in ("finished", "cancelled"):
        return
    game.status, game.phase, game.result = "finished", "over", result
    game.cancel_tasks()
    stats = await statistics.finish_game(game, result)
    await db.update_game(game.game_id, status="finished", phase="over", winner=result.get("team") or "draw", ended_at=_now())
    rows = []
    for uid, p in game.players.items():
        label, xp = stats[uid]
        r = roles.ROLES[p.role]
        rows.append([p.name, f"{r.emoji} {r.name}", {"win": "🏆 Won", "loss": "Lost", "left": "Left"}[label], f"+{xp}"])
    gif = {"town": "TOWN_WIN_GIF", "mafia": "MAFIA_WIN_GIF", "neutral": "NEUTRAL_WIN_GIF"}.get(result.get("team"), "GAME_OVER_GIF")
    await send_gif(bot, game.chat_id, gif, game.thread_id)
    await rich.send_screen(bot, game.chat_id, texts.game_over(result["title"], result["text"], rows, game.day_no), thread_id=game.thread_id)
    await send_gif(bot, game.chat_id, "GAME_OVER_GIF", game.thread_id)
    unregister(game)
