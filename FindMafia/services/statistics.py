"""End-of-game stats, XP (with anti-farming cap), achievements, daily/weekly rewards."""
from datetime import datetime, timedelta, timezone

from database.db import db, utcnow
from game import roles as R
from services import xp_system
from services.achievements import ACHIEVEMENTS

DAILY_GAME_XP_CAP = 300
WEEKLY = [("Play 5 games this week", "play5", 5, 50), ("Win 2 games this week", "win2", 2, 75)]


def _week_start() -> str:
    now = datetime.now(timezone.utc)
    return (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d 00:00:00")


async def _grant(uid: int, xp: int, reason: str) -> int:
    if xp <= 0:
        return 0
    await db.transaction([
        ("INSERT INTO xp_log(user_id,xp,reason,ts) VALUES(?,?,?,?)", (uid, xp, reason, utcnow())),
        ("UPDATE profiles SET xp=xp+? WHERE user_id=?", (xp, uid))])
    p = await db.get_profile(uid)
    await db.execute("UPDATE profiles SET level=? WHERE user_id=?", (xp_system.level_for(p["xp"]), uid))
    return xp


async def claim_daily(uid: int) -> int:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    r = await db.fetchone("SELECT last_daily FROM users WHERE user_id=?", (uid,))
    if not r or r["last_daily"] == today:
        return 0
    await db.execute("UPDATE users SET last_daily=? WHERE user_id=?", (today, uid))
    return await _grant(uid, xp_system.XP["daily"], "Daily login reward")


async def finish_game(game, result: dict) -> dict:
    """Persist results. Returns {uid: (label, xp)}. Players who left the group (fled) get nothing."""
    winners = set(result.get("winners", []))
    out = {}
    since = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    for uid, p in game.players.items():
        if p.fled:
            out[uid] = ("left", 0)
            continue
        won = uid in winners
        team = R.team_of(p.role)
        xp = xp_system.XP["participate"] + (xp_system.XP["win"] if won else 0) + (xp_system.XP["survive"] if p.alive else 0) \
            + xp_system.XP["elimination"] * p.kills
        used = (await db.fetchone("SELECT COALESCE(SUM(xp),0) s FROM xp_log WHERE user_id=? AND ts>=? AND reason LIKE 'Game %'", (uid, since)))["s"]
        xp = max(0, min(xp, DAILY_GAME_XP_CAP - used))
        await db.transaction([
            ("UPDATE profiles SET games=games+1, wins=wins+?, losses=losses+?, mafia_wins=mafia_wins+?, town_wins=town_wins+?, "
             "neutral_wins=neutral_wins+?, eliminations=eliminations+?, survived=survived+? WHERE user_id=?",
             (int(won), int(not won), int(won and team == "mafia"), int(won and team == "town"), int(won and team == "neutral"),
              p.kills, int(p.alive), uid)),
            ("INSERT INTO game_history(game_id,user_id,role,team,result,xp) VALUES(?,?,?,?,?,?)",
             (game.game_id, uid, p.role, team, "win" if won else "loss", xp))])
        await _grant(uid, xp, f"Game #{game.game_id} {'win' if won else 'played'}")
        out[uid] = ("win" if won else "loss", xp)
        await _award(uid)
        await _weekly(uid)
    return out


async def _award(uid: int):
    p = await db.get_profile(uid)
    det = (await db.fetchone("SELECT COUNT(*) c FROM game_history WHERE user_id=? AND role='detective' AND result='win'", (uid,)))["c"]
    checks = {"first_victory": p["wins"] >= 1, "mafia_master": p["mafia_wins"] >= 5, "detective_expert": det >= 3,
              "survivor": p["survived"] >= 5, "games_10": p["games"] >= 10, "games_50": p["games"] >= 50, "games_100": p["games"] >= 100}
    for k, ok in checks.items():
        if ok and k in ACHIEVEMENTS:
            await db.execute("INSERT OR IGNORE INTO achievements(user_id,key) VALUES(?,?)", (uid, k))


async def weekly_progress(uid: int) -> list[tuple[str, int, int]]:
    ws = _week_start()
    played = (await db.fetchone("SELECT COUNT(*) c FROM game_history WHERE user_id=? AND ts>=?", (uid, ws)))["c"]
    won = (await db.fetchone("SELECT COUNT(*) c FROM game_history WHERE user_id=? AND ts>=? AND result='win'", (uid, ws)))["c"]
    return [(WEEKLY[0][0], played, WEEKLY[0][2]), (WEEKLY[1][0], won, WEEKLY[1][2])]


async def _weekly(uid: int):
    ws = _week_start()
    prog = await weekly_progress(uid)
    for (name, key, target, reward), (_n, cur, _t) in zip(WEEKLY, prog):
        reason = f"Weekly challenge: {name} ({ws[:10]})"
        if cur >= target and not await db.fetchone("SELECT 1 FROM xp_log WHERE user_id=? AND reason=?", (uid, reason)):
            await _grant(uid, reward, reason)


async def recent_rewards(uid: int, limit: int = 5) -> list[dict]:
    rows = await db.fetchall("SELECT reason, xp FROM xp_log WHERE user_id=? ORDER BY id DESC LIMIT ?", (uid, limit))
    return [dict(r) for r in rows]
