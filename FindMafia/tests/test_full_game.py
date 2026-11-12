"""Plays complete games through the real handlers with a fake network.  python -m tests.test_full_game"""
import asyncio
import logging

import config
from database.db import db
from game import engine, lobby
from game import roles as R
from keyboards import role_buttons as rb
from tests.fake_request import FakeRequest
from tests.harness import boot, cb_update, chat, msg_update, send, shutdown, user

config.EDIT_INTERVAL = 0.3
lobby.MIN_REFRESH_GAP = 0.01
logging.getLogger().setLevel(logging.ERROR)
G = -1001


async def setup(n, advanced=0):
    engine.GAMES.clear(); engine.BY_CHAT.clear(); engine.USER_GAME.clear()
    fake = FakeRequest(); app = await boot(fake)
    for k in ("night_seconds", "discussion_seconds", "voting_seconds"):
        await db.set_setting(G, k, 1)
    await db.set_setting(G, "advanced_roles", advanced)
    for i in range(1, n + 1):
        await send(app, msg_update(app, "/start", user(i), chat(i, "private")))
    await send(app, msg_update(app, "/play", user(1), chat(G)))
    g = engine.BY_CHAT[G]
    for i in range(2, n + 1):
        await send(app, cb_update(app, f"lob:join:{g.game_id}", user(i), chat(G), g.lobby_msg_id))
    await send(app, cb_update(app, f"lob:start:{g.game_id}", user(1), chat(G), g.lobby_msg_id))
    assert g.status == "active"
    return fake, app, g


async def play(app, g, vote_for_team, max_rounds=12):
    """Night: everyone with an action picks a sensible target. Day: all alive vote for a player of `vote_for_team`."""
    for _ in range(max_rounds):
        # wait for night prompts
        for _w in range(200):
            if g.status != "active" or (g.phase == "night" and g.required):
                break
            await asyncio.sleep(0.05)
        if g.status != "active":
            break
        if g.phase == "night":
            tok = g.phase_token
            for uid in list(g.required):
                p = g.players[uid]
                for a in rb.usable_actions(p)[:1]:
                    if a.target is None:
                        await send(app, cb_update(app, f"act:{g.game_id}:{tok}:go:{a.key}", user(uid), chat(uid, "private"), 5))
                        continue
                    tg = rb.targets_for(g, p, a)
                    if a.key in ("kill",):
                        tg = [t for t in tg if R.team_of(t.role) == "town"] or tg
                    if tg:
                        await send(app, cb_update(app, f"act:{g.game_id}:{tok}:t:{a.key}:{g.idx_of(tg[0].user_id)}", user(uid), chat(uid, "private"), 5))
        # wait for voting
        for _w in range(400):
            if g.status != "active" or g.phase == "voting":
                break
            await asyncio.sleep(0.05)
        if g.status != "active":
            break
        tok = g.phase_token
        targets = [p for p in g.alive_players() if R.team_of(p.role) == vote_for_team] or g.alive_players()
        for v in g.alive_players():
            t = next((x for x in targets if x.user_id != v.user_id), None)
            if t:
                await send(app, cb_update(app, f"vote:{g.game_id}:{tok}:{g.idx_of(t.user_id)}", user(v.user_id), chat(G), g.vote_msg_id or 1))
        for _w in range(100):
            if g.status != "active" or g.phase != "voting":
                break
            await asyncio.sleep(0.05)
    for _w in range(100):
        if g.status == "finished":
            break
        await asyncio.sleep(0.05)


async def t_town_wins():
    fake, app, g = await setup(7)
    await play(app, g, "mafia")
    assert g.status == "finished" and g.result["team"] == "town", (g.status, g.result)
    w = await db.fetchone("SELECT COUNT(*) c FROM game_history WHERE game_id=? AND result='win'", (g.game_id,))
    assert w["c"] >= 5
    prof = await db.get_profile(next(u for u, p in g.players.items() if R.team_of(p.role) == "town"))
    assert prof["games"] == 1 and prof["wins"] == 1 and prof["xp"] >= 35, prof
    assert any("GAME OVER" in str(p) or "TOWN WINS" in str(p) for n, p in fake.calls if p.get("chat_id") == G)
    print("ok town_wins; xp", prof["xp"])


async def t_mafia_wins():
    fake, app, g = await setup(5)
    await play(app, g, "town")
    assert g.status == "finished" and g.result["team"] == "mafia", (g.status, g.result)
    print("ok mafia_wins")


async def t_advanced_games_finish_without_crash():
    for n in (8, 12, 16):
        fake, app, g = await setup(n, advanced=1)
        await play(app, g, "mafia", max_rounds=20)
        assert g.status in ("finished",), (n, g.status, g.phase)
        print("ok advanced", n, "->", g.result["title"])
        await shutdown(app)


async def t_dead_player_cannot_act_and_stale_buttons():
    fake, app, g = await setup(6)
    for _w in range(100):
        if g.phase == "night" and g.required:
            break
        await asyncio.sleep(0.05)
    old = g.phase_token
    uid = next(iter(g.required))
    p = g.players[uid]
    a = rb.usable_actions(p)[0]
    # wrong chat (group) is rejected
    fake.clear()
    await send(app, cb_update(app, f"act:{g.game_id}:{old}:skip", user(uid), chat(G), 5))
    assert "over" in fake.of("answerCallbackQuery")[-1]["text"]
    for u in list(g.required):
        await send(app, cb_update(app, f"act:{g.game_id}:{old}:skip", user(u), chat(u, "private"), 5))
    await asyncio.sleep(0.5)
    fake.clear()
    await send(app, cb_update(app, f"act:{g.game_id}:{old}:skip", user(uid), chat(uid, "private"), 5))
    assert "over" in fake.of("answerCallbackQuery")[-1]["text"], "stale token must be rejected"
    p.alive = False
    for _w in range(100):
        if g.phase == "voting":
            break
        await asyncio.sleep(0.05)
    fake.clear()
    await send(app, cb_update(app, f"vote:{g.game_id}:{g.phase_token}:0", user(uid), chat(G), g.vote_msg_id))
    assert "living" in fake.of("answerCallbackQuery")[-1]["text"]
    voter = g.alive_players()[0]
    await send(app, cb_update(app, f"vote:{g.game_id}:{g.phase_token}:{g.idx_of(voter.user_id)}", user(voter.user_id), chat(G), g.vote_msg_id))
    assert "yourself" in fake.of("answerCallbackQuery")[-1]["text"]
    print("ok dead/stale/self-vote guards")


async def main():
    for t in (t_town_wins, t_mafia_wins, t_advanced_games_finish_without_crash, t_dead_player_cannot_act_and_stale_buttons):
        fake_app = None
        try:
            await asyncio.wait_for(t(), 120)
        finally:
            from tests import harness
            for g in list(engine.GAMES.values()):
                g.cancel_tasks(except_current=False)
            await db.close()
    print("ALL FULL-GAME TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
