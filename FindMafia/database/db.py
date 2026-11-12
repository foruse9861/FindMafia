"""Async SQLite layer (aiosqlite). SQL is kept simple/portable so PostgreSQL migration is easy."""
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import aiosqlite

import config

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
  dm_ok INTEGER NOT NULL DEFAULT 0,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP, last_seen TEXT, last_daily TEXT);
CREATE TABLE IF NOT EXISTS profiles(
  user_id INTEGER PRIMARY KEY REFERENCES users(user_id),
  xp INTEGER NOT NULL DEFAULT 0, level INTEGER NOT NULL DEFAULT 1,
  games INTEGER NOT NULL DEFAULT 0, wins INTEGER NOT NULL DEFAULT 0, losses INTEGER NOT NULL DEFAULT 0,
  mafia_wins INTEGER NOT NULL DEFAULT 0, town_wins INTEGER NOT NULL DEFAULT 0, neutral_wins INTEGER NOT NULL DEFAULT 0,
  eliminations INTEGER NOT NULL DEFAULT 0, survived INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS groups(
  chat_id INTEGER PRIMARY KEY, title TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS games(
  game_id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, thread_id INTEGER,
  host_id INTEGER, status TEXT NOT NULL DEFAULT 'lobby', phase TEXT, day_no INTEGER NOT NULL DEFAULT 0,
  lobby_msg_id INTEGER, phase_msg_id INTEGER, vote_msg_id INTEGER, winner TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP, started_at TEXT, ended_at TEXT);
CREATE INDEX IF NOT EXISTS idx_games_chat_status ON games(chat_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS uq_active_game ON games(chat_id) WHERE status IN ('lobby','starting','active');
CREATE TABLE IF NOT EXISTS game_players(
  game_id INTEGER NOT NULL REFERENCES games(game_id), user_id INTEGER NOT NULL,
  name TEXT, role TEXT, alive INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(game_id, user_id));
CREATE TABLE IF NOT EXISTS game_history(
  id INTEGER PRIMARY KEY AUTOINCREMENT, game_id INTEGER, user_id INTEGER, role TEXT, team TEXT,
  result TEXT, xp INTEGER, ts TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS idx_history_user ON game_history(user_id);
CREATE TABLE IF NOT EXISTS role_history(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, role TEXT, ts TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS idx_role_history_user ON role_history(user_id);
CREATE TABLE IF NOT EXISTS votes(
  game_id INTEGER NOT NULL, day_no INTEGER NOT NULL, voter_id INTEGER NOT NULL, target_id INTEGER NOT NULL,
  PRIMARY KEY(game_id, day_no, voter_id));
CREATE TABLE IF NOT EXISTS xp_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, xp INTEGER NOT NULL, reason TEXT,
  ts TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS idx_xp_ts ON xp_log(ts);
CREATE INDEX IF NOT EXISTS idx_xp_user ON xp_log(user_id);
CREATE TABLE IF NOT EXISTS achievements(
  user_id INTEGER NOT NULL, key TEXT NOT NULL, earned_at TEXT DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(user_id, key));
CREATE TABLE IF NOT EXISTS settings(
  chat_id INTEGER NOT NULL, key TEXT NOT NULL, value TEXT, PRIMARY KEY(chat_id, key));
CREATE TABLE IF NOT EXISTS banned_users(
  user_id INTEGER PRIMARY KEY, reason TEXT, banned_at TEXT DEFAULT CURRENT_TIMESTAMP);
"""

DEFAULT_SETTINGS = {
    "min_players": config.MIN_PLAYERS,
    "max_players": config.MAX_PLAYERS,
    "lobby_seconds": config.LOBBY_SECONDS,
    "night_seconds": config.NIGHT_SECONDS,
    "discussion_seconds": config.DISCUSSION_SECONDS,
    "voting_seconds": config.VOTING_SECONDS,
    "advanced_roles": 0,
    "hardcore": 0,
    "secret_voting": 0,
    "rich": 1,
    "tie_rule": 0,          # 0 = nobody eliminated on a tie, 1 = random among tied
}


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class Database:
    def __init__(self, path: str):
        self.path = path
        self.conn: aiosqlite.Connection | None = None

    async def init(self):
        d = os.path.dirname(self.path)
        if d:
            os.makedirs(d, exist_ok=True)
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode=WAL")
        await self.conn.execute("PRAGMA foreign_keys=ON")
        await self.conn.executescript(SCHEMA)
        await self.conn.commit()

    async def close(self):
        if self.conn:
            await self.conn.close()
            self.conn = None

    # ---- low level helpers ----
    async def execute(self, sql, params=()):
        cur = await self.conn.execute(sql, params)
        await self.conn.commit()
        return cur

    async def fetchone(self, sql, params=()):
        async with self.conn.execute(sql, params) as cur:
            return await cur.fetchone()

    async def fetchall(self, sql, params=()):
        async with self.conn.execute(sql, params) as cur:
            return await cur.fetchall()

    async def transaction(self, statements):
        """Run [(sql, params), ...] atomically."""
        try:
            for sql, params in statements:
                await self.conn.execute(sql, params)
            await self.conn.commit()
        except Exception:
            await self.conn.rollback()
            raise

    # ---- users ----
    async def upsert_user(self, user_id, username, first_name, dm_ok=None):
        await self.transaction([
            ("INSERT INTO users(user_id, username, first_name, last_seen) VALUES(?,?,?,?) "
             "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name, last_seen=excluded.last_seen",
             (user_id, username, first_name, utcnow())),
            ("INSERT OR IGNORE INTO profiles(user_id) VALUES(?)", (user_id,)),
        ])
        if dm_ok is not None:
            await self.execute("UPDATE users SET dm_ok=? WHERE user_id=?", (1 if dm_ok else 0, user_id))

    async def set_dm_ok(self, user_id, ok: bool):
        await self.execute("UPDATE users SET dm_ok=? WHERE user_id=?", (1 if ok else 0, user_id))

    async def is_dm_ok(self, user_id) -> bool:
        r = await self.fetchone("SELECT dm_ok FROM users WHERE user_id=?", (user_id,))
        return bool(r and r["dm_ok"])

    async def get_profile(self, user_id):
        r = await self.fetchone(
            "SELECT u.user_id, u.username, u.first_name, p.* FROM users u JOIN profiles p ON p.user_id=u.user_id WHERE u.user_id=?",
            (user_id,))
        return dict(r) if r else None

    async def favorite_role(self, user_id):
        r = await self.fetchone(
            "SELECT role, COUNT(*) c FROM role_history WHERE user_id=? GROUP BY role ORDER BY c DESC LIMIT 1", (user_id,))
        return r["role"] if r else None

    async def earned_achievements(self, user_id) -> set:
        rows = await self.fetchall("SELECT key FROM achievements WHERE user_id=?", (user_id,))
        return {r["key"] for r in rows}

    async def user_count(self):
        return (await self.fetchone("SELECT COUNT(*) c FROM users"))["c"]

    # ---- groups & settings ----
    async def ensure_group(self, chat_id, title):
        await self.execute(
            "INSERT INTO groups(chat_id, title) VALUES(?,?) ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title",
            (chat_id, title))

    async def group_count(self):
        return (await self.fetchone("SELECT COUNT(*) c FROM groups"))["c"]

    async def get_setting(self, chat_id, key) -> int:
        r = await self.fetchone("SELECT value FROM settings WHERE chat_id=? AND key=?", (chat_id, key))
        if r is not None and r["value"] is not None:
            try:
                return int(r["value"])
            except ValueError:
                pass
        return int(DEFAULT_SETTINGS[key])

    async def set_setting(self, chat_id, key, value):
        if key not in DEFAULT_SETTINGS:
            raise KeyError(key)
        await self.execute(
            "INSERT INTO settings(chat_id,key,value) VALUES(?,?,?) ON CONFLICT(chat_id,key) DO UPDATE SET value=excluded.value",
            (chat_id, key, str(int(value))))

    async def all_settings(self, chat_id) -> dict:
        return {k: await self.get_setting(chat_id, k) for k in DEFAULT_SETTINGS}

    async def chats_with_rich_off(self):
        rows = await self.fetchall("SELECT chat_id FROM settings WHERE key='rich' AND value='0'")
        return {r["chat_id"] for r in rows}

    # ---- bans ----
    async def is_banned(self, user_id) -> bool:
        return (await self.fetchone("SELECT 1 FROM banned_users WHERE user_id=?", (user_id,))) is not None

    async def ban(self, user_id, reason=""):
        await self.execute("INSERT OR REPLACE INTO banned_users(user_id, reason) VALUES(?,?)", (user_id, reason))

    async def unban(self, user_id):
        await self.execute("DELETE FROM banned_users WHERE user_id=?", (user_id,))

    async def banned_count(self):
        return (await self.fetchone("SELECT COUNT(*) c FROM banned_users"))["c"]

    # ---- games ----
    async def create_game(self, chat_id, thread_id, host_id) -> int:
        cur = await self.execute("INSERT INTO games(chat_id, thread_id, host_id) VALUES(?,?,?)", (chat_id, thread_id, host_id))
        return cur.lastrowid

    async def update_game(self, game_id, **fields):
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        await self.execute(f"UPDATE games SET {cols} WHERE game_id=?", (*fields.values(), game_id))

    async def add_game_player(self, game_id, user_id, name):
        await self.execute("INSERT OR IGNORE INTO game_players(game_id,user_id,name) VALUES(?,?,?)", (game_id, user_id, name))

    async def remove_game_player(self, game_id, user_id):
        await self.execute("DELETE FROM game_players WHERE game_id=? AND user_id=?", (game_id, user_id))

    async def set_player_state(self, game_id, user_id, role=None, alive=None):
        if role is not None:
            await self.execute("UPDATE game_players SET role=? WHERE game_id=? AND user_id=?", (role, game_id, user_id))
        if alive is not None:
            await self.execute("UPDATE game_players SET alive=? WHERE game_id=? AND user_id=?", (1 if alive else 0, game_id, user_id))

    async def unfinished_games(self):
        rows = await self.fetchall("SELECT * FROM games WHERE status IN ('lobby','starting','active')")
        return [dict(r) for r in rows]

    async def active_game_count(self):
        return (await self.fetchone("SELECT COUNT(*) c FROM games WHERE status IN ('lobby','starting','active')"))["c"]

    async def games_total(self):
        return (await self.fetchone("SELECT COUNT(*) c FROM games WHERE status='finished'"))["c"]

    # ---- votes ----
    async def save_vote(self, game_id, day_no, voter_id, target_id):
        await self.execute(
            "INSERT INTO votes(game_id,day_no,voter_id,target_id) VALUES(?,?,?,?) "
            "ON CONFLICT(game_id,day_no,voter_id) DO UPDATE SET target_id=excluded.target_id",
            (game_id, day_no, voter_id, target_id))

    # ---- xp / leaderboard ----
    async def leaderboard(self, period: str, limit: int, offset: int):
        now = datetime.now(timezone.utc)
        since = {"day": now - timedelta(days=1), "week": now - timedelta(days=7), "month": now - timedelta(days=30)}.get(period)
        if since is None:  # all time
            rows = await self.fetchall(
                "SELECT u.user_id, u.first_name, u.username, p.xp AS score, p.wins FROM profiles p "
                "JOIN users u ON u.user_id=p.user_id WHERE p.xp>0 ORDER BY p.xp DESC, p.wins DESC LIMIT ? OFFSET ?",
                (limit, offset))
        else:
            rows = await self.fetchall(
                "SELECT u.user_id, u.first_name, u.username, SUM(x.xp) AS score, p.wins FROM xp_log x "
                "JOIN users u ON u.user_id=x.user_id JOIN profiles p ON p.user_id=u.user_id "
                "WHERE x.ts>=? GROUP BY u.user_id HAVING score>0 ORDER BY score DESC LIMIT ? OFFSET ?",
                (since.strftime("%Y-%m-%d %H:%M:%S"), limit, offset))
        return [dict(r) for r in rows]

    # ---- backup ----
    async def backup(self, dest: str):
        """Consistent online backup using a separate read connection in a worker thread."""
        import asyncio
        import sqlite3
        d = os.path.dirname(dest)
        if d:
            os.makedirs(d, exist_ok=True)
        await self.conn.commit()

        def _run(src_path, dst_path):
            if os.path.exists(dst_path):
                os.remove(dst_path)
            s, t = sqlite3.connect(src_path), sqlite3.connect(dst_path)
            try:
                s.backup(t)
            finally:
                t.close(); s.close()
        await asyncio.to_thread(_run, self.path, dest)
        return dest


db = Database(config.DB_PATH)
